"""
Lazy caching layer around yt-dlp.

The library config only ever stores YouTube URLs (easy to curate).
This module is responsible for turning a URL into a local, hardware-decodable
file the first time it's needed, and remembering that mapping afterward so
every later play is instant and offline.
"""
import json
import os
import threading

import config

_index_lock = threading.Lock()

# Serializes concurrent downloads of the *same* URL (e.g. two web-mode
# sessions whose genre/era pools overlap, or warm_cache racing a live
# playback pick at startup) -- without this, two threads can both pass the
# "not cached yet" check and race on the same staged file. Keyed by url and
# guarded by its own lock since _index_lock is only held for the brief
# index read/write, not the whole download.
_download_locks = {}
_download_locks_guard = threading.Lock()


def _get_download_lock(url):
    with _download_locks_guard:
        return _download_locks.setdefault(url, threading.Lock())


def _load_index():
    if not os.path.exists(config.INDEX_FILE):
        return {}
    with open(config.INDEX_FILE, "r") as f:
        return json.load(f)


def _save_index(index):
    tmp_path = config.INDEX_FILE + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(index, f, indent=2)
    os.replace(tmp_path, config.INDEX_FILE)  # atomic on POSIX


def get_cached_path(url):
    """Return the local file path for a URL if it's already cached, else None."""
    index = _load_index()
    path = index.get(url)
    if path and os.path.exists(path):
        return path
    return None


def ensure_cached(url, progress_hook=None, force=False):
    """
    Return a local playable path for `url`, downloading it first if needed.
    Safe to call from multiple threads/processes; index writes are locked.

    `force=True` skips the already-cached check and redownloads even if an
    index entry/file already exists (e.g. after a FORMAT_SELECTOR change,
    to replace files fetched under the old selector).

    Downloads land in a staging subdirectory first and are only moved
    (os.replace, atomic on the same filesystem) into VIDEO_DIR once the
    download+merge fully succeeds -- the existing cached file, if any, is
    left completely untouched until that swap. Learned the hard way: an
    earlier version downloaded straight to the real VIDEO_DIR path with
    yt-dlp's `overwrites` option, which deletes the destination file
    *before* attempting the new download -- a mid-run failure (e.g.
    YouTube rate-limiting during a bulk forced recache) then left several
    previously-working tracks with no cached file at all.
    """
    if not force:
        cached = get_cached_path(url)
        if cached:
            return cached

    with _get_download_lock(url):
        # Re-check now that we hold the per-URL lock -- another thread may
        # have just finished downloading this exact URL while we were
        # waiting for it.
        if not force:
            cached = get_cached_path(url)
            if cached:
                return cached

        # Import here so the rest of the app doesn't hard-require yt-dlp
        # just to browse the menu.
        import yt_dlp

        config.ensure_dirs()
        staging_dir = os.path.join(config.VIDEO_DIR, ".incoming")
        os.makedirs(staging_dir, exist_ok=True)

        # Deliberately no yt-dlp `download_archive` option here -- get_cached_path()
        # above is already the authoritative "is this downloaded" check, and it's
        # file-existence-based so it self-heals if a cached file is ever removed
        # by hand. A separate yt-dlp-side "already downloaded" ledger doesn't know
        # about that removal and once ensure_cached() decides a real download is
        # needed, insists it's already done -- which crashes yt-dlp's own merge
        # logic ('NoneType' object has no attribute 'setdefault') rather than
        # actually re-downloading. Two ledgers that can disagree is worse than one.
        ydl_opts = {
            "format": config.FORMAT_SELECTOR,
            "merge_output_format": "mp4",
            "outtmpl": os.path.join(staging_dir, "%(id)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            # Staging output is always disposable (never the real cached file),
            # so it's always safe to overwrite a leftover from an interrupted
            # previous attempt for the same id, force or not.
            "overwrites": True,
        }
        if progress_hook:
            ydl_opts["progress_hooks"] = [progress_hook]

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            # extract_info can return a merged entry; prepare_filename gives the
            # pre-merge name, so recompute with the final container extension.
            base = ydl.prepare_filename(info)
            staged_path = os.path.splitext(base)[0] + ".mp4"

        if not os.path.exists(staged_path):
            raise RuntimeError(f"yt-dlp reported success but file not found: {staged_path}")

        final_path = os.path.join(config.VIDEO_DIR, os.path.basename(staged_path))
        os.replace(staged_path, final_path)

        with _index_lock:
            index = _load_index()
            index[url] = final_path
            _save_index(index)

        return final_path


def clear_incoming():
    """
    Remove any leftover partial-download files from the staging directory.
    Meant to run once, early, at process startup (see main.py) -- anything
    found here then must be from a download interrupted by a crash/kill in
    a previous run, since a fully-cached file only ever lives in VIDEO_DIR
    itself (moved there via the atomic os.replace in ensure_cached()), and
    no new download could legitimately be writing to .incoming yet this
    early. Safe to skip if it doesn't even exist.
    """
    staging_dir = os.path.join(config.VIDEO_DIR, ".incoming")
    if not os.path.isdir(staging_dir):
        return
    for name in os.listdir(staging_dir):
        path = os.path.join(staging_dir, name)
        try:
            os.remove(path)
        except OSError as e:
            print(f"[video_cache] Could not remove stale incoming file {path}: {e}")


def prune(library):
    """
    Remove cached video files (and their index entries) for URLs no longer
    present in `library`. Meant to run right after a library.csv update --
    deleting a row should eventually free its disk space too, without
    touching anything still in use. Returns the list of URLs removed.
    """
    import library as library_module  # local import to avoid a cycle at module load time
    valid_urls = {t["url"] for t in library_module.all_tracks(library)}

    with _index_lock:
        index = _load_index()
        removed = []
        for url, path in list(index.items()):
            if url in valid_urls:
                continue
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError as e:
                    print(f"[video_cache] Could not remove {path}: {e}")
                    continue
            del index[url]
            removed.append(url)

        if removed:
            _save_index(index)

    return removed


def warm_cache(library, on_progress=None, force=False):
    """
    Walk the entire library and download anything not yet cached.
    Intended to run as a nightly cron job / background task, not during a party.
    `library` is the genre -> era -> [track dicts] structure from library.py.

    `on_progress(i, total, genre, era, track, err)` is called after each
    attempt (err is None on success) -- genre/era are passed alongside the
    track dict (rather than flattening via library.all_tracks(), which
    drops them) so callers can record a full identity for failures.

    `force=True` redownloads every track regardless of what's already
    cached (see ensure_cached) -- e.g. after a FORMAT_SELECTOR change,
    to replace files fetched under the old selector.
    """
    entries = [
        (genre, era, track)
        for genre, eras in library.items()
        for era, tracks in eras.items()
        for track in tracks
    ]

    total = len(entries)
    for i, (genre, era, track) in enumerate(entries, start=1):
        try:
            ensure_cached(track["url"], force=force)
            if on_progress:
                on_progress(i, total, genre, era, track, None)
        except Exception as e:
            if on_progress:
                on_progress(i, total, genre, era, track, e)


if __name__ == "__main__":
    # Manual cache-warming run: `python3 video_cache.py [--force]`
    import argparse

    import library as library_module

    parser = argparse.ArgumentParser(description="Pre-warm the Spin Cycle video cache.")
    parser.add_argument(
        "--force", action="store_true",
        help="Redownload every track even if already cached (e.g. after a FORMAT_SELECTOR change).",
    )
    args = parser.parse_args()

    clear_incoming()
    lib = library_module.load_library(config.LIBRARY_FILE)

    def report(i, total, genre, era, track, err):
        label = f"{track['artist']} - {track['song']}" if track.get("artist") else track["url"]
        status = "OK" if err is None else f"FAILED ({err})"
        print(f"[{i}/{total}] {label} ({genre}/{era}) -> {status}")

    warm_cache(lib, on_progress=report, force=args.force)
