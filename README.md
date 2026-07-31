<p align="center">
  <img src="app/images/spin_cycle_logo_full.png" alt="Spin Cycle logo" width="480">
</p>

# Spin Cycle

Spin Cycle is a music video jukebox, controlled from a web app in your
browser -- desktop or mobile, no app install needed. Pick a genre and an
era and it starts playing a shuffled, continuously-looping set of music
videos on the connected TV (once every track's played, it reshuffles and
keeps going). Videos are sourced from YouTube via yt-dlp and lazily
cached to local storage so playback never depends on the network once a
video's been played once.

**Status:** software (caching, playback, library, web remote) works
today.

## Deployment targets

Three deployment targets share one codebase ([`app/`](app/)) -- see each
target's README for hardware requirements and setup instructions:

- **[Console (Raspberry Pi 4)](deploy/raspberrypi/README.md)** -- one
  physical device plugged into a TV over HDMI; mpv renders straight to
  the display via DRM/KMS, and `install.sh` sets it up as a
  systemd-managed Podman container.
- **[Web (container)](deploy/container/README.md)** -- run the same
  image on a home server, NAS, or Kubernetes cluster; a browser tab you
  open becomes the player instead of mpv/DRM, and it supports multiple
  simultaneous viewers, each with their own session.
- **[macOS (windowed app)](deploy/macos/README.md)** -- the same web-mode
  experience as the container target, packaged as `Spin Cycle.app`: a
  normal Mac app (Dock icon, Cmd-Q) whose window is the web remote --
  runs on your Mac instead of a cluster, no Docker, no volumes, nothing
  to provision if you've already got a Mac.

A future deployment target (a different device, or a different install
method) would be a new sibling under `deploy/` reusing the same `app/`
codebase, not a fork of it.

## Using the web remote

Open the app's address in a browser on your LAN -- on the console target
that's `http://<pi-ip>/` or `http://raspberrypi.local/`; for a container
deployment it depends on how you exposed it (see the deploy READMEs
linked above). Works the same on desktop and mobile, no app install
needed.

In console mode, `main.py` starts a single `SpinCycleController` and
drives it from a genre `<select>`, an era `<select>`, and Skip/Stop
buttons. In web mode, the landing page is a session picker instead --
**+ New Session**, **Select** to open a session's own genre/era/skip/stop
controls plus a **Launch Player** button, **Close** to tear one down --
since each browser tab/device gets its own independent selection and
player (see `sessions.py`).

Picking a genre and an era starts playback automatically -- no separate
confirm step, since picking from a dropdown is already a deliberate
action. Changing either selection mid-playback re-tunes: stops the
current video and starts the new combination. Skip moves to the next
track without changing the selection; Stop halts playback and returns to
browsing. A Library button opens a sortable table of every track (with
per-row Preview/Edit/Delete, an add-song form with a YouTube-search
helper, and CSV export/import for bulk changes), plus the cache-warm
trigger and playback log panels (see the deploy READMEs for how to reach
the underlying data file directly, if needed).

Below Skip/Stop, a **DJ** button opens an inline panel listing every song
in the current genre/era, sorted by artist, with the currently-playing
track highlighted. Hit **Queue** on any song to have it play right after
the current one -- go back and hit Skip to jump to it immediately, or just
let the current video finish. An "Up next" line above the panel always
shows what's coming up: whichever song you queued, or, if you haven't
queued anything, a preview of the next randomly-shuffled pick.

Both the genre and era lists have one extra entry past the real values:
**"Anything"** (genre) and **"Anytime"** (era). Picking either relaxes that
half of the match -- e.g. genre `Rock` + era `Anytime` plays all Rock
regardless of era; `Anything` + a specific era plays that era across every
genre; `Anything` + `Anytime` shuffles the entire library.

## Project layout

- [`app/`](app/) - the Spin Cycle codebase itself, device-agnostic. Builds
  one container image (`app/Dockerfile`) that the Pi and container targets
  run; the macOS target runs the same code directly (no container) via
  `py2app`. All paths below are relative to `app/` unless noted.
- [`deploy/raspberrypi/`](deploy/raspberrypi/) - `install.sh` plus its
  gitignored `data/` dir (fallback cache when no `--cache-root` is given)
  -- see [`deploy/raspberrypi/README.md`](deploy/raspberrypi/README.md)
  for hardware requirements and setup instructions.
- [`deploy/container/`](deploy/container/) - see
  [`deploy/container/README.md`](deploy/container/README.md) for what the
  image expects to run as a web deployment (env vars, volumes, port) plus
  example `docker run`/Kubernetes sketches; the GitHub Actions workflow
  that publishes this target's image is
  `.github/workflows/build-container-image.yml`.
- [`deploy/macos/`](deploy/macos/) - `build.sh` packages `app/` as
  `Spin Cycle.app`, a normal windowed Mac app (Dock icon, Cmd-Q) whose
  window is a `WKWebView` running the same web mode as the container
  target -- see [`deploy/macos/README.md`](deploy/macos/README.md). All
  three `deploy/` targets build and run the same `app/` codebase -- a
  future deployment target would be a new sibling here too, rather than
  forking it.
- `config.py` - paths, yt-dlp format string, mpv settings. Edit this first.
- `config/library.db` - your actual video library, a local SQLite file:
  artist, song, genre, era, url, plus id and cache-status columns. Manage
  it from the app's Library panel (add/edit/delete/preview per song); for
  bulk changes, use the panel's Export/Import CSV buttons rather than
  editing the SQLite file directly.
- `library.py` - loads `library.db` into the genre -> era -> tracks
  structure, and resolves a genre/era pick (including the
  "Anything"/"Anytime" wildcards) into a track list. Also exposes
  `add_track()`/`update_track()`/`delete_track()`/`delete_tracks()` for
  CRUD by id (the library's stable row id -- unlike a CSV, duplicate URLs
  don't cause ambiguity), and `import_csv()`/`export_csv_rows()` for bulk
  CSV import/export. An existing `library.csv` from before this file
  existed is imported into it automatically, once, the first time the app
  runs. Also runnable standalone to sanity-check the library
  (`python3 library.py`).
- `video_cache.py` - lazy caching layer. Also runnable standalone to
  pre-warm the whole library (`python3 video_cache.py`).
- `controller.py` - `SpinCycleController`, the live playback engine behind
  the web remote: tracks the current genre/era/track, and shuffles/plays/
  skips/stops on a background thread as selections change. `queue_next(url)`
  lets the DJ panel cut a specific track ahead of the shuffle order;
  `track_list()` returns the current genre/era's tracks (sorted by artist)
  for that panel, alongside what's playing/queued. Logs each track
  play/skip/error to `config.PLAYBACK_LOG`. Intentionally decoupled from
  `input_device.py`'s `Event` model so a future GPIO dial input could
  drive it too. Instance-scoped with no module-level globals, which is
  what lets `sessions.py` run many of them concurrently in web mode.
- `sessions.py` - `SessionManager`, web-mode only: owns one
  `SpinCycleController` per session, keyed by a random adjective-animal
  name (e.g. `clever-otter`) that doubles as its id. Not used in console
  mode -- `main.py` wires up a single bare `SpinCycleController` there.
- `library_server.py` - LAN-only web server for the whole web remote:
  serves `web/` (`index.html`/`style.css`/`app.js`/`player.html`/
  `player.js`), a JSON API backed by either a single `SpinCycleController`
  (console mode: `/api/status`, `/api/genre`, `/api/era`, `/api/skip`,
  `/api/stop`, `/api/tracks`, `/api/queue-next`) or a `SessionManager` (web
  mode: `/api/sessions`, `/api/sessions/<name>/status`, `/api/sessions/
  <name>/{genre,era,skip,stop,tracks,queue-next,video-ended,close}`) --
  `tracks`/`queue-next` back the DJ panel -- a range-request-capable
  `/video/<file>` route serving cached videos to browser players, and the
  library-management routes backing the Library panel (`/api/library-tracks`
  for add/list, `/api/library-tracks/<id>/{update,delete}`,
  `/api/library-tracks/bulk-delete`, `/api/library-tracks/search` for the
  YouTube search-and-suggest helper, `/upload`/`/upload-append` for CSV
  import, `/library.csv` for export, and `/warm-cache`). Each track's own
  `cache_error` column reflects only its most recent warm-cache attempt, so
  a fixed track's row stops showing "Failed" on the next run without any
  separate cleanup step. `main.py` starts it automatically in a background
  thread; it's also runnable standalone (`python3 library_server.py`) for
  library maintenance without full playback (the controller-backed routes
  503 in that mode).
- `web/` - the browser UI: `index.html`/`style.css`/`app.js` (the remote --
  vanilla JS, no build step, polls `/api/status` or, in web mode, the
  session picker + `/api/sessions/...`; includes the DJ panel, an inline
  song list toggled by the DJ button rather than a separate page), and
  `player.html`/`player.js` (the web-mode browser player, opened via
  "Launch Player" -- polls a session's `video_url` and plays it in a
  `<video>` tag).
- `player.py` - `Player` (mpv subprocess wrapper: play / skip) and
  `BrowserPlayer` (web mode: blocks until the browser player tab reports
  the video ended or skip is pressed). `make_player()` picks between them
  based on `config.PLAYBACK_MODE`.
- `input_device.py` - input abstraction. `KeyboardInput`, built for a
  discrete menu model, not used by `main.py`.
- `menu.py` - dev/testing-only terminal keyboard mockup, superseded by
  the web remote -- run directly with `python3 menu.py`, not started by
  `main.py`.
- `main.py` - entry point, dependency check, creates the
  `SpinCycleController` and starts `library_server.py` in the background,
  then just waits (the web remote owns all interactivity).

## Why H.264, not VP9/AV1 (console mode only)

The Pi 4's V4L2 M2M hardware decoder handles H.264 (and HEVC) but not
VP9/AV1, which is what YouTube serves by default at higher resolutions.
In console mode, `config.FORMAT_SELECTOR` forces yt-dlp to grab the H.264
variant of each video so playback stays hardware-accelerated instead of
falling back to slow software decode. This constraint doesn't apply to
the container/web deployment target -- there, decoding happens client-side
in the viewer's own browser rather than on the server, so web mode uses a
looser selector (up to 4K, any codec) instead. See
[`deploy/container/README.md`](deploy/container/README.md).
