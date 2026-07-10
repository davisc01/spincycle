"""
Loads config/library.csv into a genre -> era -> [tracks] structure, where
each "track" is a dict with artist/song/url -- so the UI can show
"Artist - Song" instead of a raw link.

Expected columns (header row required): artist,song,genre,era,url
Extra columns are ignored; column order doesn't matter as long as the
header names match.
"""
import csv

REQUIRED_COLUMNS = {"artist", "song", "genre", "era", "url"}


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


def all_tracks(library):
    """Flatten the whole library into a single list of track dicts."""
    tracks = []
    for eras in library.values():
        for track_list in eras.values():
            tracks.extend(track_list)
    return tracks


if __name__ == "__main__":
    import config
    lib = load_library(config.LIBRARY_FILE)
    for genre, eras in lib.items():
        for era, tracks in eras.items():
            print(f"{genre} / {era}: {len(tracks)} track(s)")
            for t in tracks:
                print(f"    {t['artist']} - {t['song']}")
