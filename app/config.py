"""
Central configuration for Spin Cycle. Edit these paths for your setup.
"""
import json
import os

# --- Storage paths -----------------------------------------------------
# Point this at your external USB drive's mount point via
# SPINCYCLE_CACHE_ROOT=/media/pi/SPINCYCLE/spincycle_cache, set once at
# deploy time (see deploy/raspberrypi/install.sh's --cache-root flag).
# Don't leave it on the fallback default below for real use. That default
# is just a repo-local folder (already .gitignore'd) chosen so the app
# always boots even before you've mounted a drive or set a real path; it
# lives on the same storage as the code (the SD card, on a Pi), which
# CLAUDE.md's hardware notes explicitly say to avoid for actual video I/O.
#
# CACHE_ROOT (and the paths derived from it below) can also be changed at
# runtime via set_cache_root() -- but only when SPINCYCLE_CACHE_ROOT isn't
# already set in the environment, which both deploy targets always do (see
# set_cache_root() below). In practice that makes this reachable only for a
# bare `python3 main.py` run outside a container, not console or web
# deployments -- the web remote's Settings panel shows this value read-only
# ("Deployment info") and has no editable field for it either way. A
# change persists to SETTINGS_FILE so it survives a restart, taking
# priority over SPINCYCLE_CACHE_ROOT/the hardcoded default from then on.
# Everything else in the app reads these as `config.VIDEO_DIR` etc. (fresh
# attribute lookups, never a cached local copy), so a runtime change takes
# effect immediately everywhere without a restart.
#
# CONFIG_DIR defaults to the in-repo config/ folder (bind-mounted by the Pi
# and container targets), but a bundled app -- deploy/macos's .app, whose
# own Resources folder isn't a sensible place for a user's growing
# library.csv/settings.json -- overrides it via SPINCYCLE_CONFIG_DIR to a
# writable, per-user directory instead (see deploy/macos/menubar_app.py).
CONFIG_DIR = os.environ.get("SPINCYCLE_CONFIG_DIR", os.path.join(os.path.dirname(__file__), "config"))
SETTINGS_FILE = os.path.join(CONFIG_DIR, "settings.json")
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
    global VIDEO_DIR, INDEX_FILE, PLAYBACK_LOG
    VIDEO_DIR = os.path.join(CACHE_ROOT, "videos")
    INDEX_FILE = os.path.join(CACHE_ROOT, "index.json")       # url -> local path map
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


LIBRARY_FILE = os.path.join(CONFIG_DIR, "library.csv")
# The live library store (see library.py). LIBRARY_FILE above is kept only
# as the one-time migration source (an existing library.csv is imported
# into LIBRARY_DB the first time anything touches the library -- see
# library._ensure_db()) and as the target of CSV import/export -- nothing
# in the app writes to LIBRARY_FILE itself anymore.
LIBRARY_DB = os.path.join(CONFIG_DIR, "library.db")

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
# no H.264 variant available. Web mode relaxes the resolution cap to 4K
# but still prefers avc1 first: Safari's VP9/AV1 support is hardware-gated
# per chip with no software fallback (VP9 needs A12+/Apple Silicon, AV1
# needs A17 Pro/M3+), so a bare "best" selector plays fine on some
# viewers' devices and silently fails to play at all on others (confirmed:
# iPhone playable, iPad/Intel MacBook not, because YouTube's 4K streams
# are almost always VP9/AV1). H.264 decodes everywhere, hardware or
# software, on every browser -- falling back to non-avc1 only when a video
# genuinely has no H.264 variant at that resolution.
_CONSOLE_FORMAT_SELECTOR = (
    "bestvideo[vcodec^=avc1][height<=1080]+bestaudio[ext=m4a]/"
    "best[vcodec^=avc1][height<=1080]/"
    "best[height<=1080]"
)
_WEB_FORMAT_SELECTOR = (
    "bestvideo[vcodec^=avc1][height<=2160]+bestaudio/"
    "best[vcodec^=avc1][height<=2160]/"
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
# Unix socket player.py uses to send the MTV-style overlay text to mpv via
# its JSON IPC protocol (show-text). A single fixed path is safe: console
# mode runs exactly one Player for the app's whole lifetime, and play()
# never runs two mpv processes concurrently (it blocks on wait()).
MPV_IPC_SOCKET = "/tmp/spincycle-mpv-ipc.sock"
MPV_EXTRA_ARGS = [
    "--fs",
    "--really-quiet",
    "--no-terminal",
    "--ao=alsa",
    f"--audio-device={MPV_AUDIO_DEVICE}",
    "--gpu-context=drm",
    f"--drm-connector={DRM_CONNECTOR}",
    f"--drm-mode={DRM_MODE}",
    f"--input-ipc-server={MPV_IPC_SOCKET}",
    # Lower-left OSD alignment for the MTV-style overlay -- fine to apply
    # globally since nothing else on the physical console shows OSD text
    # (no keyboard/seek interaction there).
    "--osd-align-x=left",
    "--osd-align-y=bottom",
    "--osd-color=#39FF8A",
    "--osd-font-size=32",
    "--osd-margin-x=48",
    "--osd-margin-y=64",
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
# Port 80 is privileged on Linux and macOS alike -- see library_server.py's
# module docstring for the setcap incantation needed to bind it without
# root. SPINCYCLE_SERVER_PORT overrides it for targets that'd rather not
# require root/sudo at all (deploy/macos runs unprivileged on 8080).
LIBRARY_SERVER_HOST = "0.0.0.0"
LIBRARY_SERVER_PORT = int(os.environ.get("SPINCYCLE_SERVER_PORT", 80))


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
