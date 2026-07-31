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

# --- Icon: isolate just the left dial out of the full radio-face
# artwork (masked to a circle -- the source is a flat opaque panel, so a
# plain rectangular crop drags in bezel/panel texture around the knob)
# and composite it, large and centered, onto a procedurally generated
# wood-grain background -- this is now the app's actual Dock icon (a
# regular app, not a menu-bar-only one, see app.py), so it matters more
# than ever to get right. See generate_icon_source.py for the crop/mask
# coordinates (derived by pixel-sampling the knob's true center/radius,
# not eyeballed) and the wood-texture recipe.
SRC=icon_source.png
python3 generate_icon_source.py

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
# icon_source.png is a full 1024x1024 composite (see
# generate_icon_source.py), so this is a native-resolution copy for the
# largest iconset slot, not an upscale -- the only softness left is
# whatever the ~5x enlargement of the dial itself (source knob artwork
# is only ~156px across) already bakes in, unavoidable given the source
# artwork's resolution.
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
