#!/usr/bin/env bash
# Build Spin Cycle.app: venv -> deps -> icon.icns -> py2app.
#
# Usage: ./build.sh
# Output: dist/Spin Cycle.app
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

# py2app support for brand-new Python versions lags behind CPython
# releases -- prefer 3.10/3.11 (what the Pi/container targets' Dockerfile
# also uses) over whatever `python3` happens to resolve to system-wide.
PYTHON=python3
for candidate in python3.11 python3.10; do
    if command -v "$candidate" >/dev/null 2>&1; then
        PYTHON="$candidate"
        break
    fi
done
echo "Using $($PYTHON --version) ($(command -v "$PYTHON"))"

if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "Warning: ffmpeg not found on PATH. yt-dlp needs it to mux separate" >&2
    echo "video/audio streams -- install it with: brew install ffmpeg" >&2
fi

VENV_DIR=.venv-build
if [ ! -d "$VENV_DIR" ]; then
    "$PYTHON" -m venv "$VENV_DIR"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

pip install --upgrade pip >/dev/null
pip install -r requirements.txt -r ../../app/requirements.txt

# --- Icon: crop one dial out of the full radio-face artwork, then build
# icon.icns from that -- this is now the app's actual Dock icon (a regular
# app, not a menu-bar-only one, see app.py), so it matters more than ever
# to get right. The full spin_cycle_icon_1024.png (two dials either side
# of a "spin cycle" LCD screen, see the main README) is a wide strip that
# goes illegible once shrunk to Finder-list/Dock-small sizes -- a single
# dial reads fine at that size. Crop box below is the left dial plus its
# rounded corner/screw-hole bezel, picked by eyeballing
# app/images/spin_cycle_icon_1024.png's 980x980 canvas (content sits at
# roughly x:40-940 y:350-629) to land just before the LCD screen starts.
SRC_FULL=../../app/images/spin_cycle_icon_1024.png
SRC=icon_source.png
python3 -c "
from PIL import Image
im = Image.open('$SRC_FULL').convert('RGBA')
im.crop((20, 365, 280, 625)).save('$SRC')
"

ICONSET=icon.iconset
rm -rf "$ICONSET" icon.icns
mkdir "$ICONSET"
sips -z 16 16     "$SRC" --out "$ICONSET/icon_16x16.png"      >/dev/null
sips -z 32 32     "$SRC" --out "$ICONSET/icon_16x16@2x.png"   >/dev/null
sips -z 32 32     "$SRC" --out "$ICONSET/icon_32x32.png"      >/dev/null
sips -z 64 64     "$SRC" --out "$ICONSET/icon_32x32@2x.png"   >/dev/null
sips -z 128 128   "$SRC" --out "$ICONSET/icon_128x128.png"    >/dev/null
sips -z 256 256   "$SRC" --out "$ICONSET/icon_128x128@2x.png" >/dev/null
sips -z 256 256   "$SRC" --out "$ICONSET/icon_256x256.png"    >/dev/null
sips -z 512 512   "$SRC" --out "$ICONSET/icon_256x256@2x.png" >/dev/null
sips -z 512 512   "$SRC" --out "$ICONSET/icon_512x512.png"    >/dev/null
# 1024px slot upscaled from a 260px crop (the source artwork's native
# resolution caps out around 980px for the whole two-dial strip, so a
# single dial has no more than ~260px of real detail to begin with) --
# soft at Finder's largest preview size, sharp everywhere the icon is
# actually seen day-to-day (the Dock, Cmd-Tab switcher, Finder list view).
# Fine for now; swap in dedicated high-res dial artwork later if that
# starts to bug you.
sips -z 1024 1024 "$SRC" --out "$ICONSET/icon_512x512@2x.png" >/dev/null
iconutil -c icns "$ICONSET" -o icon.icns
rm -rf "$ICONSET" "$SRC"

rm -rf build dist
python3 setup.py py2app

# The whole app/ dir gets copied verbatim as a resource (see setup.py) --
# strip the bits that are meaningless inside a bundled .app.
BUNDLED_APP="dist/Spin Cycle.app/Contents/Resources/app"
find "$BUNDLED_APP" -name "__pycache__" -exec rm -rf {} +
rm -f "$BUNDLED_APP/Dockerfile" "$BUNDLED_APP/.dockerignore"

# py2app already ad-hoc-signed the bundle as part of the py2app step above
# -- but editing its contents afterward (the strip above) invalidates that
# signature's sealed resource manifest (`spctl -a` on the result reports
# "a sealed resource is missing or invalid"). A same-machine Finder copy
# tolerates that, but Gatekeeper enforces it strictly on anything that
# picks up a quarantine flag -- AirDrop, a zip, a download -- which is
# exactly how you'd hand this to someone else. Re-sign (still ad-hoc, no
# paid account needed) now that the bundle's final contents are settled.
codesign --force --deep --sign - "dist/Spin Cycle.app"

deactivate
echo ""
echo "Built: $(pwd)/dist/Spin Cycle.app"
echo "Launch it from Finder, or: open 'dist/Spin Cycle.app'"
