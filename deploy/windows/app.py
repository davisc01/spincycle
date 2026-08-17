#!/usr/bin/env python3
"""
Spin Cycle - Windows app wrapper.

A real windowed app around the same app/ codebase the container target
runs in web mode (SPINCYCLE_PLAYBACK_MODE=web -- no mpv/DRM/ALSA,
decoding happens client-side). The window is a pywebview window (backed
by the Windows WebView2/Edge-Chromium runtime) pointed at the local web
remote (http://localhost:8080/ by default), so this is a thin native
shell, not a reimplementation -- all the genre/era/session/DJ logic still
lives in the same web/ JS the browser target uses. Other devices on the
LAN can still reach the same server directly (see
config.LIBRARY_SERVER_HOST), same as the container/macOS targets -- the
window is just this PC's own client.

Unlike deploy/macos/app.py's raw WKWebView, WebView2 is a full Chromium
engine -- JS alert()/confirm()/<input type="file"> already work without
any custom delegate code. window.open() (the "Launch Player" button, see
app/web/app.js) is handled by pywebview's default external-link handling
(webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"]), which sends it to
the system default browser rather than a second native window -- simpler
than macOS's popup-window dance, and still gets the player onto its own
tab.

Two ways to run this file:
  - Packaged: build.ps1's PyInstaller build bundles app/ as onedir data
    next to the exe (see spincycle.spec's `datas`) and this becomes the
    app's entry point. Launched by double-clicking Spin Cycle.exe.
  - From source (dev loop, faster than a full PyInstaller build):
    `python3 deploy/windows/app.py` after `pip install -r
    requirements.txt -r ../../app/requirements.txt`. _app_source_dir()
    below falls back to the sibling ../../app directory when not frozen.

Env vars/ports are set here, before importing anything from app/, because
config.py reads them at import time (module-level) -- same pattern
deploy/container and deploy/macos rely on (see config.py's
CACHE_ROOT/CONFIG_DIR/LIBRARY_SERVER_PORT comments).
"""
import os
import sys
import threading
from pathlib import Path

import webview

PORT = 8080
WINDOW_SIZE = (1100, 750)
WINDOW_MIN_SIZE = (760, 520)

APP_SUPPORT_DIR = Path(os.environ["LOCALAPPDATA"]) / "Spin Cycle"
CACHE_DIR = APP_SUPPORT_DIR / "cache"
CONFIG_DIR = APP_SUPPORT_DIR / "config"


def _app_source_dir() -> str:
    """
    Locate the bundled app/ codebase: the `app` folder PyInstaller
    extracts alongside sys._MEIPASS when frozen (see spincycle.spec's
    `datas`), or the sibling ../../app directory when running from a
    source checkout.
    """
    if getattr(sys, "frozen", False):
        return str(Path(sys._MEIPASS) / "app")
    return str(Path(__file__).resolve().parent.parent.parent / "app")


def _seed_config(app_dir: str) -> None:
    """
    Copy the starter config/library.csv into %LOCALAPPDATA% on first
    launch only -- never overwrites an existing one, so a real library.csv
    already there survives an app update (a rebuilt exe's bundled starter
    library.csv is replaced, but Application-data isn't touched by
    rebuilding). This seeded/existing CSV is only ever a one-time
    migration source -- library._ensure_db() imports it into library.db
    (the live store) the first time anything in the app touches the
    library, and never writes to the CSV again.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    dest = CONFIG_DIR / "library.csv"
    if dest.exists():
        return
    src = Path(app_dir) / "config" / "library.csv"
    if src.exists():
        dest.write_bytes(src.read_bytes())


def _local_url() -> str:
    return f"http://localhost:{PORT}/"


def _start_spincycle(app_dir: str) -> bool:
    """
    Set up env vars + start library_server.py in a background thread.
    Mirrors app/main.py's setup (minus the console splash and the
    blocking wait loop, which don't apply here) so this stays the same
    web-mode startup path the container/macOS targets use. Returns False
    if a hard dependency is missing (caller should show an error and
    quit).
    """
    os.environ["SPINCYCLE_PLAYBACK_MODE"] = "web"
    os.environ["SPINCYCLE_CACHE_ROOT"] = str(CACHE_DIR)
    os.environ["SPINCYCLE_CONFIG_DIR"] = str(CONFIG_DIR)
    os.environ["SPINCYCLE_SERVER_PORT"] = str(PORT)
    _seed_config(app_dir)

    sys.path.insert(0, app_dir)
    import config
    import video_cache
    import library_server
    from sessions import SessionManager

    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        return False

    problem = config.cache_root_problem()
    if problem:
        print(f"[spincycle] Warning: cache folder {config.CACHE_ROOT} isn't usable ({problem}).")
    else:
        video_cache.clear_incoming()

    session_manager = SessionManager()
    library_server.start_background_warm_cache()

    def _run():
        try:
            library_server.run_server(session_manager=session_manager)
        except OSError as e:
            print(f"[spincycle] Could not start web remote: {e}")

    threading.Thread(target=_run, daemon=True).start()
    return True


def main():
    app_dir = _app_source_dir()
    if not _start_spincycle(app_dir):
        webview.create_window(
            "Spin Cycle can't start",
            html=(
                "<body style='font-family:sans-serif;padding:2em'>"
                "<h3>Spin Cycle can't start</h3>"
                "<p>yt-dlp isn't installed in this app's bundled environment. "
                "Rebuild via deploy/windows/build.ps1.</p></body>"
            ),
            width=480,
            height=220,
        )
        webview.start()
        return

    width, height = WINDOW_SIZE
    min_width, min_height = WINDOW_MIN_SIZE
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    webview.create_window(
        "Spin Cycle",
        _local_url(),
        width=width,
        height=height,
        min_size=(min_width, min_height),
    )
    webview.start()


if __name__ == "__main__":
    main()
