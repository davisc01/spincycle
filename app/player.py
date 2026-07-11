"""
Thin wrapper around mpv for fullscreen playback with hardware decode.
Kept deliberately simple: one subprocess per video, killable for "skip".

Also defines BrowserPlayer, the web-mode equivalent used when a browser
tab is the player instead of mpv on the physical console (see
config.PLAYBACK_MODE, controller.py, and library_server.py's /video and
/api/sessions/<name>/video-ended routes). make_player() picks between the
two so callers (controller.py) don't need to know which mode they're in.
"""
import subprocess
import threading

import config


class Player:
    def __init__(self):
        self._proc = None

    def play(self, local_path):
        """Start playing a local video file. Blocks until finished or skipped."""
        cmd = [
            "mpv",
            f"--hwdec={config.MPV_HWDEC}",
            *config.MPV_EXTRA_ARGS,
            local_path,
        ]
        self._proc = subprocess.Popen(cmd)
        self._proc.wait()
        self._proc = None

    def skip(self):
        """Kill the currently playing video, if any. play() will then return."""
        if self._proc is not None:
            self._proc.terminate()

    def mark_ended(self):
        """No-op: mpv's own process exit already unblocks play(). Exists so
        callers can treat Player and BrowserPlayer interchangeably."""
        pass

    def is_playing(self):
        return self._proc is not None and self._proc.poll() is None


class BrowserPlayer:
    """Web-mode player: nothing actually plays video here -- a browser tab
    polls the controller's status for the current video_url and plays it
    itself. play() just blocks until that tab reports the video ended
    (mark_ended()) or the user hits skip(), mirroring Player's blocking
    play()/killable-from-another-thread contract."""

    def __init__(self):
        self._current_path = None
        self._done = threading.Event()

    def play(self, local_path):
        self._current_path = local_path
        self._done.clear()
        self._done.wait()
        self._current_path = None

    def skip(self):
        self._done.set()

    def mark_ended(self):
        self._done.set()

    def is_playing(self):
        return self._current_path is not None and not self._done.is_set()


def make_player():
    return BrowserPlayer() if config.PLAYBACK_MODE == "web" else Player()
