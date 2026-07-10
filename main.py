#!/usr/bin/env python3
"""
Music video jukebox - entry point.

Run this directly to test the whole flow with a keyboard standing in for
the rotary encoder + buttons. Once the hardware's wired up, only
input_device.py needs a GPIO-based sibling to KeyboardInput.
"""
import shutil
import sys

import config


def check_dependencies():
    problems = []
    if shutil.which("mpv") is None:
        problems.append("mpv is not installed (sudo apt install mpv)")
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        problems.append("yt-dlp is not installed (pip install yt-dlp)")
    return problems


def main():
    problems = check_dependencies()
    if problems:
        print("Missing dependencies:")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)

    config.ensure_dirs()

    from menu import MenuController
    print(f"Video cache: {config.VIDEO_DIR}")
    print("Starting jukebox. Ctrl+C to force-quit at any time.\n")
    MenuController().run()
    print("\nGoodnight.")


if __name__ == "__main__":
    main()
