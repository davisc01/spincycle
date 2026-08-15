"""
Loads the library (a SQLite file, see config.LIBRARY_DB) into a
genre -> era -> [tracks] structure, where each "track" is a dict with
id/artist/song/url/genre/era -- so the UI can show "Artist - Song" instead
of a raw link, and callers that only have a track in hand (e.g. after a
wildcard genre/era pick) still know its real genre/era rather than just the
wildcard that was selected. The "id" is the stable primary key CRUD
operations (add_track/update_track/delete_track/set_cache_status) key off
of -- there's no assumption that url is unique (duplicate URLs exist in
real libraries).

The library used to be a hand-edited config/library.csv (columns:
artist,song,genre,era,url). That format is still fully supported for bulk
editing via import_csv()/export_csv_rows() -- see library_server.py's
/upload, /upload-append, and /library.csv routes -- but SQLite (config.
LIBRARY_DB) is now the live, continuously-read/written store. The first
time anything touches the library after upgrading, _ensure_db() imports
any existing library.csv into it once (see that function's docstring).
"""
import csv
import os
import shutil
import sqlite3
from datetime import datetime, timezone

REQUIRED_COLUMNS = {"artist", "song", "genre", "era", "url"}
CSV_COLUMNS = ["artist", "song", "genre", "era", "url"]

# Wildcard picks, appended to the real genre/era lists -- picking either
# (or both) plays across whatever dimension is left unconstrained.
ANY_GENRE = "Anything"
ANY_ERA = "Anytime"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    artist         TEXT NOT NULL DEFAULT '',
    song           TEXT NOT NULL DEFAULT '',
    genre          TEXT NOT NULL,
    era            TEXT NOT NULL,
    url            TEXT NOT NULL,
    cache_error    TEXT,
    cache_error_at TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_tracks_genre_era ON tracks(genre, era);
"""

_PLAYLIST_SCHEMA = """
CREATE TABLE IF NOT EXISTS playlists (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS playlist_tracks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_id INTEGER NOT NULL,
    track_id    INTEGER NOT NULL,
    UNIQUE(playlist_id, track_id)
);
CREATE INDEX IF NOT EXISTS idx_playlist_tracks_playlist ON playlist_tracks(playlist_id);
"""


def _connect(db_path):
    conn = sqlite3.connect(db_path, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_db(db_path):
    """
    Idempotent bootstrap, called as the first line of every public function
    in this module (mirrors load_library() already re-reading everything
    fresh on every call, so every existing call site gets migration for
    free with no separate init() step for main.py to remember to call).

    If db_path already exists, this is just a cheap os.path.exists check.
    Otherwise: create the schema, then, if a legacy library.csv sits next
    to it (config.LIBRARY_FILE), import every valid row from it (same
    tolerant skip-on-missing-genre/era/url behavior as this module always
    had) and copy that CSV to "<path>.pre-migration.bak" -- never deleted,
    so nothing is lost even if the import logic itself is ever wrong.
    Also best-effort folds in any leftover cache_failures.json from a
    pre-SQLite install, matching failed rows by url (matching more than
    one row on a duplicate url is harmless -- it self-corrects on the next
    warm-cache run either way).
    """
    if not os.path.exists(db_path):
        conn = _connect(db_path)
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()

        import config  # local import: config imports nothing from here, but avoids a cycle at module load time

        if os.path.exists(config.LIBRARY_FILE):
            imported = _import_csv_rows(db_path, config.LIBRARY_FILE, mode="append")
            print(f"[library] Migrated {imported['imported']} track(s) from {config.LIBRARY_FILE} into {db_path}.")
            shutil.copy2(config.LIBRARY_FILE, config.LIBRARY_FILE + ".pre-migration.bak")

        cache_failures_file = os.path.join(config.CACHE_ROOT, "cache_failures.json")
        if os.path.exists(cache_failures_file):
            import json
            try:
                with open(cache_failures_file, "r", encoding="utf-8") as f:
                    failures = json.load(f)
            except (OSError, ValueError):
                failures = []
            if failures:
                conn = _connect(db_path)
                try:
                    now = datetime.now(timezone.utc).isoformat()
                    for failure in failures:
                        conn.execute(
                            "UPDATE tracks SET cache_error = ?, cache_error_at = ? WHERE url = ?",
                            (failure.get("error", ""), now, failure.get("url", "")),
                        )
                    conn.commit()
                finally:
                    conn.close()

    # Runs on every call (not just for a brand-new db_path) so an existing
    # install's library.db picks up the playlists/playlist_tracks tables
    # the first time anything in this module runs after upgrading --
    # CREATE TABLE/INDEX IF NOT EXISTS make every call after the first a
    # cheap no-op.
    conn = _connect(db_path)
    try:
        conn.executescript(_PLAYLIST_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _row_to_track(row):
    return {
        "id": row["id"],
        "artist": row["artist"],
        "song": row["song"],
        "genre": row["genre"],
        "era": row["era"],
        "url": row["url"],
        "cache_error": row["cache_error"],
        "cache_error_at": row["cache_error_at"],
    }


def load_library(db_path):
    _ensure_db(db_path)
    library = {}
    conn = _connect(db_path)
    try:
        rows = conn.execute("SELECT * FROM tracks").fetchall()
    finally:
        conn.close()

    for row in rows:
        track = _row_to_track(row)
        library.setdefault(track["genre"], {}).setdefault(track["era"], []).append(track)

    return library


def list_tracks(db_path):
    """Flat list of every track (unlike load_library's genre/era grouping),
    for the Library panel's table -- sorted by artist as a reasonable base
    ordering (the client re-sorts by whichever column the user clicked)."""
    _ensure_db(db_path)
    conn = _connect(db_path)
    try:
        rows = conn.execute("SELECT * FROM tracks ORDER BY artist COLLATE NOCASE").fetchall()
    finally:
        conn.close()
    return [_row_to_track(row) for row in rows]


def get_track(db_path, track_id):
    _ensure_db(db_path)
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT * FROM tracks WHERE id = ?", (track_id,)).fetchone()
    finally:
        conn.close()
    return _row_to_track(row) if row else None


def add_track(db_path, artist, song, genre, era, url):
    """Insert a new track, returning its new id. Raises ValueError if
    genre/era/url is blank -- same validation load_library's CSV parsing
    always applied per row."""
    _ensure_db(db_path)
    genre = (genre or "").strip()
    era = (era or "").strip()
    url = (url or "").strip()
    if not (genre and era and url):
        raise ValueError("genre, era, and url are required")

    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO tracks (artist, song, genre, era, url) VALUES (?, ?, ?, ?, ?)",
            ((artist or "").strip(), (song or "").strip(), genre, era, url),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_track(db_path, track_id, artist, song, genre, era, url):
    """Full-row replace. Returns False if track_id doesn't exist. If url
    changed from the stored value, clears cache_error/cache_error_at -- a
    failure recorded against the old URL is meaningless once the URL is
    different; if url is unchanged, cache status is left as-is (an
    artist/genre/era-only edit shouldn't reset a real download failure)."""
    _ensure_db(db_path)
    genre = (genre or "").strip()
    era = (era or "").strip()
    url = (url or "").strip()
    if not (genre and era and url):
        raise ValueError("genre, era, and url are required")

    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT url FROM tracks WHERE id = ?", (track_id,)).fetchone()
        if row is None:
            return False
        url_changed = row["url"] != url
        if url_changed:
            conn.execute(
                "UPDATE tracks SET artist = ?, song = ?, genre = ?, era = ?, url = ?, "
                "cache_error = NULL, cache_error_at = NULL, updated_at = datetime('now') WHERE id = ?",
                ((artist or "").strip(), (song or "").strip(), genre, era, url, track_id),
            )
        else:
            conn.execute(
                "UPDATE tracks SET artist = ?, song = ?, genre = ?, era = ?, url = ?, "
                "updated_at = datetime('now') WHERE id = ?",
                ((artist or "").strip(), (song or "").strip(), genre, era, url, track_id),
            )
        conn.commit()
        return True
    finally:
        conn.close()


def delete_track(db_path, track_id):
    """Delete a single row by id (and drop it from any playlist it's a
    member of -- no FK cascade is configured, so this is explicit).
    Returns False if track_id doesn't exist."""
    _ensure_db(db_path)
    conn = _connect(db_path)
    try:
        conn.execute("DELETE FROM playlist_tracks WHERE track_id = ?", (track_id,))
        cur = conn.execute("DELETE FROM tracks WHERE id = ?", (track_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def delete_tracks(db_path, track_ids):
    """Bulk delete by id, one transaction (also dropping each from any
    playlist it's a member of). Returns the number of rows actually
    deleted (ids that didn't exist are silently skipped)."""
    _ensure_db(db_path)
    if not track_ids:
        return 0
    conn = _connect(db_path)
    try:
        placeholders = ",".join("?" for _ in track_ids)
        conn.execute(f"DELETE FROM playlist_tracks WHERE track_id IN ({placeholders})", list(track_ids))
        cur = conn.execute(f"DELETE FROM tracks WHERE id IN ({placeholders})", list(track_ids))
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def set_cache_status(db_path, track_id, error):
    """Record the outcome of the most recent cache-warm attempt for one
    track. error=None means it succeeded (clears any prior failure);
    otherwise error is stored (str()'d) with the current timestamp. Called
    once per track on every warm_cache() run regardless of outcome, so a
    track that stops failing naturally clears itself on the very next
    run -- no separate "clear all failures" step needed the way the old
    cache_failures.json rewrite required."""
    _ensure_db(db_path)
    conn = _connect(db_path)
    try:
        if error is None:
            conn.execute(
                "UPDATE tracks SET cache_error = NULL, cache_error_at = NULL WHERE id = ?",
                (track_id,),
            )
        else:
            conn.execute(
                "UPDATE tracks SET cache_error = ?, cache_error_at = ? WHERE id = ?",
                (str(error), datetime.now(timezone.utc).isoformat(), track_id),
            )
        conn.commit()
    finally:
        conn.close()


def create_playlist(db_path, name):
    """Create a new (initially empty) playlist, returning its new id.
    Raises ValueError if name is blank."""
    _ensure_db(db_path)
    name = (name or "").strip()
    if not name:
        raise ValueError("playlist name is required")
    conn = _connect(db_path)
    try:
        cur = conn.execute("INSERT INTO playlists (name) VALUES (?)", (name,))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_playlists(db_path):
    """Every playlist with its member track_count, sorted by name -- for
    the Playlists settings section and the new-session picker."""
    _ensure_db(db_path)
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT p.id, p.name, p.created_at, p.updated_at, COUNT(pt.id) AS track_count "
            "FROM playlists p LEFT JOIN playlist_tracks pt ON pt.playlist_id = p.id "
            "GROUP BY p.id ORDER BY p.name COLLATE NOCASE"
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def get_playlist(db_path, playlist_id):
    _ensure_db(db_path)
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT id, name, created_at, updated_at FROM playlists WHERE id = ?", (playlist_id,)
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def rename_playlist(db_path, playlist_id, name):
    """Returns False if playlist_id doesn't exist. Raises ValueError if
    name is blank."""
    _ensure_db(db_path)
    name = (name or "").strip()
    if not name:
        raise ValueError("playlist name is required")
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "UPDATE playlists SET name = ?, updated_at = datetime('now') WHERE id = ?",
            (name, playlist_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def delete_playlist(db_path, playlist_id):
    """Deletes the playlist and its playlist_tracks rows in one
    transaction. Returns False if playlist_id doesn't exist. A session
    already running from this playlist is unaffected -- it holds its own
    filtered library dict in memory (see library_for_playlist), not a
    live reference to this row."""
    _ensure_db(db_path)
    conn = _connect(db_path)
    try:
        conn.execute("DELETE FROM playlist_tracks WHERE playlist_id = ?", (playlist_id,))
        cur = conn.execute("DELETE FROM playlists WHERE id = ?", (playlist_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def set_playlist_tracks(db_path, playlist_id, track_ids):
    """Replaces a playlist's full membership in one call -- matches how
    the checkbox-based builder UI submits the whole selected set at once
    rather than incremental add/remove calls. Silently ignores
    track_ids that don't exist in tracks (same tolerance delete_tracks
    has). Raises ValueError if playlist_id doesn't exist."""
    _ensure_db(db_path)
    conn = _connect(db_path)
    try:
        if conn.execute("SELECT 1 FROM playlists WHERE id = ?", (playlist_id,)).fetchone() is None:
            raise ValueError(f"no playlist with id {playlist_id}")
        conn.execute("DELETE FROM playlist_tracks WHERE playlist_id = ?", (playlist_id,))
        if track_ids:
            conn.executemany(
                "INSERT OR IGNORE INTO playlist_tracks (playlist_id, track_id) "
                "SELECT ?, id FROM tracks WHERE id = ?",
                [(playlist_id, track_id) for track_id in track_ids],
            )
        conn.execute("UPDATE playlists SET updated_at = datetime('now') WHERE id = ?", (playlist_id,))
        conn.commit()
    finally:
        conn.close()


def get_playlist_tracks(db_path, playlist_id):
    """Flat list of the playlist's member track dicts, in playlist_tracks
    insertion order, for the builder's edit view. Raises ValueError if
    playlist_id doesn't exist."""
    _ensure_db(db_path)
    conn = _connect(db_path)
    try:
        if conn.execute("SELECT 1 FROM playlists WHERE id = ?", (playlist_id,)).fetchone() is None:
            raise ValueError(f"no playlist with id {playlist_id}")
        rows = conn.execute(
            "SELECT t.* FROM tracks t JOIN playlist_tracks pt ON pt.track_id = t.id "
            "WHERE pt.playlist_id = ? ORDER BY pt.id",
            (playlist_id,),
        ).fetchall()
    finally:
        conn.close()
    return [_row_to_track(row) for row in rows]


def library_for_playlist(db_path, playlist_id):
    """Same {genre: {era: [tracks]}} shape as load_library(), scoped to
    one playlist's member tracks -- the JOIN naturally excludes any track
    that was deleted from the library since the playlist was built.
    Returns {} if the playlist has zero surviving member tracks or
    doesn't exist -- callers are responsible for rejecting an empty
    result with a clear error rather than silently starting a session
    with nothing to play."""
    _ensure_db(db_path)
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT t.* FROM tracks t JOIN playlist_tracks pt ON pt.track_id = t.id "
            "WHERE pt.playlist_id = ?",
            (playlist_id,),
        ).fetchall()
    finally:
        conn.close()

    result = {}
    for row in rows:
        track = _row_to_track(row)
        result.setdefault(track["genre"], {}).setdefault(track["era"], []).append(track)
    return result


def _read_csv_rows(csv_path):
    """Shared by _import_csv_rows()/_ensure_db()'s migration path: parses a
    library.csv-shaped file, skipping (with a printed warning) any row
    missing genre/era/url, same tolerance load_library's CSV-parsing days
    always had. Raises ValueError if a required *column* is missing."""
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = set(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS - fieldnames
        if missing:
            raise ValueError(
                f"{csv_path} is missing required column(s): {', '.join(sorted(missing))}"
            )

        rows = []
        for row_num, row in enumerate(reader, start=2):  # row 1 is the header
            genre = (row["genre"] or "").strip()
            era = (row["era"] or "").strip()
            url = (row["url"] or "").strip()
            artist = (row["artist"] or "").strip()
            song = (row["song"] or "").strip()

            if not (genre and era and url):
                print(f"Skipping row {row_num}: missing genre/era/url -> {row}")
                continue

            rows.append({"artist": artist, "song": song, "genre": genre, "era": era, "url": url})

    return rows


def _import_csv_rows(db_path, csv_path, mode):
    rows = _read_csv_rows(csv_path)

    conn = _connect(db_path)
    try:
        if mode == "replace":
            conn.execute("DELETE FROM tracks")
        conn.executemany(
            "INSERT INTO tracks (artist, song, genre, era, url) VALUES (:artist, :song, :genre, :era, :url)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()

    return {"imported": len(rows)}


def import_csv(db_path, csv_path, mode):
    """Bulk-load csv_path into the library. mode="replace" wipes the
    existing library first (today's whole-file upload semantics); mode=
    "append" adds rows without touching what's already there (for mass-
    adding songs without losing the current library). Returns
    {"imported": n}. Raises ValueError on a malformed CSV (missing
    column) -- same as load_library always did."""
    _ensure_db(db_path)
    if mode not in ("replace", "append"):
        raise ValueError(f"mode must be 'replace' or 'append', got {mode!r}")
    return _import_csv_rows(db_path, csv_path, mode)


def export_csv_rows(db_path):
    """Rows in artist,song,genre,era,url order (matching CSV_COLUMNS) for
    the /library.csv download route to feed straight into csv.DictWriter."""
    _ensure_db(db_path)
    conn = _connect(db_path)
    try:
        rows = conn.execute("SELECT artist, song, genre, era, url FROM tracks ORDER BY artist COLLATE NOCASE").fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def all_tracks(library):
    """Flatten the whole library into a single list of track dicts."""
    tracks = []
    for eras in library.values():
        for track_list in eras.values():
            tracks.extend(track_list)
    return tracks


def genre_options(library):
    """Real genres plus the ANY_GENRE wildcard, for the genre picker."""
    return list(library.keys()) + [ANY_GENRE]


def _era_sort_key(era):
    """
    Sort eras chronologically by the year embedded in the label (e.g. "80s"
    or "1980s" both sort as 80/1980), rather than alphabetically -- a plain
    string sort would put "1970s" right before "1980s" but "2000s" before
    "2010s" is fine while "90s" would sort after "2000s". Eras with no digits
    fall back to alphabetical, after all numbered eras.
    """
    import re
    match = re.search(r"\d+", era)
    if match:
        return (0, int(match.group()))
    return (1, era)


def era_options(library, genre):
    """
    Real eras plus the ANY_ERA wildcard, for the era picker, sorted
    chronologically. If genre is ANY_GENRE, that's every era across the
    whole library (deduped) rather than just one genre's eras.
    """
    if genre == ANY_GENRE:
        eras = set()
        for eras_dict in library.values():
            eras.update(eras_dict.keys())
    else:
        eras = set(library.get(genre, {}).keys())
    return sorted(eras, key=_era_sort_key) + [ANY_ERA]


def tracks_for(library, genre, era):
    """
    Tracks matching a genre/era pick, honoring ANY_GENRE/ANY_ERA wildcards
    in either or both positions.
    """
    if genre == ANY_GENRE and era == ANY_ERA:
        return all_tracks(library)
    if genre == ANY_GENRE:
        tracks = []
        for eras_dict in library.values():
            tracks.extend(eras_dict.get(era, []))
        return tracks
    if era == ANY_ERA:
        tracks = []
        for era_tracks in library.get(genre, {}).values():
            tracks.extend(era_tracks)
        return tracks
    return library.get(genre, {}).get(era, [])


if __name__ == "__main__":
    import config
    lib = load_library(config.LIBRARY_DB)
    for genre, eras in lib.items():
        for era, tracks in eras.items():
            print(f"{genre} / {era}: {len(tracks)} track(s)")
            for t in tracks:
                print(f"    {t['artist']} - {t['song']}")
