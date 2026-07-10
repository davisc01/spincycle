"""
Central configuration for the jukebox. Edit these paths for your setup.
"""
import os

# --- Storage paths -----------------------------------------------------
# Point this at your external USB drive's mount point.
# e.g. if the drive auto-mounts at /media/pi/JUKEBOX, use that path.
CACHE_ROOT = os.environ.get("JUKEBOX_CACHE_ROOT", "/mnt/usbdrive/jukebox_cache")

VIDEO_DIR = os.path.join(CACHE_ROOT, "videos")
INDEX_FILE = os.path.join(CACHE_ROOT, "index.json")       # url -> local path map
ARCHIVE_FILE = os.path.join(CACHE_ROOT, "yt-dlp-archive.txt")  # yt-dlp's own "already downloaded" ledger

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


def ensure_dirs():
    os.makedirs(VIDEO_DIR, exist_ok=True)
