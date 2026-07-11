"""
Loads config/library.csv into a genre -> era -> [tracks] structure, where
each "track" is a dict with artist/song/url -- so the UI can show
"Artist - Song" instead of a raw link.

Expected columns (header row required): artist,song,genre,era,url
Extra columns are ignored; column order doesn't matter as long as the
header names match.
"""
import csv
import os
import re

REQUIRED_COLUMNS = {"artist", "song", "genre", "era", "url"}

# Wildcard picks, appended to the real genre/era lists -- picking either
# (or both) plays across whatever dimension is left unconstrained.
ANY_GENRE = "Anything"
ANY_ERA = "Anytime"


def load_library(csv_path):
    library = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = set(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS - fieldnames
        if missing:
            raise ValueError(
                f"{csv_path} is missing required column(s): {', '.join(sorted(missing))}"
            )

        for row_num, row in enumerate(reader, start=2):  # row 1 is the header
            genre = (row["genre"] or "").strip()
            era = (row["era"] or "").strip()
            url = (row["url"] or "").strip()
            artist = (row["artist"] or "").strip()
            song = (row["song"] or "").strip()

            if not (genre and era and url):
                print(f"Skipping row {row_num}: missing genre/era/url -> {row}")
                continue

            track = {"artist": artist, "song": song, "url": url}
            library.setdefault(genre, {}).setdefault(era, []).append(track)

    return library


def _rewrite_rows(csv_path, rows, fieldnames):
    tmp_path = csv_path + ".tmp"
    with open(tmp_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp_path, csv_path)


def update_url(csv_path, old_url, new_url):
    """
    Rewrite every library.csv row whose url matches old_url to new_url,
    preserving all other columns/order. There's no stable row ID in the CSV
    (see load_library()), so url -- the cache key that's actually failing --
    is the natural match key. Returns the number of rows changed.
    """
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    changed = 0
    for row in rows:
        if (row.get("url") or "").strip() == old_url:
            row["url"] = new_url
            changed += 1

    if changed:
        _rewrite_rows(csv_path, rows, fieldnames)
    return changed


def remove_by_url(csv_path, url):
    """
    Remove every library.csv row whose url matches. Returns the number of
    rows removed.
    """
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    kept = [row for row in rows if (row.get("url") or "").strip() != url]
    removed = len(rows) - len(kept)

    if removed:
        _rewrite_rows(csv_path, kept, fieldnames)
    return removed


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
    lib = load_library(config.LIBRARY_FILE)
    for genre, eras in lib.items():
        for era, tracks in eras.items():
            print(f"{genre} / {era}: {len(tracks)} track(s)")
            for t in tracks:
                print(f"    {t['artist']} - {t['song']}")
