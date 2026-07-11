"""
Retro-styled console banner for startup/shutdown.

Static, one-shot rendering only (not a live dashboard) -- called once each
from main.py. Renders to two places: whatever stdout the process inherited
(useful when run interactively -- dev terminal, SSH session) and, if
reachable, config.CONSOLE_TTY (the physical console device, e.g. the TV
over HDMI) -- mpv already renders straight to that display via DRM/KMS
regardless of which session launched the process, so the idle screen
should too, rather than leaving the TV stuck on the login prompt while the
banner only shows up over SSH. Relies entirely on rich's own TTY/color
detection for each target rather than special-casing "am I on a real
console vs. dev terminal" -- that keeps this correct whether launched
locally, over SSH, or (eventually) by a systemd service with
StandardOutput=tty.
"""
import os
import sys

from rich.box import DOUBLE
from rich.console import Console, Group
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text

import config

ACCENT_STYLE = "bold gold1"

# Can't rely on rich's auto-detected terminal size for CONSOLE_TTY below --
# Console.size checks the process's own stdin/stdout/stderr file descriptors,
# not the file object it's actually printing to, so a separately-opened
# device would otherwise pick up whatever terminal launched the process
# (e.g. a wide SSH window) instead of the physical console's real size. 80
# columns is the standard Linux virtual console width.
CONSOLE_WIDTH = 80

# Deliberately NOT multi-row block-letter ASCII art -- tried that twice (5x5,
# then 5x7 dot-matrix) and both came out illegible on the real console: Linux
# virtual terminals put visible vertical gaps between text lines (normal line
# spacing), so adjacent rows of a pixel font never touch and vertical strokes
# read as disconnected blobs instead of continuous lines. That's a property
# of how the console spaces lines, not something fixable by tweaking glyph
# shapes. A single spaced-out, bold line of the terminal's own font glyphs
# can't suffer that problem -- there's nothing that needs to visually merge
# across rows -- so that's the retro-marquee effect used here instead.
BANNER = "S P I N     C Y C L E"

TAGLINE = "~ your car-stereo jukebox ~"


def _consoles():
    """
    Yield every Console this session should render the splash to.
    """
    stdout_console = Console()
    yield stdout_console

    stdout_device = None
    try:
        stdout_device = os.ttyname(sys.stdout.fileno())
    except OSError:
        pass  # not a tty (piped/redirected) -- fine, just means no dedup below

    console_tty = config.CONSOLE_TTY
    if stdout_device is not None and os.path.realpath(stdout_device) == os.path.realpath(console_tty):
        return  # stdout already *is* the physical console -- don't print twice

    try:
        tty_file = open(console_tty, "w")
    except FileNotFoundError:
        return  # no such device -- expected on a non-Pi dev machine
    except OSError as e:
        print(
            f"[splash] Could not open console {console_tty} for the idle screen ({e}). "
            "Console devices are typically root-only until a session claims them -- run "
            "as root for now, or (eventually) package this as a systemd service with "
            "TTYPath= set, which grants ownership automatically. The banner will still "
            "show up here over SSH in the meantime.",
            file=sys.stderr,
        )
        return

    yield Console(file=tty_file, width=CONSOLE_WIDTH)


def show_startup(host: str, port: int, video_dir: str) -> None:
    body = Group(
        Text(BANNER, style=ACCENT_STYLE, justify="center"),
        Text(TAGLINE, style="dim italic " + ACCENT_STYLE, justify="center"),
        Text(""),
        Text(f"Web remote: http://{host}:{port}/ (LAN only, no auth)", style=ACCENT_STYLE),
        Text(f"Video cache: {video_dir}", style=ACCENT_STYLE),
        Text("Ctrl+C to quit.", style=ACCENT_STYLE),
    )
    panel = Panel(
        body,
        box=DOUBLE,
        border_style=ACCENT_STYLE,
        style=ACCENT_STYLE + " on black",
        padding=(1, 2),
    )
    for console in _consoles():
        console.clear()
        console.print(panel)


def show_shutdown() -> None:
    for console in _consoles():
        console.print(Rule(style=ACCENT_STYLE))
        console.print(Text("Goodnight.", style=ACCENT_STYLE))
