"""
py2app build script -- bundles app.py plus the whole app/ directory
(copied in verbatim, not analyzed by py2app's import graph, since it's
imported dynamically via sys.path.insert -- see app._app_source_dir())
into Spin Cycle.app.

Run via build.sh (handles the venv + icon generation too), or directly
from an already-set-up venv:

    python3 setup.py py2app
"""
from setuptools import setup

APP = ["app.py"]
OPTIONS = {
    "argv_emulation": False,
    "resources": ["../../app"],
    "iconfile": "icon.icns",
    "plist": {
        "CFBundleName": "Spin Cycle",
        "CFBundleDisplayName": "Spin Cycle",
        "CFBundleIdentifier": "com.spincycle.menubar",
        "CFBundleShortVersionString": "1.0.0",
        # No LSUIElement: a regular app -- Dock icon, bounces on launch,
        # Cmd-Tab app-switcher entry, standard behavior (see app.py's
        # AppDelegate for the Dock-icon-stays-up-after-window-closes and
        # click-to-reopen behavior that goes with that).
        # Triggers macOS's Local Network permission prompt the first time
        # another device tries to reach the web remote -- without this
        # string (and NSBonjourServices below) the prompt never fires and
        # incoming LAN connections just silently fail instead.
        "NSLocalNetworkUsageDescription": (
            "Spin Cycle serves its web remote to other devices on your "
            "LAN (phones, laptops, TVs) so they can control playback."
        ),
        "NSBonjourServices": ["_http._tcp"],
    },
}

setup(
    app=APP,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
