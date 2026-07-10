#!/usr/bin/env python3
"""
Music video jukebox - entry point.

Run this directly to test the whole flow with a keyboard standing in for
the rotary encoder + buttons. Once the hardware's wired up, only
input_device.py needs a GPIO-based sibling to KeyboardInput.

Also starts library_server.py's web page (library.csv upload, cache-warm
trigger) in a background thread -- see that file's module docstring for
the setcap step needed to bind its default port (80) without root.
"""
import shutil
import sys
import threading

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


def _start_library_server():
    import library_server
    try:
        library_server.run_server()
    except OSError as e:
        print(f"[library_server] Could not start web management page: {e}")


def main():
    problems = check_dependencies()
    if problems:
        print("Missing dependencies:")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)

    config.ensure_dirs()

    threading.Thread(target=_start_library_server, daemon=True).start()
    print(
        f"Library management page starting on "
        f"http://{config.LIBRARY_SERVER_HOST}:{config.LIBRARY_SERVER_PORT}/ "
        "(LAN only, no auth)"
    )

    from menu import MenuController
    print(f"Video cache: {config.VIDEO_DIR}")
    print("Starting jukebox. Ctrl+C to force-quit at any time.\n")
    MenuController().run()
    print("\nGoodnight.")


if __name__ == "__main__":
    main()
