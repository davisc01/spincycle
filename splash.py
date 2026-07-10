"""
Retro-styled console banner for startup/shutdown.

Static, one-shot rendering only (not a live dashboard) -- called once each
from main.py. Relies entirely on rich's own TTY/color-system detection so
this renders correctly whether launched from an interactive dev terminal or
handed a bare Linux virtual console by a systemd service (TERM=linux,
StandardOutput=tty), which is the actual deployment target.
"""
from rich.box import DOUBLE
from rich.console import Console, Group
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text

ACCENT_STYLE = "bold gold1"

BANNER = (
    "##### ####  ### #   #   ##### #   # ##### #     #####\n"
    "#     #   #  #  ##  #   #      # #  #     #     #    \n"
    "##### ####   #  # # #   #       #   #     #     #### \n"
    "    # #      #  #  ##   #       #   #     #     #    \n"
    "##### #     ### #   #   #####   #   ##### ##### #####"
)

TAGLINE = "~ your car-stereo jukebox ~"

console = Console()


def show_startup(host: str, port: int, video_dir: str) -> None:
    body = Group(
        Text(BANNER, style=ACCENT_STYLE, justify="center"),
        Text(TAGLINE, style="dim italic " + ACCENT_STYLE, justify="center"),
        Text(""),
        Text(f"Web remote: http://{host}:{port}/ (LAN only, no auth)", style=ACCENT_STYLE),
        Text(f"Video cache: {video_dir}", style=ACCENT_STYLE),
        Text("Ctrl+C to quit.", style=ACCENT_STYLE),
    )
    console.print(
        Panel(
            body,
            box=DOUBLE,
            border_style=ACCENT_STYLE,
            style=ACCENT_STYLE + " on black",
            padding=(1, 2),
        )
    )


def show_shutdown() -> None:
    console.print(Rule(style=ACCENT_STYLE))
    console.print(Text("Goodnight.", style=ACCENT_STYLE))
