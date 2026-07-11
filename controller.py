"""
Live playback engine shared by the web UI (library_server.py).

Unlike menu.py's Event-driven state machine (built for "browse a list,
press to confirm"), this tracks genre/era as continuously-live state:
setting either one commits immediately -- there's no separate confirm
step, matching the settle-then-autoplay radio-tuner model described in
CLAUDE.md's "Interaction model" section, just without the settle timer
(an HTTP request is already a deliberate, settled action, unlike a
still-spinning dial). A future GPIO dial input could drive this same
controller instead of menu.py's KeyboardInput/Event model.
"""
import random
import threading
from datetime import datetime

import config
import library
import video_cache
from player import Player


def _log_playback(line):
    # A bad CACHE_ROOT must never take down the play loop -- just skip the
    # log line and keep playing; config.cache_root_problem() surfaces the
    # underlying issue to the Settings panel instead.
    if config.cache_root_problem():
        return
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(config.PLAYBACK_LOG, "a", encoding="utf-8") as f:
        f.write(f"{timestamp}  {line}\n")


class JukeboxController:
    def __init__(self):
        self.library = library.load_library(config.LIBRARY_FILE)
        self.player = Player()

        self._lock = threading.Lock()
        self._genre = None
        self._era = None
        self._playing = False
        self._current_track = None
        self._status_message = "Select a genre and era to start playing."

        self._generation = 0
        self._play_thread = None

    # -- library management -------------------------------------------

    def reload_library(self):
        with self._lock:
            self.library = library.load_library(config.LIBRARY_FILE)
            genres = library.genre_options(self.library)
            if self._genre not in genres:
                self._genre = None
            eras = library.era_options(self.library, self._genre) if self._genre else []
            if self._era not in eras:
                self._era = None

    # -- selection -------------------------------------------------------

    def set_genre(self, genre):
        with self._lock:
            self._genre = genre
            eras = library.era_options(self.library, genre)
            if self._era not in eras:
                self._era = None
            self._maybe_start_playback_locked()

    def set_era(self, era):
        with self._lock:
            self._era = era
            self._maybe_start_playback_locked()

    def _maybe_start_playback_locked(self):
        """Called with self._lock held. (Re)starts playback if both genre
        and era are now set, stopping any playback already in flight."""
        self._stop_playback_locked()
        if self._genre is None or self._era is None:
            self._status_message = "Select a genre and era to start playing."
            return

        tracks = library.tracks_for(self.library, self._genre, self._era)
        if not tracks:
            self._status_message = "No Tracks"
            return

        self._generation += 1
        generation = self._generation
        self._playing = True
        self._status_message = "loading..."
        self._play_thread = threading.Thread(
            target=self._play_loop,
            args=(generation, tracks, self._genre, self._era),
            daemon=True,
        )
        self._play_thread.start()

    # -- transport controls ----------------------------------------------

    def skip(self):
        self.player.skip()

    def stop(self):
        with self._lock:
            self._stop_playback_locked()
            self._status_message = "Stopped. Select a genre and era to start playing."

    def _stop_playback_locked(self):
        self._generation += 1  # invalidate any in-flight _play_loop
        thread = self._play_thread
        self._play_thread = None
        self._playing = False
        self._current_track = None
        if thread is not None and thread.is_alive():
            self.player.skip()
            # Release the lock while joining so the play loop (which takes
            # the lock to update status) doesn't deadlock against us.
            self._lock.release()
            try:
                thread.join()
            finally:
                self._lock.acquire()

    # -- status ------------------------------------------------------------

    def status(self):
        with self._lock:
            genre_options = library.genre_options(self.library)
            era_options = library.era_options(self.library, self._genre) if self._genre else []
            return {
                "genre": self._genre,
                "era": self._era,
                "genre_options": genre_options,
                "era_options": era_options,
                "playing": self._playing,
                "current_track": self._current_track,
                "status_message": self._status_message,
                "cache_root_problem": config.cache_root_problem(),
            }

    # -- playback loop -------------------------------------------------

    def _is_current_locked(self, generation):
        return generation == self._generation

    def _play_loop(self, generation, tracks, genre, era):
        while True:
            with self._lock:
                if not self._is_current_locked(generation):
                    return
            playlist = tracks[:]
            random.shuffle(playlist)

            for track in playlist:
                with self._lock:
                    if not self._is_current_locked(generation):
                        return
                label = f"{track['artist']} - {track['song']}" if track["artist"] else track["url"]

                with self._lock:
                    self._status_message = f"loading: {label}"
                try:
                    local_path = video_cache.ensure_cached(track["url"])
                except Exception as e:
                    _log_playback(f"CACHE MISS  {genre} / {era}  {label}  ERROR: {e}")
                    with self._lock:
                        if not self._is_current_locked(generation):
                            return
                        self._status_message = f"cache miss, skipping: {label}"
                    continue

                with self._lock:
                    if not self._is_current_locked(generation):
                        return
                    self._current_track = label
                    self._status_message = f"Now playing: {label}"
                _log_playback(f"PLAY  {genre} / {era}  {label}")

                self.player.play(local_path)

                with self._lock:
                    if not self._is_current_locked(generation):
                        return
