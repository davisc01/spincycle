"""
Central configuration for Spin Cycle. Edit these paths for your setup.
"""
import json
import os

# --- Storage paths -----------------------------------------------------
# Point this at your external USB drive's mount point, e.g. via
# SPINCYCLE_CACHE_ROOT=/media/pi/SPINCYCLE/spincycle_cache, or set it later from
# the web remote's Settings panel (see set_cache_root() below) -- either
# way, don't leave it on the fallback default below for real use. That
# default is just a repo-local folder (already .gitignore'd) chosen so the
# app always boots even before you've mounted a drive or set a real path;
# it lives on the same storage as the code (the SD card, on a Pi), which
# CLAUDE.md's hardware notes explicitly say to avoid for actual video I/O.
#
# CACHE_ROOT (and the paths derived from it below) can also be changed at
# runtime via set_cache_root() -- the web remote's settings panel does this.
# A change persists to SETTINGS_FILE so it survives a restart, taking
# priority over SPINCYCLE_CACHE_ROOT/the hardcoded default from then on.
# Everything else in the app reads these as `config.VIDEO_DIR` etc. (fresh
# attribute lookups, never a cached local copy), so a runtime change takes
# effect immediately everywhere without a restart.
SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "config", "settings.json")
_FALLBACK_CACHE_ROOT = os.path.join(os.path.dirname(__file__), "cache")
_DEFAULT_CACHE_ROOT = os.environ.get("SPINCYCLE_CACHE_ROOT", _FALLBACK_CACHE_ROOT)


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
    global VIDEO_DIR, INDEX_FILE, CACHE_FAILURES_FILE, PLAYBACK_LOG
    VIDEO_DIR = os.path.join(CACHE_ROOT, "videos")
    INDEX_FILE = os.path.join(CACHE_ROOT, "index.json")       # url -> local path map
    CACHE_FAILURES_FILE = os.path.join(CACHE_ROOT, "cache_failures.json")  # rewritten each warm-cache run: only tracks that failed *this* run
    PLAYBACK_LOG = os.path.join(CACHE_ROOT, "playback.log")  # append-only log of track plays/skips/errors


_recompute_cache_paths()


def set_cache_root(path):
    """
    Change CACHE_ROOT (and everything derived from it) at runtime and
    persist the choice to SETTINGS_FILE. Raises OSError if `path` can't be
    created/written to -- callers should leave CACHE_ROOT unchanged in that
    case, which this does by validating before assigning.

    Refuses (RuntimeError) if SPINCYCLE_CACHE_ROOT is set in the environment.
    That means a deploy layer (e.g. deploy/raspberrypi/install.sh) has
    already pinned the real storage location via a bind mount -- typically
    to a fixed in-container path like /cache -- and the actual host
    directory is controlled entirely by that mount, not by any path string
    the app itself sees. Letting this function "succeed" against some other
    path there would just create a fresh, empty directory tree wherever the
    app happens to be running (e.g. the container's own writable layer),
    disconnected from the real drive, and silently swallow every future
    download into a location that looks fine from inside the app but never
    reaches the actual mounted storage -- and gets wiped on every container
    recreation to boot. This bit us for real once already (see CLAUDE.md's
    "Known gaps"), hence a hard guard rather than just a docs warning.
    """
    if os.environ.get("SPINCYCLE_CACHE_ROOT"):
        raise RuntimeError(
            "Cache location is fixed by this deployment (SPINCYCLE_CACHE_ROOT "
            "is set in the environment) -- change the deploy-time configuration "
            "instead of setting it here (e.g. re-run deploy/raspberrypi/install.sh "
            "with a different --cache-root, or update the k8s Deployment's env)."
        )

    global CACHE_ROOT
    path = os.path.abspath(os.path.expanduser(path))
    os.makedirs(os.path.join(path, "videos"), exist_ok=True)  # validates writability

    CACHE_ROOT = path
    _recompute_cache_paths()

    settings = _load_settings()
    settings["cache_root"] = CACHE_ROOT
    _save_settings(settings)


LIBRARY_FILE = os.path.join(os.path.dirname(__file__), "config", "library.csv")

# --- Playback mode ---------------------------------------------------------
# "console" (default): mpv renders to the physical console via DRM/KMS, as
# on the Pi. "web": a browser tab is the player instead -- see player.py's
# BrowserPlayer and sessions.py. Read once from env at startup, unlike
# CACHE_ROOT -- this isn't meant to be flipped at runtime from Settings.
PLAYBACK_MODE = os.environ.get("SPINCYCLE_PLAYBACK_MODE", "console")
if PLAYBACK_MODE not in ("console", "web"):
    raise ValueError(f"SPINCYCLE_PLAYBACK_MODE must be 'console' or 'web', got {PLAYBACK_MODE!r}")

# --- yt-dlp format selection --------------------------------------------
# Console mode forces H.264 (avc1) at <=1080p so the Pi 4's V4L2 hardware
# decoder can handle it -- falls back gracefully if a video genuinely has
# no H.264 variant available. That constraint doesn't apply to web mode:
# decoding happens client-side in the viewer's own browser, not on the
# server, and modern browsers handle VP9/AV1 and much higher resolutions
# natively -- so web mode gets noticeably better quality for free.
_CONSOLE_FORMAT_SELECTOR = (
    "bestvideo[vcodec^=avc1][height<=1080]+bestaudio[ext=m4a]/"
    "best[vcodec^=avc1][height<=1080]/"
    "best[height<=1080]"
)
_WEB_FORMAT_SELECTOR = (
    "bestvideo[height<=2160]+bestaudio/"
    "best[height<=2160]/"
    "best"
)
FORMAT_SELECTOR = _CONSOLE_FORMAT_SELECTOR if PLAYBACK_MODE == "console" else _WEB_FORMAT_SELECTOR

# --- Playback ------------------------------------------------------------
MPV_HWDEC = "v4l2m2m"   # hardware decode mode for Pi 4 (V4L2 M2M)
# ALSA `hw:` fails on the Pi 4's vc4-hdmi devices ("Can't find appropriate
# sample format" -- they don't support mpv's format/rate without conversion).
# `plughw:` routes through ALSA's plug layer, which converts as needed.
# CARD=vc4hdmi0 is the HDMI port nearest the USB-C power connector; use
# vc4hdmi1 (port nearest the audio jack) if audio is plugged into that one.
MPV_AUDIO_DEVICE = "alsa/plughw:CARD=vc4hdmi0,DEV=0"
# mpv's DRM output (--gpu-context=drm, what it auto-selects with no desktop
# running) defaults --drm-mode to "preferred" -- it re-reads the TV's EDID
# and requests its highest-resolution mode the instant mpv opens the
# display, regardless of whatever /boot/firmware/cmdline.txt's video=
# argument locked at boot (see README's HDMI/resolution setup step). On a
# 4K-capable TV that snaps the display back up to 4K right as playback
# starts, and decoding/scaling our modest-resolution H.264 source up to
# 4K is what causes audio/video drift. Pin the same connector/mode locked
# at boot so mpv doesn't renegotiate. Update DRM_CONNECTOR/DRM_MODE below
# to match if you changed the video= value in cmdline.txt (find valid
# values on the Pi with `mpv --drm-connector=help` / `--drm-mode=help`).
DRM_CONNECTOR = "HDMI-A-1"
DRM_MODE = "1280x720@60"
MPV_EXTRA_ARGS = [
    "--fs",
    "--really-quiet",
    "--no-terminal",
    "--ao=alsa",
    f"--audio-device={MPV_AUDIO_DEVICE}",
    "--gpu-context=drm",
    f"--drm-connector={DRM_CONNECTOR}",
    f"--drm-mode={DRM_MODE}",
]

# --- Console display ------------------------------------------------------
# The physical screen Spin Cycle sits in front of (a TV over HDMI, showing
# a Linux virtual console when nothing's playing). mpv already renders
# straight to this display via DRM/KMS no matter which session launched the
# process; splash.py opens this device explicitly so the idle-screen banner
# does too, rather than just going to whatever stdout main.py happened to
# inherit (e.g. an SSH session's pty, which isn't what's on the TV).
# Override via SPINCYCLE_CONSOLE_TTY if the Pi's console isn't tty1 for some
# reason. Requires write access to the device -- see splash.py.
CONSOLE_TTY = os.environ.get("SPINCYCLE_CONSOLE_TTY", "/dev/tty1")

# --- Library management web page (library_server.py) ---------------------
# Port 80 is privileged on Linux -- see library_server.py's module
# docstring for the setcap incantation needed to bind it without root.
LIBRARY_SERVER_HOST = "0.0.0.0"
LIBRARY_SERVER_PORT = 80


def ensure_dirs():
    os.makedirs(VIDEO_DIR, exist_ok=True)


def cache_root_problem():
    """
    Try to create CACHE_ROOT and return a human-readable problem
    description if it's not usable (missing drive, permission denied,
    etc.), or None if it's fine. Callers on the startup/hot path should
    use this instead of a bare ensure_dirs() so a bad CACHE_ROOT never
    crashes the app or blocks the web remote from coming up -- that's the
    only way to fix it via the Settings panel instead of ssh.
    """
    try:
        ensure_dirs()
    except OSError as e:
        return str(e)
    return None
