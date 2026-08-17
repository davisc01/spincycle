# macOS (windowed app) deployment target

A sibling to `deploy/container/`, reusing the same
[`app/`](../../app/) codebase unchanged: `Spin Cycle.app` runs
`library_server.py` in web mode (`SPINCYCLE_PLAYBACK_MODE=web`, same as
`deploy/container` -- no mpv, no DRM/ALSA, decoding happens client-side)
as a background process on your Mac, with a real window (a `WKWebView`
pointed at the local server) instead of a foreground terminal program or
a container. It behaves like any other Mac app -- Dock icon, bounces on
launch, stays in the Dock while running, Cmd-Q/File menu to quit -- but
under the hood it's the same server: other devices on your LAN can still
reach it directly, exactly like they'd reach a k3s/container deployment
(same JSON API, same web remote, same single-session-store constraint,
see "Single instance only" below). The window is just this Mac's own
client onto that server, not a separate app.

See the main [README.md](../../README.md) for the overall project
description and "Using the web remote" for how the session picker works.

## Why this exists

Not everyone trying Spin Cycle has a home server or a k8s cluster.
If you've already got a Mac, this gets you the same
multi-viewer web experience as `deploy/container` with nothing to
provision -- no Docker/Podman, no volumes to wire up, no port-forwarding
through a router. Build it once, double-click it, done.

## Prerequisites

- macOS with Xcode Command Line Tools (`xcode-select --install` if you
  don't already have them -- needed for `iconutil`/`sips`, used by
  `build.sh` to generate the app icon).
- Python 3.10 or 3.11 (`build.sh` prefers these over whatever `python3`
  resolves to system-wide -- py2app support for brand-new CPython
  releases lags behind). `brew install python@3.11` if you don't have
  one.
- **ffmpeg**, via Homebrew: `brew install ffmpeg`. yt-dlp needs it to mux
  separately-downloaded video/audio streams -- without it, every track
  fails to cache (`ERROR: ... ffmpeg is not installed`). `build.sh` warns
  if it's missing but still builds, since the app should come up either
  way (see `config.cache_root_problem()`).

## Build and run

```bash
cd deploy/macos
./build.sh
open "dist/Spin Cycle.app"
```

`build.sh` creates a throwaway venv (`.venv-build/`, gitignored), installs
`app/requirements.txt` plus this directory's build-time deps (`py2app`,
the PyObjC Cocoa/WebKit bindings, `pillow`), crops one dial out of the
existing `app/images/spin_cycle_icon_1024.png` artwork for the app icon
(the full two-dial strip goes illegible once shrunk to Dock/Finder sizes;
a single dial reads fine), and runs `py2app`. Re-run it any time you
change code under `app/` -- it rebuilds clean each time (`rm -rf build
dist` first).

Launching opens a normal window with the web remote in it -- the same
session picker you'd see in a browser. Closing the window doesn't quit
the app (same convention as Mail/Preview -- the server and Dock icon stay
up; click the Dock icon again to bring the window back). To actually
quit: **Cmd-Q**, or **Spin Cycle -> Quit Spin Cycle** in the menu bar. The
**File** menu also has:

- **Open in Browser** -- opens the same remote in your default browser,
  if you'd rather use that than the app's own window.
- **Reveal Video Cache in Finder** / **Reveal Library File in Finder** --
  jump straight to where things live on disk (see below).

## Where things live

Unlike the container target (bind-mounted `app/config`, a PVC), a
packaged `.app`'s own `Contents/Resources` isn't a sensible place to keep
a growing library or cache -- rebuilding the app would wipe it, and
per-user data doesn't belong inside an app bundle at all. Instead:

- `~/Library/Application Support/Spin Cycle/config/` -- `library.db` (the
  live library -- a local SQLite file) and `settings.json`. A starter
  `library.csv` is seeded here on first launch only and imported into
  `library.db` automatically; neither is ever overwritten by a rebuild, so
  edits made via the web remote's Library panel persist across app
  updates.
- `~/Library/Application Support/Spin Cycle/cache/` -- the video cache.
  Gets large; same caveat as the other targets about sizing storage for
  your library.

Both are driven by `SPINCYCLE_CONFIG_DIR`/`SPINCYCLE_CACHE_ROOT`, which
`app.py` sets before importing anything from `app/` (see `config.py`'s
`CONFIG_DIR`/`CACHE_ROOT` -- both are read once at import time, the same
pattern the other two targets already rely on for their own env vars).

## Port 8080, not 80

Port 80 is privileged on macOS same as Linux (`config.py`'s
`LIBRARY_SERVER_PORT` comment). Rather than requiring `sudo` or a setcap
equivalent just to launch a normal app, this target sets
`SPINCYCLE_SERVER_PORT=8080` (a new env override in `config.py`, additive
-- the container target is untouched and keeps defaulting to 80). The
app's own window always points at `http://localhost:8080/`; another
device on your LAN reaches the same server at
`http://<hostname>.local:8080/` (check `System Settings -> General ->
Sharing` for your Mac's local hostname).

## The macOS Local Network permission prompt

The first time another device on your LAN actually reaches the app (not
when it just starts), macOS pops a **"Spin Cycle" would like to find and
connect to devices on your local network** prompt. This is expected --
`setup.py`'s `NSLocalNetworkUsageDescription`/`NSBonjourServices` plist
entries are what make the prompt fire at all; without them, incoming LAN
connections just silently fail with no explanation. Approve it once and
it's remembered (`System Settings -> Privacy & Security -> Local
Network`).

## Single instance only

Same constraint as `deploy/container` (see its README's "Single replica
only"): sessions live in the running process's memory, not shared
storage. That's a non-issue here since a Mac app is inherently one
instance -- just don't try to run two copies pointed at the same
`Application Support` folder simultaneously.

## Sharing the built app with someone else

Handing your `dist/Spin Cycle.app` to another Mac user (AirDrop, a zip
over email, etc.) works, but macOS Gatekeeper will block the first launch
with **"Apple cannot check it for malicious software"** -- this build
is only ad-hoc signed (enough to run on your own machine), not signed
with a paid Apple Developer ID or notarized. The recipient needs to
right-click the app and choose **Open** (instead of double-clicking) the
first time to bypass that. There's no way around this without enrolling
in Apple's $99/yr Developer Program and notarizing the build -- same cost
floor as the tvOS/iOS distribution friction discussed for those targets.

(`build.sh` re-signs the bundle as its last step, after stripping a
couple of build-only files out of it -- editing a signed bundle's
contents invalidates its signature, and Gatekeeper enforces that strictly
on anything that picks up a quarantine flag, which is exactly what
AirDrop/a zip/a download does. Skipping that re-sign step would make a
shared copy fail with "Spin Cycle is damaged and can't be opened" instead
of the expected right-click-to-open prompt.)

## Security

Same as `deploy/container`: `library_server.py` has no authentication.
Fine for LAN-only trust; if your Mac's network is shared with people you
don't trust with playback/library control, that's true of this target
too.
