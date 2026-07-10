"""
Central configuration for the jukebox. Edit these paths for your setup.
"""
import json
import os

# --- Storage paths -----------------------------------------------------
# Point this at your external USB drive's mount point.
# e.g. if the drive auto-mounts at /media/pi/JUKEBOX, use that path.
#
# CACHE_ROOT (and the paths derived from it below) can also be changed at
# runtime via set_cache_root() -- the web remote's settings panel does this.
# A change persists to SETTINGS_FILE so it survives a restart, taking
# priority over JUKEBOX_CACHE_ROOT/the hardcoded default from then on.
# Everything else in the app reads these as `config.VIDEO_DIR` etc. (fresh
# attribute lookups, never a cached local copy), so a runtime change takes
# effect immediately everywhere without a restart.
SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "config", "settings.json")
_DEFAULT_CACHE_ROOT = os.environ.get("JUKEBOX_CACHE_ROOT", "/mnt/usbdrive/jukebox_cache")


def _load_settings():
    if not os.path.exists(SETTINGS_FILE):
        return {}
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_settings(settings):
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    tmp_path = SETTINGS_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(settings, f)
    os.replace(tmp_path, SETTINGS_FILE)


CACHE_ROOT = _load_settings().get("cache_root") or _DEFAULT_CACHE_ROOT


def _recompute_cache_paths():
    global VIDEO_DIR, INDEX_FILE, ARCHIVE_FILE, WARM_CACHE_LOG, PLAYBACK_LOG
    VIDEO_DIR = os.path.join(CACHE_ROOT, "videos")
    INDEX_FILE = os.path.join(CACHE_ROOT, "index.json")       # url -> local path map
    ARCHIVE_FILE = os.path.join(CACHE_ROOT, "yt-dlp-archive.txt")  # yt-dlp's own "already downloaded" ledger
    WARM_CACHE_LOG = os.path.join(CACHE_ROOT, "warm_cache_failures.log")  # append-only log of failed downloads
    PLAYBACK_LOG = os.path.join(CACHE_ROOT, "playback.log")  # append-only log of track plays/skips/errors


_recompute_cache_paths()


def set_cache_root(path):
    """
    Change CACHE_ROOT (and everything derived from it) at runtime and
    persist the choice to SETTINGS_FILE. Raises OSError if `path` can't be
    created/written to -- callers should leave CACHE_ROOT unchanged in that
    case, which this does by validating before assigning.
    """
    global CACHE_ROOT
    path = os.path.abspath(os.path.expanduser(path))
    os.makedirs(os.path.join(path, "videos"), exist_ok=True)  # validates writability

    CACHE_ROOT = path
    _recompute_cache_paths()

    settings = _load_settings()
    settings["cache_root"] = CACHE_ROOT
    _save_settings(settings)


LIBRARY_FILE = os.path.join(os.path.dirname(__file__), "config", "library.csv")

# --- yt-dlp format selection --------------------------------------------
# Force H.264 video (avc1) so the Pi 4's V4L2 hardware decoder can handle it.
# Falls back gracefully if a video genuinely has no H.264 variant available.
FORMAT_SELECTOR = (
    "bestvideo[vcodec^=avc1][height<=1080]+bestaudio[ext=m4a]/"
    "best[vcodec^=avc1][height<=1080]/"
    "best[height<=1080]"
)

# --- Playback ------------------------------------------------------------
MPV_HWDEC = "v4l2m2m"   # hardware decode mode for Pi 4 (V4L2 M2M)
# ALSA `hw:` fails on the Pi 4's vc4-hdmi devices ("Can't find appropriate
# sample format" -- they don't support mpv's format/rate without conversion).
# `plughw:` routes through ALSA's plug layer, which converts as needed.
# CARD=vc4hdmi0 is the HDMI port nearest the USB-C power connector; use
# vc4hdmi1 (port nearest the audio jack) if audio is plugged into that one.
MPV_AUDIO_DEVICE = "alsa/plughw:CARD=vc4hdmi0,DEV=0"
MPV_EXTRA_ARGS = [
    "--fs",
    "--really-quiet",
    "--no-terminal",
    "--ao=alsa",
    f"--audio-device={MPV_AUDIO_DEVICE}",
]

# --- Library management web page (library_server.py) ---------------------
# Port 80 is privileged on Linux -- see library_server.py's module
# docstring for the setcap incantation needed to bind it without root.
LIBRARY_SERVER_HOST = "0.0.0.0"
LIBRARY_SERVER_PORT = 80


def ensure_dirs():
    os.makedirs(VIDEO_DIR, exist_ok=True)
