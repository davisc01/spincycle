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


def ensure_cached(url, progress_hook=None):
    """
    Return a local playable path for `url`, downloading it first if needed.
    Safe to call from multiple threads/processes; index writes are locked.
    """
    cached = get_cached_path(url)
    if cached:
        return cached

    # Import here so the rest of the app doesn't hard-require yt-dlp
    # just to browse the menu.
    import yt_dlp

    config.ensure_dirs()

    ydl_opts = {
        "format": config.FORMAT_SELECTOR,
        "merge_output_format": "mp4",
        "outtmpl": os.path.join(config.VIDEO_DIR, "%(id)s.%(ext)s"),
        "download_archive": config.ARCHIVE_FILE,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    if progress_hook:
        ydl_opts["progress_hooks"] = [progress_hook]

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        # extract_info can return a merged entry; prepare_filename gives the
        # pre-merge name, so recompute with the final container extension.
        base = ydl.prepare_filename(info)
        final_path = os.path.splitext(base)[0] + ".mp4"

    if not os.path.exists(final_path):
        raise RuntimeError(f"yt-dlp reported success but file not found: {final_path}")

    with _index_lock:
        index = _load_index()
        index[url] = final_path
        _save_index(index)

    return final_path


def prune(library):
    """
    Remove cached video files (and their index/download-archive entries)
    for URLs no longer present in `library`. Meant to run right after a
    library.csv update -- deleting a row should eventually free its disk
    space too, without touching anything still in use. Returns the list
    of URLs removed.
    """
    import library as library_module  # local import to avoid a cycle at module load time
    valid_urls = {t["url"] for t in library_module.all_tracks(library)}

    with _index_lock:
        index = _load_index()
        removed = []
        removed_ids = []
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
            removed_ids.append(os.path.splitext(os.path.basename(path))[0])

        if removed:
            _save_index(index)
            _prune_archive(removed_ids)

    return removed


def _prune_archive(video_ids):
    """Drop matching lines from yt-dlp's download-archive ledger so a
    re-added URL with the same video ID actually re-downloads instead of
    yt-dlp silently skipping it as 'already downloaded'."""
    if not video_ids or not os.path.exists(config.ARCHIVE_FILE):
        return
    stale_ids = set(video_ids)
    with open(config.ARCHIVE_FILE, "r") as f:
        lines = f.readlines()
    kept = [line for line in lines if line.split() and line.split()[-1] not in stale_ids]
    if len(kept) != len(lines):
        with open(config.ARCHIVE_FILE, "w") as f:
            f.writelines(kept)


def warm_cache(library, on_progress=None):
    """
    Walk the entire library and download anything not yet cached.
    Intended to run as a nightly cron job / background task, not during a party.
    `library` is the genre -> era -> [track dicts] structure from library.py.
    """
    import library as library_module  # local import to avoid a cycle at module load time
    tracks = library_module.all_tracks(library)

    total = len(tracks)
    for i, track in enumerate(tracks, start=1):
        url = track["url"]
        label = f"{track['artist']} - {track['song']}" if track.get("artist") else url
        try:
            ensure_cached(url)
            if on_progress:
                on_progress(i, total, label, None)
        except Exception as e:
            if on_progress:
                on_progress(i, total, label, e)


if __name__ == "__main__":
    # Manual cache-warming run: `python3 video_cache.py`
    import library as library_module

    lib = library_module.load_library(config.LIBRARY_FILE)

    def report(i, total, label, err):
        status = "OK" if err is None else f"FAILED ({err})"
        print(f"[{i}/{total}] {label} -> {status}")

    warm_cache(lib, on_progress=report)
