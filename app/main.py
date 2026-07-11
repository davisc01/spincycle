#!/usr/bin/env python3
"""
Music video jukebox - entry point.

Starts a JukeboxController (genre/era selection, shuffle playback) and
library_server.py's web remote in a background thread -- the browser-based
UI (genre/era selectors, skip/stop, settings) is the primary interface
until the physical rotary-encoder + LCD hardware lands. The old terminal
keyboard mode (menu.py + input_device.py) still works standalone for dev
use (`python3 menu.py`) but is no longer started here, to avoid two
independent Player/mpv instances fighting over the one screen/speaker.

See library_server.py's module docstring for the setcap step needed to
bind its default port (80) without root.
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
    try:
        import rich  # noqa: F401
    except ImportError:
        problems.append("rich is not installed (pip install rich)")
    return problems


def _start_library_server(controller):
    import library_server
    # Fresh deploys (or a library.csv with newly-added URLs) start with a
    # cold cache -- without this, the first genre/era pick after startup
    # has to synchronously download+merge via yt-dlp before anything plays,
    # which can look like playback is broken rather than just slow. This
    # runs in its own background thread (see start_background_warm_cache)
    # so it never delays the web remote or splash screen from coming up,
    # and it's a no-op almost immediately for anything already cached.
    library_server.start_background_warm_cache()
    try:
        library_server.run_server(controller=controller)
    except OSError as e:
        print(f"[library_server] Could not start web remote: {e}")


def main():
    problems = check_dependencies()
    if problems:
        print("Missing dependencies:")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)

    problem = config.cache_root_problem()
    if problem:
        print(f"[jukebox] Warning: cache folder {config.CACHE_ROOT} isn't usable ({problem}).")
        print("[jukebox] Starting anyway -- set a working path from the web remote's Settings panel.")

    from controller import JukeboxController
    import splash
    controller = JukeboxController()

    threading.Thread(target=_start_library_server, args=(controller,), daemon=True).start()
    splash.show_startup(config.LIBRARY_SERVER_PORT, config.VIDEO_DIR)

    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    splash.show_shutdown()


if __name__ == "__main__":
    main()
