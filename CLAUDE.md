# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

Spin Cycle is a music video jukebox, controlled from a web app in the
browser (desktop or mobile, no install) rather than physical controls --
pick a genre and an era and it starts a shuffled, continuously-looping set
of music videos on the connected TV. Videos come from a local library that
only stores YouTube URLs; a lazy caching layer downloads each video once
via yt-dlp and plays the local copy on every subsequent request, so
runtime playback never depends on network availability.

**Two deployment targets share one codebase and container image:**
- **Console (Raspberry Pi 4)** -- `deploy/raspberrypi/`, one physical
  device plugged into a TV over HDMI, mpv renders straight to the display
  via DRM/KMS. Single `SpinCycleController` for the device's whole
  lifetime.
- **Web (k3s)** -- `deploy/k3s/`, a multi-viewer deployment where a
  browser tab you open (via "Launch Player") becomes the player instead of
  mpv/DRM. Adds `sessions.py`'s `SessionManager`: each browser tab/device
  gets its own independent genre/era selection and player.

A 3D-printed car-stereo case with physical rotary dials (genre) and an LCD
was the *original* plan and may still happen, but the web remote turned
out to be the better interface and is what actually runs today -- see
"Physical build (on hold)" below for that design, kept for later rather
than discarded.

The codebase is device-agnostic and lives in `app/` -- all file paths
below are relative to that directory, not the repo root, unless noted.
`app/` builds a single container image (`app/Dockerfile`) via Podman;
per-target install/deploy configs live under `deploy/` (`deploy/
raspberrypi/`, `deploy/k3s/`) -- a future deployment target (a different
device, or a different install method) is a new sibling under `deploy/`
reusing the same `app/` image, not a fork of the codebase. `case/`
(3D-printed case files, not yet populated) and this `CLAUDE.md`/`README.md`
stay at the repo root since they're either target-agnostic or describe
the whole repo.

## Target hardware / environment

`config.PLAYBACK_MODE` (`SPINCYCLE_PLAYBACK_MODE` env var, default
`"console"`) switches between the two targets below; `player.make_player()`
picks `Player` (mpv) or `BrowserPlayer` accordingly, and `controller.py` is
identical either way.

### Console (Raspberry Pi 4) -- `deploy/raspberrypi/`

- **Raspberry Pi 4**, Raspberry Pi OS (64-bit, current `vc4-kms-v3d` driver
  stack -- not the legacy FKMS stack `omxplayer` needed).
- Playback via **mpv** with `--hwdec=v4l2m2m`. This is the load-bearing
  constraint of console mode: the Pi 4's hardware decoder handles H.264
  (and HEVC) but *not* VP9/AV1, which is what YouTube serves by default at
  higher resolutions. `config.FORMAT_SELECTOR` forces yt-dlp to select the
  H.264 (`avc1`) stream when `PLAYBACK_MODE == "console"`. Don't relax
  that format string without understanding this tradeoff -- it's the
  difference between smooth hardware-decoded playback and a Pi choking on
  software VP9 decode.
- Video cache lives on an external USB 3 SSD, not the SD card
  (`SPINCYCLE_CACHE_ROOT` env var, see `config.py`). SD cards have weak
  write endurance; don't route heavy video I/O through one.
- `SPINCYCLE_CACHE_ROOT` is always set by `install.sh`'s container
  invocation, which makes `config.set_cache_root()` permanently refuse at
  runtime (`RuntimeError`) -- the cache path is fixed at deploy time
  (`--cache-root`), not editable from the Settings panel. See
  README.md's "Video cache location" for the user-facing explanation.

### Web (k3s) -- `deploy/k3s/`

- No hardware decode constraint -- decoding happens client-side in the
  viewer's own browser, so `config.FORMAT_SELECTOR` uses a looser selector
  (up to 4K, any codec) when `PLAYBACK_MODE == "web"`.
- No mpv/DRM/ALSA at all; a browser tab opened via "Launch Player" polls
  `SpinCycleController.status()`'s `video_url` and plays it in a `<video>`
  tag, reporting back via `/api/sessions/<name>/video-ended`. See
  `player.py`'s `BrowserPlayer`.
- Multi-viewer: `sessions.py`'s `SessionManager` holds one independent
  `SpinCycleController` per browser session -- single replica only
  (sessions live in the pod's memory, not shared storage).
- Actual k8s manifests + ArgoCD `Application` live in the separate
  `myhomelab` GitOps repo, not here -- this repo only builds and pushes
  `ghcr.io/davisc01/spincycle:latest` via `.github/workflows/
  build-k3s-image.yml` (triggers on any push to `app/**`). See
  `deploy/k3s/README.md` and README.md's "Setup on k3s".

## Physical build (on hold)

Not built yet -- LCD and rotary encoders are on order, not on the bench.
The web remote (`library_server.py` + `web/`) is the real, working
interface today; this section is a spec to build against later, not a
description of current behavior. See README.md's "Appendix: 3D-printed
case & physical controls" for the same content in user-facing form.

### Physical controls (car-stereo design)

- **Two EC11-style rotary encoders**, bare shaft, panel-mounted through the
  case front. Left = genre, right = era. Each has a built-in push-button
  (the SW pin) which is *not* used for confirming a selection (see
  interaction model below) -- it's repurposed:
  - Genre dial's button -> **skip current track**
  - Era dial's button -> **stop playback, return to live browsing**
- **16x2 I2C LCD** (HD44780 controller + PCF8574 backpack), driven over I2C
  (SDA/SCL only). Top row (row 0) shows the live genre/era selection
  (e.g. left-aligned genre, right-aligned era on the same line). Bottom
  row (row 1) is reserved for status and error text ("loading...",
  "cache miss, skipping", track name during playback, etc.) -- keep row 0
  dedicated to the current genre/era state, don't overload it with status
  text.

Pin budget: 3 GPIO per encoder (CLK, DT, SW) x 2 = 6, plus the I2C bus
(GPIO2/GPIO3, shared) for the LCD. 8 pins total out of 40.

### Shopping list (for reference / reordering)

- 830-point solderless breadboard (prototyping stage)
- 16x2 I2C LCD (HD44780 + PCF8574 backpack, usually I2C address `0x27`)
- 2x bare-shaft EC11 rotary encoders (5-pin: CLK, DT, SW, +, GND; panel-mount
  bushing/nut/washer included on most breakout boards)
- Female-to-female jumper wires (~20)
- Perfboard + male headers + hookup wire (for the final solder-down once
  the breadboard version works)
- M2.5/M3 standoffs + screws (case assembly)

### Interaction model (target design -- not yet implemented)

This is a **radio-tuner** model, not a menu tree with confirm clicks. Note
that the web remote already implements the core idea of this model --
picking a genre/era commits immediately, no separate confirm step (see
`controller.py`) -- just via an HTTP request instead of a settling dial,
so there's no settle-timer debounce needed there. The dial/LCD version
below adds the settle-timer layer that a physical control needs and a web
`<select>` doesn't:

1. Turning the genre dial live-updates the genre shown on the LCD's top
   row. Turning the era dial live-updates the era. Both dials are
   independent and can be turned in any order.
2. There is no "press to confirm." Instead, each dial tracks a
   last-moved timestamp. After a dial has been still for a **settle
   window** (~700ms-1000ms), that dial's current value is considered
   "locked in."
3. Once **both** dials are simultaneously settled, the app automatically
   starts caching/shuffling/playing that genre+era combination -- no
   button press required. Bottom row shows "loading..." during the cache
   check, then the current track during playback.
4. If either dial is turned again -- including *during* playback --
   treat it as the user re-tuning: stop the current video and go back to
   live browsing mode immediately.
5. Genre dial's SW button = skip the current track without re-tuning.
   Era dial's SW button = stop playback and return to browsing (a manual
   escape hatch, same effect as turning a dial but without changing the
   selection).

Each dial's position list includes the `library.ANY_GENRE`/`library.ANY_ERA`
wildcard as one extra detent past the real values (e.g. genre dial:
Rock -> Pop -> Hip-Hop -> Anything -> back to Rock) -- it's a normal stop on
the dial, not a special gesture.

`input_device.py`/`menu.py`'s discrete `Event` model (`NEXT`/`PREV`/
`SELECT`/`SKIP`/`QUIT`) is a dev-only terminal keyboard mockup, already
superseded in production by the web remote -- it isn't what a GPIO dial
input would extend. A future GPIO implementation should instead drive
`controller.py`'s `SpinCycleController` directly (same `set_genre()`/
`set_era()`/`skip()`/`stop()` calls the web remote's HTTP routes already
use), adding the settle-timer debounce as a new layer in front of it
rather than reworking `input_device.py`/`menu.py`'s event model at all.
`player.py` and `video_cache.py` need no changes either way.

## Architecture (current code)

All paths are relative to `app/`, except `deploy/raspberrypi/install.sh`
and `deploy/k3s/` which are called out explicitly below.

| File | Responsibility |
|---|---|
| `Dockerfile` | Builds the Spin Cycle image, shared by both deploy targets: `python:3.11-slim-trixie` (matches Raspberry Pi OS's own Debian generation -- see "Known gaps") + `mpv`/`ffmpeg`/`ca-certificates`/`alsa-utils` via apt, `requirements.txt` via pip, then the app code. `ENTRYPOINT` is `python3 main.py`. `ffmpeg` is required (not just `mpv`) because `config.FORMAT_SELECTOR`'s `bestvideo+bestaudio` merges need it -- easy to miss since a bare-metal Pi OS install often has it incidentally. |
| `deploy/raspberrypi/install.sh` | Console-target installer: installs Podman, idempotently forces 720p in the boot config (`config.txt`/`cmdline.txt`, detecting the live HDMI connector), builds the image from `app/`, and installs+enables a `spincycle.service` systemd unit generated via `podman generate systemd --new` (bakes the full `podman run` invocation into the unit, so re-running install.sh safely regenerates it). Runs the container `--privileged` with `--network host`, bind-mounting `app/config` (so `library.csv`/`settings.json` edits persist), the cache root at `/cache` (always via `SPINCYCLE_CACHE_ROOT=/cache`, which locks the cache path for the container's lifetime -- see "Target hardware"), and the host's `/usr/share/alsa` read-only (Pi-specific ALSA config `vc4-hdmi` playback needs -- see "Known gaps"). See README.md's "Setup on the Pi". |
| `deploy/k3s/` | Web-target deploy config: just a README pointing at `.github/workflows/build-k3s-image.yml` (repo root), which builds/pushes `ghcr.io/davisc01/spincycle:latest` on every push to `app/**`. The actual k8s manifests + ArgoCD `Application` live in the separate `myhomelab` GitOps repo, not here. See `deploy/k3s/README.md` and README.md's "Setup on k3s". |
| `config.py` | Paths, yt-dlp format selector (console vs. web, see "Target hardware"), mpv args (`DRM_CONNECTOR`/`DRM_MODE`), `PLAYBACK_MODE`. `CACHE_ROOT` and everything derived from it (`VIDEO_DIR`, `INDEX_FILE`, `CACHE_FAILURES_FILE`, `PLAYBACK_LOG`) can change at runtime via `set_cache_root()`, persisted to `config/settings.json` -- except `set_cache_root()` refuses (`RuntimeError`) whenever `SPINCYCLE_CACHE_ROOT` is set in the environment, which both deploy targets always do. `cache_root_problem()` validates writability without raising, so a bad path never crashes the app. Start here for any environment-specific change. |
| `library.py` | Parses `config/library.csv` into `{genre: {era: [track_dict]}}`. Track dicts have `artist`/`song`/`url`. Also exposes `genre_options()`/`era_options()`/`tracks_for()`, which layer the `ANY_GENRE`/`ANY_ERA` ("Anything"/"Anytime") wildcard picks on top of the raw structure, and `update_url()`/`remove_by_url()` for single-row edits/deletes by URL (there's no other stable row id) -- both round-trip through `csv.DictReader`/`DictWriter` to preserve columns/order and write atomically. `menu.py` and `controller.py` go through the option/track-list helpers rather than indexing the dict directly. |
| `video_cache.py` | Lazy caching: `ensure_cached(url)` returns a local path, downloading via yt-dlp only if not already indexed. `warm_cache(library, on_progress)` walks the whole library genre/era-by-genre/era (not via a flattened list, so genre/era survive into the callback) and calls `on_progress(i, total, genre, era, track, err)` per track; used by both the standalone `python3 video_cache.py` pre-warm run and `library_server.py`'s background warm-cache. Index is a JSON file (`url -> local path`), written atomically. `prune(library)` deletes cached files/index entries for URLs no longer in the library (called after an upload or a cache-failures remove). |
| `controller.py` | `SpinCycleController` -- the live playback engine behind the web remote (console mode: one instance for the app's lifetime; web mode: one per `sessions.py` session). Setting genre/era commits immediately (no confirm step) and (re)starts a background shuffle-play loop; `reload_library()` re-parses `library.csv` in place (used after an upload or a cache-failures edit/remove). Logs each play/cache-miss to `config.PLAYBACK_LOG`. Decoupled from `input_device.py`'s `Event` model on purpose -- see "Physical build (on hold)". |
| `sessions.py` | `SessionManager`, web-mode only: owns one `SpinCycleController` per session, keyed by a random adjective-animal name (e.g. `clever-otter`) that doubles as its id. Not used in console mode -- `main.py` wires up a single bare `SpinCycleController` there instead. |
| `player.py` | `Player` (console: thin mpv subprocess wrapper, one process per video, `skip()` terminates it) and `BrowserPlayer` (web: no local playback -- blocks until a browser tab reports the video ended or skip is pressed). `make_player()` picks between them based on `config.PLAYBACK_MODE` so `controller.py` doesn't need to know which mode it's in. |
| `input_device.py` | Input abstraction. `KeyboardInput` (w/s or arrows, Enter/Space, k, q), built for `menu.py`'s old discrete menu-tree model. Dev/testing-only today -- not started by `main.py` -- and, per "Physical build (on hold)", not what a future GPIO dial input would extend either; that would drive `controller.py` directly instead. |
| `menu.py` | Terminal keyboard mockup of a discrete browse-a-list-then-confirm menu (Genre list -> Era list -> shuffle -> play loop). Dev/testing-only, superseded by the web remote -- run directly (`python3 menu.py`), not started by `main.py` (avoids two independent mpv processes fighting over one screen/speaker). |
| `main.py` | Entry point: dependency check (mpv installed in console mode? yt-dlp/rich importable?), then builds either a `SpinCycleController` (console) or a `sessions.SessionManager` (web, based on `config.PLAYBACK_MODE`) and starts `library_server.py`'s `run_server()` with it in a background daemon thread, catching `OSError` so a bind failure (e.g. port 80 without the setcap grant) logs a warning instead of crashing Spin Cycle. Also kicks off a background cache-warm run on startup so a cold cache doesn't block the first playback. Startup/shutdown console output delegated to `splash.py`. |
| `library_server.py` | LAN-only HTTP server (no auth) for the whole web remote: serves `web/` (`index.html`/`style.css`/`app.js`/`player.html`/`player.js`); a JSON API backed by either a single `SpinCycleController` (console mode: `/api/status`, `/api/genre`, `/api/era`, `/api/skip`, `/api/stop`) or a `SessionManager` (web mode: `/api/sessions`, `/api/sessions/<name>/status`, `/api/sessions/<name>/{genre,era,skip,stop,video-ended,close}`); a range-request-capable `/video/<file>` route for browser players; and library-management routes -- `/upload` (replace `library.csv`, validated, `.bak`'d, prunes orphaned cache entries), `/library.csv` download, `/warm-cache` (kicks off `video_cache.warm_cache()` in the background), and `/api/cache-failures` (+ `/edit`, `/remove`). Cache failures are a structured, rewritten-each-run list (`config.CACHE_FAILURES_FILE`: artist/song/genre/era/url/error per entry) -- cleared the instant a run starts (not just when it finishes) and rewritten fresh at the end, so a fixed or no-longer-failing entry never lingers; edit/remove rewrite the matching `library.csv` row by URL (via `library.update_url`/`remove_by_url`), back it up to `.bak` first, and reload the live controller. `run_server(host, port)` is the reusable entry point -- `main()` (CLI/argparse) and `main.py`'s background thread both call it. |
| `web/` | Browser UI, vanilla JS/CSS, no build step. `index.html`/`style.css`/`app.js` -- the remote: genre/era pickers (rendered as both a `<select>` and a draggable/scrollable fake rotary dial bound to it), Skip/Stop, a session picker in web mode, and the Settings panel (library upload/download, cache warming, cache-failures list with inline edit/remove, playback log, read-only deployment info). `player.html`/`player.js` -- the web-mode browser player opened via "Launch Player": polls a session's `video_url` and plays it in a `<video>` tag, reporting completion back to the session. |
| `splash.py` | Static ASCII-art "SPIN CYCLE" startup banner and retro-styled (amber LCD look, via `rich`) startup/shutdown console text. One-shot render, not a live dashboard -- `show_startup()`/`show_shutdown()` are each called once from `main.py`. Prints to both the inherited stdout (dev terminal/SSH) and, if writable, `config.CONSOLE_TTY` directly (`/dev/tty1` by default) -- since `mpv` renders straight to the physical display via DRM/KMS regardless of the launching session, the idle banner opens that device explicitly too rather than relying on whatever stdout it inherited, deduping if they're already the same device (e.g. once run under a future systemd `TTYPath=` service). |

## Library format

`config/library.csv`, columns: `artist,song,genre,era,url`. Header row
required. Rows missing `genre`/`era`/`url` are skipped with a printed
warning rather than raising -- keep that behavior, a malformed row
shouldn't take down the whole app. A missing *column* (not row) should
still raise `ValueError` from `library.load_library()` -- that's a real
config error, not a data quality issue.

Alongside the real genre/era values parsed from the CSV, the picker always
offers a wildcard: `library.ANY_GENRE` ("Anything") and `library.ANY_ERA`
("Anytime"). Picking one relaxes that dimension; picking both plays from
the whole library. This is a UI-layer concept only -- it's never a value
that appears in `library.csv` itself, and `library.tracks_for(library,
genre, era)` is what resolves a genre/era pick (wildcard or not) into the
matching track list.

There's no stable row id -- `library.update_url()`/`remove_by_url()` (used
by the Settings panel's cache-failures editor) match rows by `url`, so
duplicate URLs in the CSV would affect every matching row. Not currently
guarded against; keep that in mind before adding a feature that assumes
uniqueness.

## Commands

Local dev/testing (from within `app/`, `cd app` first) doesn't require a
container -- just a Python environment with `requirements.txt` installed
and `mpv` on `PATH`:

```bash
# Sanity-check the library parses correctly
python3 library.py

# Pre-warm the video cache (walks entire library, downloads anything missing)
python3 video_cache.py

# Run Spin Cycle -- starts a SpinCycleController (or, in web mode below,
# a SessionManager) plus the library-management web server in the
# background automatically.
python3 main.py

# Same, in web mode (no mpv/DRM required -- a browser tab is the player)
SPINCYCLE_PLAYBACK_MODE=web python3 main.py

# Start just the library-management web server (upload a new library.csv,
# trigger/monitor cache warming), without launching full playback -- binds
# 0.0.0.0:80 by default, which needs root or cap_net_bind_service outside
# a container (see library_server.py's module docstring)
python3 library_server.py

# Syntax-check everything
python3 -m py_compile config.py library.py video_cache.py player.py controller.py sessions.py input_device.py menu.py main.py library_server.py splash.py
```

On a Pi, `deploy/raspberrypi/install.sh` builds the image and runs
`main.py` as a systemd-managed Podman container instead (`spincycle.service`
-- see README.md's "Setup on the Pi"). Useful commands there:

```bash
cd deploy/raspberrypi
./install.sh                        # first deploy, or re-run after git pull
sudo systemctl status spincycle     # is it up?
journalctl -u spincycle -f          # live logs
sudo systemctl restart spincycle    # after editing app/config/library.csv, etc.
```

On k3s, there's no install script -- a push to `main` touching `app/**`
builds and pushes the image; the cluster doesn't pick it up automatically:

```bash
git push                                                   # builds + pushes ghcr.io/davisc01/spincycle:latest
kubectl rollout restart deployment/spincycle -n spincycle  # pick up the new image
```

There's no test suite yet -- `library.py`'s `__main__` block and manual runs
of `video_cache.py`/`main.py` are the current verification loop. If adding
real tests, prefer testing `library.py`'s CSV parsing/row-edit functions
(pure, no external deps) and `video_cache.py`'s index read/write logic
over anything that touches mpv, yt-dlp, GPIO, or I2C directly (those need
real network/hardware). The settle-timer logic in the physical-build
interaction model would be a good candidate for a pure unit test (feed it
fake timestamps, assert lock/unlock transitions) once it exists.

## Conventions

- Python 3, no framework, minimal dependencies (`yt-dlp` and `rich` in
  `requirements.txt`; `mpv`, `gpiozero`, and the I2C LCD library (`RPLCD`)
  are the other expected runtime dependencies once hardware lands --
  `mpv` is a system package, `gpiozero`/`RPLCD` are pip packages).
- f-strings throughout, keep that style.
- Errors during playback (a video fails to fetch) should be logged and
  skipped, not crash the whole playback loop -- someone's mid-party when
  this runs. Today that means `controller.py` logs to `config.PLAYBACK_LOG`
  and moves to the next track, and a warm-cache failure surfaces in the
  Settings panel's cache-failures list, not just stdout; once the physical
  LCD lands, an error should also surface on its bottom row (see "Physical
  build (on hold)").
- Don't add a database. The CSV + JSON index pattern is intentional: it's
  meant to be hand-editable and inspectable without tooling. Extend that
  to the cache-failures file too: it's plain JSON, not a log, and gets
  rewritten wholesale rather than migrated/versioned.
- Files mutated from a running process (`library.csv`, `config/
  settings.json`, `index.json`, `cache_failures.json`) are written
  atomically (`tmp` path + `os.replace`), and `library.csv` specifically
  gets a `.bak` copy before any programmatic edit (upload, or the
  cache-failures edit/remove actions) -- match this pattern for any new
  code that mutates them.

## Known gaps / next steps

- **Confirmed on real Pi 4 hardware**: hardware-accelerated V4L2 M2M
  decode + direct DRM/KMS scanout work fine from inside the privileged
  Podman container -- no base-image changes needed there. Audio took two
  rounds to fix, though: ALSA's format negotiation against `vc4-hdmi`
  failed inside the container ("Sample format not available for
  playback") even though `/dev/snd` and `/proc/asound/cards` were
  identical to the host, and even after bind-mounting the host's
  `/usr/share/alsa` (which has `cards/vc4-hdmi.conf`, defining a `hdmi`
  PCM type that does software IEC958 subframe conversion -- vc4-hdmi
  apparently can't negotiate a format at all without that wrapper) into
  the container. The config file loading wasn't enough on its own: the
  actual root cause was a Debian *generation* mismatch, not a missing
  file. Raspberry Pi OS had already moved to Debian **Trixie** (13), where
  `libasound2t64` is `1.2.14`; `app/Dockerfile`'s base image was
  `python:3.11-slim-bookworm` (Debian 12), whose `libasound2` is `1.2.8`
  -- too old to correctly execute config written for the newer alsa-lib.
  Fixed by changing the base image to `python:3.11-slim-trixie`. Confirmed
  vanilla Debian Trixie's own `libasound2-data` already ships
  `cards/vc4-hdmi.conf` (identical file size to the Raspberry Pi
  Foundation's `+rpt`-patched build) -- this was never actually a
  Pi-specific patch, just something Bookworm predates. The `/usr/share/
  alsa` bind-mount in `deploy/raspberrypi/install.sh` was kept anyway (to
  exactly match the host's patched build rather than trust a
  near-identical but not-guaranteed-identical vanilla version) but is
  likely redundant now that the base image matches. Worth remembering as
  a pattern for future Pi-hardware-touching dependencies: check the
  host's actual `/etc/apt/sources.list.d/*.list` and Debian codename
  (`apt-cache policy <package>`) before assuming a container's package
  *version* matches its base image's nominal Debian release -- Raspberry
  Pi OS tracks newer Debian generations before they're broadly "stable,"
  and a same-named package can differ by multiple minor versions across
  that gap.
- Hardware (LCD, 2x rotary encoders) is on order, not yet on the bench --
  `input_device.py`/`menu.py` still reflect the old discrete-menu keyboard
  mockup, not the radio-tuner model described in "Physical build (on
  hold)".
- Once hardware arrives: build the settle-timer input abstraction, the
  `RPLCD`-based display layer (top row genre/era, bottom row status), and
  rewrite `menu.py` around live dual-dial state instead of a list-based
  state machine.
- No 3D-printed case files in this repo yet -- consider a `case/` directory
  once STL/CAD files exist, with panel cutout dimensions matching the
  final LCD and encoder bushing sizes.
- k3s/web target has no GPU use yet despite one being available on that
  cluster's node (already used by Jellyfin there via a `/dev/dri` hostPath
  mount) -- a follow-up would be a one-time GPU-accelerated transcode step
  in `video_cache.ensure_cached()` (AMD/VAAPI) to normalize whatever
  codec/resolution YouTube served down to a consistent cached file. See
  README.md's "Setup on k3s".
