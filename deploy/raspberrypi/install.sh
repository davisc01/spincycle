#!/usr/bin/env bash
# Installs Spin Cycle on a Raspberry Pi 4 as a Podman container: Podman
# itself, 720p HDMI boot config, an image build, and a systemd service
# (generated via `podman generate systemd`) enabled to auto-start on boot.
# Safe to re-run -- rebuilds the image and recreates the service each time,
# which doubles as the upgrade path after a `git pull`.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/../../app" && pwd)"
DATA_DIR="$SCRIPT_DIR/data"
CACHE_ROOT=""
ASSUME_YES=0

usage() {
  cat <<'EOF'
Usage: install.sh [--cache-root=PATH] [--yes]

  --cache-root=PATH   Video cache location (e.g. an external USB SSD mount,
                       /media/pi/SPINCYCLE/spincycle_cache). Skips the
                       interactive prompt. Leave unset to be prompted, or
                       to skip entirely -- the container falls back to a
                       local dir under deploy/raspberrypi/data/cache, which
                       lives on the SD card and isn't meant for real use.
  --yes                Skip confirmation prompts (for scripted re-runs).
EOF
}

for arg in "$@"; do
  case "$arg" in
    --cache-root=*) CACHE_ROOT="${arg#--cache-root=}" ;;
    --yes) ASSUME_YES=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $arg" >&2; usage; exit 1 ;;
  esac
done

if [ "$EUID" -eq 0 ]; then
  echo "Don't run install.sh as root/with sudo -- it calls sudo itself for" >&2
  echo "the steps that need it. Run it as yourself instead: ./install.sh" >&2
  exit 1
fi

confirm() {
  if [ "$ASSUME_YES" -eq 1 ]; then
    return 0
  fi
  local reply
  read -r -p "$1 [y/N] " reply
  case "$reply" in
    [Yy]*) return 0 ;;
    *) return 1 ;;
  esac
}

echo "=================================================================="
echo " Spin Cycle -- Raspberry Pi installer (container-based)"
echo "=================================================================="
echo "This will:"
echo "  - install Podman"
echo "  - force 720p HDMI output by editing config.txt and cmdline.txt in"
echo "    /boot/firmware (or /boot on older Raspberry Pi OS)"
echo "  - build the spincycle container image from $APP_DIR"
echo "  - install and enable a systemd service that runs spincycle as a"
echo "    privileged container, auto-starting it on every boot"
echo
if ! confirm "Continue?"; then
  echo "Aborted."
  exit 1
fi

echo
echo "--- Installing Podman ---"
sudo apt-get update
sudo apt-get install -y podman

echo
echo "--- Configuring 720p HDMI output ---"
if [ -d /boot/firmware ]; then
  BOOT_DIR=/boot/firmware
else
  BOOT_DIR=/boot
fi
CONFIG_TXT="$BOOT_DIR/config.txt"
CMDLINE_TXT="$BOOT_DIR/cmdline.txt"

add_config_line() {
  local line="$1"
  if sudo grep -qxF "$line" "$CONFIG_TXT"; then
    echo "  already set: $line"
  else
    echo "$line" | sudo tee -a "$CONFIG_TXT" > /dev/null
    echo "  added: $line"
  fi
}

if [ -f "$CONFIG_TXT" ]; then
  add_config_line "hdmi_force_hotplug=1"
  add_config_line "hdmi_group=1"
  add_config_line "hdmi_mode=4"
else
  echo "  warning: $CONFIG_TXT not found, skipping hdmi_* boot config" >&2
fi

echo
echo "--- Detecting HDMI connector ---"
CONNECTOR="HDMI-A-1"
CONNECTED_CONNECTORS=()
if compgen -G "/sys/class/drm/card*-HDMI-*" > /dev/null 2>&1; then
  for f in /sys/class/drm/card*-HDMI-*; do
    name="$(basename "$f" | sed -E 's/^card[0-9]+-//')"
    status="$(cat "$f/status" 2>/dev/null || echo unknown)"
    echo "  $name: $status"
    if [ "$status" = "connected" ]; then
      CONNECTED_CONNECTORS+=("$name")
    fi
  done
else
  echo "  (no /sys/class/drm/card*-HDMI-* entries found -- skipping detection, defaulting to $CONNECTOR)"
fi

if [ "${#CONNECTED_CONNECTORS[@]}" -eq 1 ] && [ "${CONNECTED_CONNECTORS[0]}" != "$CONNECTOR" ]; then
  CONNECTOR="${CONNECTED_CONNECTORS[0]}"
  echo
  echo "  NOTE: the connected HDMI port is $CONNECTOR, not the default HDMI-A-1."
  echo "  cmdline.txt will be set to use $CONNECTOR, but you must also hand-edit"
  echo "  DRM_CONNECTOR in $APP_DIR/config.py to match (currently hardcoded to"
  echo "  HDMI-A-1) -- otherwise mpv will still try to use the wrong port."
fi

if [ -f "$CMDLINE_TXT" ]; then
  if sudo grep -q 'video=' "$CMDLINE_TXT"; then
    echo "  cmdline.txt already has a video= argument, leaving it as-is:"
    sudo grep -o 'video=[^ ]*' "$CMDLINE_TXT"
  else
    VIDEO_ARG="video=${CONNECTOR}:1280x720@60D"
    sudo sed -i "s/\$/ ${VIDEO_ARG}/" "$CMDLINE_TXT"
    echo "  added to cmdline.txt: $VIDEO_ARG"
  fi
else
  echo "  warning: $CMDLINE_TXT not found, skipping video= kernel argument" >&2
fi

echo
echo "--- Video cache location ---"
if [ -z "$CACHE_ROOT" ] && [ "$ASSUME_YES" -eq 0 ]; then
  echo "Point this at your external USB SSD's mount point, e.g."
  echo "/media/pi/SPINCYCLE/spincycle_cache. This is fixed for the life of"
  echo "this install -- the app refuses to change it at runtime once set, so"
  echo "the only way to change it later is to re-run install.sh with a"
  echo "different --cache-root."
  if compgen -G "/media/*/*" > /dev/null 2>&1; then
    echo "Detected mounts under /media:"
    for m in /media/*/*; do
      [ -d "$m" ] && echo "  $m"
    done
  fi
  read -r -p "Cache root path (blank to use the SD card instead): " CACHE_ROOT
  if [ -z "$CACHE_ROOT" ]; then
    echo
    echo "WARNING: leaving this blank stores the video cache on the SD card"
    echo "($DATA_DIR/cache) instead of an external drive. SD cards have weak"
    echo "write endurance -- repeatedly downloading/rewriting videos can wear"
    echo "one out. Fine for local testing, not recommended for a real party."
    if ! confirm "Continue with SD-card storage?"; then
      echo "Aborted -- re-run and provide --cache-root, or answer this prompt with a path."
      exit 1
    fi
  fi
fi

if [ -n "$CACHE_ROOT" ]; then
  CACHE_HOST_DIR="$CACHE_ROOT"
else
  CACHE_HOST_DIR="$DATA_DIR/cache"
  echo "NOTE: using SD-card storage for the video cache ($CACHE_HOST_DIR) --"
  echo "not recommended for a real party. Re-run with --cache-root to point"
  echo "at an external drive."
fi
mkdir -p "$CACHE_HOST_DIR"

# The container always sees its cache root as /cache (bind-mounted from
# CACHE_HOST_DIR above) -- config/settings.json must never hold anything
# else. If the web remote's Settings panel was ever used to "fix" the
# cache path to a real host path (an easy mistake -- see config.py's
# set_cache_root() for why that silently breaks things), that value
# persists across redeploys and permanently shadows this mount. Reset it
# on every run so a stale value can't linger.
# sudo tee, not a plain redirect: the container runs privileged/as root, so
# anything it previously wrote into this bind-mounted config/ dir (this
# file included) is root-owned on the host -- your normal user can't
# overwrite it directly.
echo '{"cache_root": "/cache"}' | sudo tee "$APP_DIR/config/settings.json" > /dev/null

echo
echo "--- Building the spincycle image ---"
sudo podman build -t spincycle:latest "$APP_DIR"

echo
echo "--- Installing systemd service ---"
sudo systemctl stop spincycle.service 2>/dev/null || true
sudo podman rm -f spincycle 2>/dev/null || true

# /usr/share/alsa is bind-mounted read-only from the host because Raspberry
# Pi OS's alsa-utils/libasound2 (built by the Raspberry Pi Foundation, "+rpt"
# package suffix) ships card-specific config (e.g. cards/vc4-hdmi.conf) that
# plain Debian's alsa packages -- what the container image is built from --
# don't have. Without it, ALSA's plughw format negotiation against the
# vc4-hdmi device fails ("Sample format not available for playback") even
# though the /dev/snd device nodes themselves are visible fine via
# --privileged. Device nodes being present isn't the same as ALSA's
# userspace config knowing how to talk to this specific card.
# --uts host shares the host's hostname (UTS namespace) into the container.
# --network host alone does NOT do this -- containers get their own private
# UTS namespace by default, so without this the splash screen's hostname
# lookup would show the container's random ID instead of the Pi's real
# hostname.
sudo podman create --name spincycle \
  --privileged \
  --network host \
  --uts host \
  -v "$APP_DIR/config:/app/config" \
  -v "$CACHE_HOST_DIR:/cache" \
  -v /usr/share/alsa:/usr/share/alsa:ro \
  -e SPINCYCLE_CACHE_ROOT=/cache \
  spincycle:latest

sudo bash -c 'cd /tmp && podman generate systemd --new --name spincycle --files \
  --restart-policy=on-failure -t 15'
sudo mv /tmp/container-spincycle.service /etc/systemd/system/spincycle.service
sudo podman rm spincycle

sudo systemctl daemon-reload
sudo systemctl enable --now spincycle.service

echo
echo "=================================================================="
echo " Done."
echo "=================================================================="
echo "spincycle.service is enabled and running now."
echo "Video cache: $CACHE_HOST_DIR"
echo
echo "Still to do:"
echo "  - Add your videos to $APP_DIR/config/library.csv (or via the web"
echo "    remote's Settings panel once it's running)"
echo "  - Optionally pre-warm the cache:"
echo "    sudo podman run --rm -v \"$APP_DIR/config:/app/config\" \\"
echo "      -v \"$CACHE_HOST_DIR:/cache\" -e SPINCYCLE_CACHE_ROOT=/cache \\"
echo "      spincycle:latest python3 video_cache.py"
echo
echo "Useful commands:"
echo "  sudo systemctl status spincycle     # is it up?"
echo "  journalctl -u spincycle -f          # live logs"
echo "  sudo systemctl restart spincycle    # after editing config.py, etc."
echo
echo "A reboot is required for the 720p HDMI change to fully take effect"
echo "(the service is already running, just maybe not yet at 720p)."
if confirm "Reboot now?"; then
  sudo reboot
else
  echo "Remember to reboot later: sudo reboot"
fi
