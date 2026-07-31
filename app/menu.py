"""
Menu state machine: Category -> Era -> shuffled playback.
Talks to the input device in terms of NEXT/PREV/SELECT/SKIP/QUIT events only,
so it doesn't care whether those come from a keyboard or a rotary encoder.
"""
import random
import threading

import config
import library
import video_cache
from input_device import Event, KeyboardInput
from player import Player


class MenuController:
    def __init__(self):
        self.library = library.load_library(config.LIBRARY_DB)
        self.input = KeyboardInput()
        self.player = Player()

    def run(self):
        while True:
            genre = self._select_from_list(library.genre_options(self.library), "Genre")
            if genre is None:
                break  # quit the whole app
            era = self._select_from_list(library.era_options(self.library, genre), f"{genre} > Era")
            if era is None:
                continue  # back to genre list
            tracks = library.tracks_for(self.library, genre, era)
            if not tracks:
                print(f"\nNo tracks yet in {genre} / {era} -- add some to config/library.csv!\n")
                continue
            self._play_shuffled(genre, era, tracks)

    def _select_from_list(self, options, title):
        """Rotary-encoder-style browsing: rotate to move a highlight, press to confirm."""
        if not options:
            print(f"{title}: (empty)")
            return None

        index = 0
        while True:
            print(f"\n-- {title} --")
            for i, opt in enumerate(options):
                marker = ">" if i == index else " "
                print(f" {marker} {opt}")
            print("[w/s or Up/Down = move, Enter/Space = select, q = back]")

            event = self.input.wait_for_event()
            if event == Event.NEXT:
                index = (index + 1) % len(options)
            elif event == Event.PREV:
                index = (index - 1) % len(options)
            elif event == Event.SELECT:
                return options[index]
            elif event == Event.QUIT:
                return None

    def _play_shuffled(self, genre, era, tracks):
        print(f"\nPlaying {len(tracks)} track(s) from {genre} / {era} on shuffle -- loops forever.")
        print("Press 'k' to skip a track, 'q' to stop and return to the menu.\n")

        while True:
            playlist = tracks[:]
            random.shuffle(playlist)
            for track in playlist:
                label = f"{track['artist']} - {track['song']}" if track["artist"] else track["url"]
                print(f"Checking cache: {label}")
                try:
                    local_path = video_cache.ensure_cached(track["url"])
                except Exception as e:
                    print(f"  Could not fetch, skipping: {e}")
                    continue

                print(f"Now playing: {label}")
                return_to_menu = self._play_with_skip_listener(local_path)
                if return_to_menu:
                    return

    def _play_with_skip_listener(self, local_path):
        """
        Plays one video on a background thread while polling for SKIP/QUIT.
        Returns True if the user wants to bail out to the menu entirely,
        False if they just want to move on to the next track normally.
        """
        state = {"quit": False}

        thread = threading.Thread(target=self.player.play, args=(local_path,))
        thread.start()

        while thread.is_alive():
            event = self.input.poll_event(timeout=0.1)
            if event == Event.SKIP:
                self.player.skip()
            elif event == Event.QUIT:
                self.player.skip()
                state["quit"] = True

        thread.join()
        return state["quit"]


if __name__ == "__main__":
    MenuController().run()
