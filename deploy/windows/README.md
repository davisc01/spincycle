# Windows (windowed app) deployment target

A third sibling to `deploy/container/` and `deploy/macos/`, reusing the
same [`app/`](../../app/) codebase unchanged: `Spin Cycle.exe` runs
`library_server.py` in web mode (`SPINCYCLE_PLAYBACK_MODE=web`, same as
`deploy/container` and `deploy/macos` -- no mpv, decoding happens
client-side) as a background thread, with a real window (a
[pywebview](https://pywebview.flowrl.com/) window, backed by the Windows
WebView2/Edge-Chromium runtime) instead of a terminal program or a
container. Other devices on your LAN can still reach the same server
directly, exactly like they'd reach a container deployment (same JSON
API, same web remote, same single-session-store constraint, see "Single
instance only" below). The window is just this PC's own client onto that
server, not a separate app.

See the main [README.md](../../README.md) for the overall project
description and "Using the web remote" for how the session picker works.

## Why this exists

Not everyone trying Spin Cycle has a home server, a k8s cluster, a spare
Raspberry Pi, or a Mac. If you've already got a Windows PC, this gets you
the same multi-viewer web experience as `deploy/container` with nothing
to provision -- no Docker/Podman, no volumes to wire up, no
port-forwarding through a router. Build it once, double-click it, done.

## Prerequisites

- **Python 3.10 or 3.11** (`build.ps1` prefers these, via the `py`
  launcher, over whatever `python` resolves to system-wide --
  PyInstaller support for brand-new CPython releases lags behind). Get
  one from [python.org](https://www.python.org/downloads/windows/) or
  `winget install Python.Python.3.11`.
- **ffmpeg**, on `PATH`: `winget install Gyan.FFmpeg`. yt-dlp needs it to
  mux separately-downloaded video/audio streams -- without it, every
  track fails to cache (`ERROR: ... ffmpeg is not installed`). `build.ps1`
  warns if it's missing but still builds, since the app should come up
  either way (see `config.cache_root_problem()`).
- **WebView2 Runtime** -- already preinstalled on Windows 11 and current
  Windows 10 builds. If pywebview's window fails to open with a
  WebView2-related error, install the [Evergreen
  Bootstrapper](https://developer.microsoft.com/microsoft-edge/webview2/)
  from Microsoft.

## Build and run

```powershell
cd deploy\windows
.\build.ps1
& "dist\Spin Cycle\Spin Cycle.exe"
```

`build.ps1` creates a throwaway venv (`.venv-build\`, gitignored),
installs `app\requirements.txt` plus this directory's build-time deps
(`pywebview`, `pythonnet`, `pyinstaller`, `pillow`), crops one dial out of
the existing `app/images/spin_cycle_icon_1024.png` artwork for the app
icon (same artwork/crop the macOS target uses, converted straight to
`.ico` via Pillow), runs PyInstaller (`--onedir`), and zips the result to
`dist\Spin Cycle-windows.zip`. Re-run it any time you change code under
`app/` -- it rebuilds clean each time.

Launching opens a window with the web remote in it -- the same session
picker you'd see in a browser. Unlike the macOS target's Dock-icon
convention, closing the window quits the app outright (a background tray
icon / re-open-on-click convention could be added later via pywebview's
`webview.menu`/tray APIs, but isn't implemented here). The web remote is
also always reachable in a regular browser at the same address (see
below), independent of whether the app window is open.

## Where things live

Unlike the container target (a bind-mounted volume), a packaged
`Spin Cycle.exe`'s own folder isn't a sensible place to keep a growing
library or cache -- rebuilding wipes it, and per-user data doesn't belong
next to the executable at all. Instead:

- `%LOCALAPPDATA%\Spin Cycle\config\` -- `library.db` (the live library --
  a local SQLite file) and `settings.json`. A starter `library.csv` is
  seeded here on first launch only and imported into `library.db`
  automatically; neither is ever overwritten by a rebuild, so edits made
  via the web remote's Library panel persist across app updates.
- `%LOCALAPPDATA%\Spin Cycle\cache\` -- the video cache. Gets large; same
  caveat as the other targets about sizing storage for your library.

Both are driven by `SPINCYCLE_CONFIG_DIR`/`SPINCYCLE_CACHE_ROOT`, which
`app.py` sets before importing anything from `app/` (see `config.py`'s
`CONFIG_DIR`/`CACHE_ROOT` -- both are read once at import time, the same
pattern the other two targets already rely on for their own env vars).

## Port 8080, not 80

Port 80 needs admin privileges on Windows same as Linux/macOS
(`config.py`'s `LIBRARY_SERVER_PORT` comment). Rather than requiring the
app to run elevated just to launch, this target sets
`SPINCYCLE_SERVER_PORT=8080` (the same additive env override the macOS
target uses -- the Pi/container targets are untouched and keep defaulting
to 80). The app's own window always points at `http://localhost:8080/`;
another device on your LAN reaches the same server at
`http://<this-pc-name>:8080/` (check **Settings -> System -> About** for
your PC's name).

## The Windows Defender Firewall prompt

The first time another device on your LAN actually reaches the app (not
when it just starts), Windows pops a **Windows Defender Firewall has
blocked some features of this app** prompt asking to allow access on
private/public networks. This is expected -- the app is listening on
`0.0.0.0:8080` for exactly that purpose (see
`config.LIBRARY_SERVER_HOST`). Allow it (at least for **Private
networks**) and it's remembered.

## Single instance only

Same constraint as `deploy/container`/`deploy/macos` (see their READMEs'
"Single instance/replica only"): sessions live in the running process's
memory, not shared storage. Don't run two copies pointed at the same
`%LOCALAPPDATA%\Spin Cycle` folder simultaneously.

## Sharing the built app with someone else

Handing your `dist\Spin Cycle-windows.zip` to another Windows user
works, but Windows SmartScreen will likely block the first launch with
**"Windows protected your PC"** -- this build isn't signed with a paid
code-signing certificate. The recipient needs to click **More info ->
Run anyway** the first time to bypass that -- the Windows equivalent of
macOS Gatekeeper's right-click-to-open friction on an unsigned/ad-hoc
`.app`. There's no way around this without buying a code-signing
certificate, same cost floor as the macOS target's notarization note.

## Security

Same as `deploy/container`/`deploy/macos`: `library_server.py` has no
authentication. Fine for LAN-only trust; if your network is shared with
people you don't trust with playback/library control, that's true of
this target too.
