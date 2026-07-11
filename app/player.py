"""
Thin wrapper around mpv for fullscreen playback with hardware decode.
Kept deliberately simple: one subprocess per video, killable for "skip".
"""
import subprocess

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

    def is_playing(self):
        return self._proc is not None and self._proc.poll() is None
