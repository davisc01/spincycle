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
import os
import random
import threading
import time
from datetime import datetime

import config
import library
import video_cache
from player import make_player

# If a full shuffled pass through the current genre/era's tracks fails to
# play even one of them (e.g. every video needs re-caching and the network
# is down), retrying immediately just hammers yt-dlp/network in a tight
# loop and flickers the status line. Back off between passes instead.
_ALL_TRACKS_FAILED_BACKOFF_SECONDS = 30


def _log_playback(line):
    # A bad CACHE_ROOT must never take down the play loop -- just skip the
    # log line and keep playing; config.cache_root_problem() surfaces the
    # underlying issue to the Settings panel instead.
    if config.cache_root_problem():
        return
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(config.PLAYBACK_LOG, "a", encoding="utf-8") as f:
        f.write(f"{timestamp}  {line}\n")


class SpinCycleController:
    def __init__(self):
        self.library = library.load_library(config.LIBRARY_DB)
        self.player = make_player()

        self._lock = threading.Lock()
        self._genre = None
        self._era = None
        self._playing = False
        self._current_track = None
        self._current_video_path = None
        self._queued_track = None
        self._playlist = None
        self._playlist_pos = 0
        self._status_message = "Select a genre and era to start playing."

        self._generation = 0
        self._play_thread = None
        self._closed = False

    # -- library management -------------------------------------------

    def reload_library(self):
        with self._lock:
            self.library = library.load_library(config.LIBRARY_DB)
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
        if self._closed:
            # A set_genre()/set_era() call that raced in right as
            # SessionManager.close() was tearing this controller down --
            # refuse to spin up a play thread that would then be unreachable
            # (SessionManager no longer holds a reference to us to stop it).
            return
        if self._genre is None or self._era is None:
            self._status_message = "Select a genre and era to start playing."
            return

        tracks = library.tracks_for(self.library, self._genre, self._era)
        if not tracks:
            self._status_message = "no tracks in this genre/era"
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

    def queue_next(self, url):
        """Make the track matching `url` (in the current genre/era) play
        immediately after the one in flight, cutting ahead of the shuffle
        order -- see _play_loop. Raises ValueError if there's no active
        genre/era or the url isn't among its tracks."""
        with self._lock:
            if self._genre is None or self._era is None:
                raise ValueError("no genre/era selected")
            tracks = library.tracks_for(self.library, self._genre, self._era)
            track = next((t for t in tracks if t["url"] == url), None)
            if track is None:
                raise ValueError("track not found in the current genre/era")
            self._queued_track = track

    def clear_queue(self):
        with self._lock:
            self._queued_track = None

    def stop(self):
        with self._lock:
            self._stop_playback_locked()
            self._status_message = "Stopped. Select a genre and era to start playing."

    def close(self):
        """Permanently stop this controller -- used by SessionManager.close()
        instead of stop() so that a genre/era-change call already in flight
        when a session is closed can't resurrect it (see
        _maybe_start_playback_locked)."""
        with self._lock:
            self._closed = True
            self._stop_playback_locked()
            self._status_message = "Session closed."

    def _stop_playback_locked(self):
        self._generation += 1  # invalidate any in-flight _play_loop
        thread = self._play_thread
        self._play_thread = None
        self._playing = False
        self._current_track = None
        self._current_video_path = None
        self._queued_track = None
        self._playlist = None
        self._playlist_pos = 0
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

    def _next_track_locked(self):
        """What will actually play after the current track: a queued
        track if one's set, else a peek at the next not-yet-consumed item
        in the current shuffle pass -- for the "Up next" line, which shows
        the queued pick or, absent one, a preview of the next random song.
        None only in the brief window between passes, right as a fresh
        shuffle is being built (self-corrects on the next poll)."""
        if self._queued_track is not None:
            return self._queued_track
        if self._playlist is not None and self._playlist_pos < len(self._playlist):
            return self._playlist[self._playlist_pos]
        return None

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
                "queued_track": self._queued_track,
                "up_next": self._next_track_locked(),
                "video_url": f"/video/{os.path.basename(self._current_video_path)}" if self._current_video_path else None,
                "playback_mode": config.PLAYBACK_MODE,
                "status_message": self._status_message,
                "cache_root_problem": config.cache_root_problem(),
            }

    def track_list(self):
        """Every track in the current genre/era, sorted by artist then
        song, for the DJ panel -- alongside what's currently playing/queued
        so it can highlight both without a second request."""
        with self._lock:
            if self._genre is None or self._era is None:
                tracks = []
            else:
                tracks = library.tracks_for(self.library, self._genre, self._era)
            return {
                "genre": self._genre,
                "era": self._era,
                "current_track": self._current_track,
                "queued_track": self._queued_track,
                "tracks": sorted(tracks, key=lambda t: (t["artist"].lower(), t["song"].lower())),
            }

    # -- playback loop -------------------------------------------------

    def _is_current_locked(self, generation):
        return generation == self._generation

    def _wait_or_superseded(self, generation, seconds):
        """Sleep up to `seconds`, checking every second whether this play
        loop has since been superseded (stop/skip/genre-or-era change) so a
        backoff wait doesn't delay those actions. Returns True if the loop
        should stop."""
        for _ in range(seconds):
            time.sleep(1)
            with self._lock:
                if not self._is_current_locked(generation):
                    return True
        return False

    def _play_loop(self, generation, tracks, genre, era):
        while True:
            with self._lock:
                if not self._is_current_locked(generation):
                    return
            playlist = tracks[:]
            random.shuffle(playlist)
            pos = 0
            with self._lock:
                self._playlist = playlist
                self._playlist_pos = pos

            played_any = False
            while True:
                with self._lock:
                    if not self._is_current_locked(generation):
                        return
                    queued = self._queued_track
                    if queued is not None:
                        self._queued_track = None
                if queued is not None:
                    # A track queued from the DJ panel cuts ahead of the
                    # shuffle order without consuming it -- playlist/pos
                    # are untouched, so both the remaining shuffle order
                    # and the "up next" preview pick up where they left
                    # off once this one plays.
                    track = queued
                else:
                    if pos >= len(playlist):
                        break
                    track = playlist[pos]
                    pos += 1
                    with self._lock:
                        self._playlist_pos = pos
                label = f"{track['artist']} - {track['song']}" if track["artist"] else track["url"]

                with self._lock:
                    self._status_message = f"loading: {label}"
                try:
                    local_path = video_cache.ensure_cached(track)
                except Exception as e:
                    _log_playback(f"CACHE MISS  {genre} / {era}  {label}  ERROR: {e}")
                    with self._lock:
                        if not self._is_current_locked(generation):
                            return
                        self._status_message = f"cache miss, skipping: {label}"
                    continue

                played_any = True
                # Use the track's own genre/era (not the loop-level genre/era
                # params, which can be the ANY_GENRE/ANY_ERA wildcard) so the
                # overlay shows what the track actually is, e.g. "Rock" for a
                # rock song even when the viewer picked "Anything".
                overlay_text = "\n".join(
                    line for line in (
                        track["artist"], track["song"], f"{track['genre']} / {track['era']}"
                    ) if line
                )
                with self._lock:
                    if not self._is_current_locked(generation):
                        return
                    self._current_track = {
                        "artist": track["artist"],
                        "song": track["song"],
                        "genre": track["genre"],
                        "era": track["era"],
                        "url": track["url"],
                        "label": label,
                    }
                    self._current_video_path = local_path
                    self._status_message = f"Now playing: {label}"
                _log_playback(f"PLAY  {genre} / {era}  {label}")

                self.player.play(local_path, overlay_text=overlay_text)

                with self._lock:
                    if not self._is_current_locked(generation):
                        return

            if not played_any:
                # A full pass just failed, so self._playlist is fully
                # consumed (pos == len) -- "up next" would go blank for the
                # whole backoff otherwise. Pre-shuffle a preview of the
                # retry's pass now so there's still a best-guess answer;
                # the retry reshuffles again for real once it actually
                # starts (see the top of the outer loop), so this is just a
                # placeholder in the meantime.
                preview = tracks[:]
                random.shuffle(preview)
                with self._lock:
                    if not self._is_current_locked(generation):
                        return
                    self._status_message = (
                        f"No videos in {genre} / {era} could be loaded "
                        f"(see Settings > Cache failures) -- retrying in "
                        f"{_ALL_TRACKS_FAILED_BACKOFF_SECONDS}s"
                    )
                    self._playlist = preview
                    self._playlist_pos = 0
                if self._wait_or_superseded(generation, _ALL_TRACKS_FAILED_BACKOFF_SECONDS):
                    return
