"""
Thin wrapper around mpv for fullscreen playback with hardware decode.
Kept deliberately simple: one subprocess per video, killable for "skip".

Also defines BrowserPlayer, the web-mode equivalent used when a browser
tab is the player instead of mpv on the physical console (see
config.PLAYBACK_MODE, controller.py, and library_server.py's /video and
/api/sessions/<name>/video-ended routes). make_player() picks between the
two so callers (controller.py) don't need to know which mode they're in.
"""
import json
import os
import socket
import subprocess
import threading
import time

import config

# How long to give mpv to exit gracefully after SIGTERM before escalating
# to SIGKILL -- a stuck DRM/ALSA state could otherwise ignore SIGTERM
# forever, and Player.play()'s blocking wait() would then freeze the whole
# shuffle loop with no way to recover short of restarting the process.
_TERMINATE_GRACE_SECONDS = 5

# mpv needs a moment after Popen() to create its IPC socket file -- retry
# connecting for a bit rather than giving up on the first attempt.
_IPC_CONNECT_TIMEOUT_SECONDS = 2.0
_IPC_CONNECT_RETRY_INTERVAL_SECONDS = 0.1
_OVERLAY_DURATION_MS = 5000


class Player:
    def __init__(self):
        self._proc = None

    def play(self, local_path, overlay_text=None):
        """Start playing a local video file. Blocks until finished or skipped."""
        # Clear a stale socket file left behind by a previous mpv process
        # that didn't exit cleanly -- mpv's own bind can fail otherwise.
        try:
            os.remove(config.MPV_IPC_SOCKET)
        except FileNotFoundError:
            pass
        except OSError as e:
            print(f"[player] Could not clear stale IPC socket: {e}")

        cmd = [
            "mpv",
            f"--hwdec={config.MPV_HWDEC}",
            *config.MPV_EXTRA_ARGS,
            local_path,
        ]
        self._proc = subprocess.Popen(cmd)
        if overlay_text:
            threading.Thread(
                target=self._show_overlay, args=(overlay_text,), daemon=True
            ).start()
        self._proc.wait()
        self._proc = None

    def _show_overlay(self, text):
        """Best-effort: connect to mpv's JSON IPC socket and show `text` as
        an MTV-style OSD message for a few seconds. Never raises -- a
        failure here (e.g. mpv didn't create the socket in time) must not
        affect playback."""
        deadline = time.monotonic() + _IPC_CONNECT_TIMEOUT_SECONDS
        sock = None
        try:
            while sock is None and time.monotonic() < deadline:
                try:
                    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    sock.connect(config.MPV_IPC_SOCKET)
                except OSError:
                    sock = None
                    time.sleep(_IPC_CONNECT_RETRY_INTERVAL_SECONDS)
            if sock is None:
                print("[player] Could not connect to mpv IPC socket for overlay; skipping.")
                return
            payload = json.dumps({"command": ["show-text", text, _OVERLAY_DURATION_MS]}) + "\n"
            sock.sendall(payload.encode("utf-8"))
        except OSError as e:
            print(f"[player] Overlay IPC failed, skipping: {e}")
        finally:
            if sock is not None:
                sock.close()

    def skip(self):
        """Kill the currently playing video, if any. play() will then return."""
        proc = self._proc  # snapshot once -- play() can set self._proc to
        # None concurrently (mpv exiting on its own right as skip() runs),
        # and re-reading self._proc after this check would race that.
        if proc is None:
            return
        proc.terminate()
        threading.Thread(target=self._force_kill_if_still_running, args=(proc,), daemon=True).start()

    def _force_kill_if_still_running(self, proc):
        try:
            proc.wait(timeout=_TERMINATE_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            proc.kill()

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

    def play(self, local_path, overlay_text=None):
        # overlay_text is unused here -- the browser player renders its own
        # overlay from controller.status()'s structured current_track field.
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
