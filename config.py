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
MPV_EXTRA_ARGS = ["--fs", "--really-quiet", "--no-terminal"]


def ensure_dirs():
    os.makedirs(VIDEO_DIR, exist_ok=True)
