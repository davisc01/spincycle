# Music Video Jukebox

A Raspberry Pi 4 powered music video jukebox, built into a 3D-printed case
styled like an old car stereo: two rotary dials up front (genre on the
left, era on the right) and a horizontal LCD in the middle. Turn the dials
like tuning a radio -- stop turning, and it starts loading and playing a
shuffled, continuously-looping set of music videos on the connected TV
over HDMI (once every track's played, it reshuffles and keeps going).
Videos are
sourced from YouTube via yt-dlp and lazily cached to local storage so
playback never depends on the network once a video's been played once.

**Status:** software (caching, playback, library) works today via a
browser-based web remote (genre/era selectors, skip/stop, settings).
Physical hardware (LCD, rotary encoders) is on order -- see "Controls"
below for what exists now vs. what's coming.

## Hardware

- Raspberry Pi 4 (any RAM size), HDMI to TV
- External USB 3 SSD for the video cache (don't use the SD card for this)
- 16x2 I2C LCD (HD44780 controller + PCF8574 backpack) -- top row shows the
  live genre/era selection, bottom row shows status/errors
- 2x bare-shaft EC11 rotary encoders (5-pin: CLK, DT, SW, +, GND),
  panel-mounted through the case front -- left dial = genre, right dial = era
- Breadboard + jumper wires for prototyping; perfboard + headers for the
  final solder-down once the wiring's proven out

## Setup on the Pi (Raspberry Pi OS 64-bit)

The app lives at `/opt/apps/jukebox`. `/opt/apps` is chown'd to your user
(e.g. `pi`) so you can clone/pull and manage the venv without `sudo`; `/opt`
itself stays root-owned.

1. System packages:
   ```
   sudo apt update
   sudo apt install mpv python3-full
   ```

2. Get the code onto the Pi and create a virtual environment. Raspberry Pi
   OS's system Python is externally managed (PEP 668) and refuses
   `pip install` outside a venv, so don't reach for `--break-system-packages`
   -- just use a venv like anywhere else:
   ```
   git clone <repo-url> /opt/apps/jukebox
   cd /opt/apps/jukebox
   python3 -m venv venv
   venv/bin/pip install -r requirements.txt
   ```
   From here on, run everything via `venv/bin/python3` (or `source
   venv/bin/activate` first).

3. Plug in your external USB drive and note its mount point, e.g. `/media/pi/JUKEBOX`.
   Point the app at it:
   ```
   export JUKEBOX_CACHE_ROOT=/media/pi/JUKEBOX/jukebox_cache
   ```
   (Add this line to `~/.bashrc` or a systemd service's `Environment=` so it's
   always set.) If you'd rather not deal with environment variables at all,
   skip this step -- `main.py` boots fine either way -- and instead set the
   cache path from the web remote's Settings panel ("Cache storage
   location") once it's running (step 6). That takes effect immediately (no
   restart) and is remembered across restarts in `config/settings.json`,
   which then takes priority over `JUKEBOX_CACHE_ROOT` from then on.

   Without either one set, the app falls back to a `cache/` folder inside
   the repo just so it always boots -- it's `.gitignore`'d and works
   everywhere, but it lives on the same storage as the code (the SD card,
   on a Pi), which defeats the point of using an external drive (see
   "Target hardware" in `CLAUDE.md`). Don't leave it there for real parties;
   a bad or unmounted path is never fatal (the web remote still comes up so
   you can fix it), and the main page shows a warning banner whenever the
   configured cache folder isn't actually usable.

4. Add your videos to `config/library.csv`. It's a plain CSV with these
   columns (header row required):
   ```
   artist,song,genre,era,url
   Example Artist,Example Song,Rock,80s,https://www.youtube.com/watch?v=XXXXXXXXXXX
   ```
   Open it in any text editor or spreadsheet app -- no need to hand-write
   JSON structure. Rows missing a genre, era, or url are skipped with a
   warning rather than breaking the app. A starter library of 18 well-known
   tracks across Rock/Pop/Hip-Hop and the 80s/90s/2000s ships in the repo.

   Instead of editing the file directly on the Pi (scp/git pull), open the
   web remote's Settings panel (see step 6) from any browser on your LAN at
   `http://<pi-ip>/` (or `http://raspberrypi.local/` -- Raspberry Pi OS
   runs Avahi/mDNS by default, so the `.local` hostname resolves on the LAN
   without knowing the Pi's IP) and download/upload `library.csv` from
   there. Uploads are validated before being accepted, so a malformed CSV
   never overwrites the live one. **No authentication** -- LAN-only, same
   trust level as ssh. The web server starts automatically in the
   background whenever `main.py` runs (step 6); run `venv/bin/python3
   library_server.py` directly if you want library upload/download and
   cache-warming without launching full playback (e.g. remote library
   maintenance between parties) -- the genre/era/skip/stop controls simply
   report unavailable (503) when run this way, since there's no
   `JukeboxController` behind them.

   It binds port 80 by default so you don't need `:8080` in the URL, but
   port 80 is privileged on Linux -- binding it will fail with "Permission
   denied" unless you either run as root (not recommended here, since the
   server accepts file uploads and has no auth) or grant the interpreter
   permission to bind low ports once:
   ```
   sudo setcap 'cap_net_bind_service=+ep' $(readlink -f venv/bin/python3)
   ```
   Re-run that command any time you rebuild the venv (a new `python3`
   binary needs the capability reapplied). This applies whether you run
   `library_server.py` standalone or via `main.py` -- both bind the same
   port with the same interpreter. If the capability isn't granted,
   `main.py` still runs the jukebox fine; it just logs that the web page
   couldn't start and carries on. No firewall changes are needed on a
   stock Raspberry Pi OS install -- it doesn't ship with `ufw` enabled by
   default.

5. (Optional but recommended) Pre-warm the cache so party night doesn't
   depend on your internet connection:
   ```
   venv/bin/python3 video_cache.py
   ```
   This walks the whole library and downloads anything not yet cached,
   printing progress as it goes. Safe to re-run any time you add new URLs --
   already-cached videos are skipped instantly. The web remote's Settings
   panel (step 6) has a "Warm cache" button that does this remotely, with a
   live progress line and a scrollable log of anything that failed to
   download.

6. Run the jukebox:
   ```
   venv/bin/python3 main.py
   ```
   This starts a `JukeboxController` plus the web remote from step 4 in the
   background -- same host/port, same setcap requirement. Open
   `http://<pi-ip>/` (or `http://raspberrypi.local/`) in a browser on your
   laptop or phone: pick a genre and an era and playback starts
   automatically (re-picking either one re-tunes: stops the current video
   and starts the new combination), Skip/Stop control the current track,
   and the Settings button opens the library upload/download, cache-warm,
   and log panels from steps 4-5.

## Controls

### Today: web remote

Until the rotary encoders and LCD are wired up, `main.py` starts a
`JukeboxController` and drives it from the browser-based web remote
(`http://<pi-ip>/`, see step 6 above): a genre `<select>`, an era
`<select>`, and Skip/Stop buttons. Picking a genre and an era starts
playback automatically -- no separate confirm step, since picking from a
dropdown is already a deliberate action. Changing either selection
mid-playback re-tunes: stops the current video and starts the new
combination. Skip moves to the next track without changing the selection;
Stop halts playback and returns to browsing. A Settings button opens the
library upload/download, cache-warm trigger, and cache/playback log panels.

There's also a terminal keyboard mockup (`menu.py` + `input_device.py`)
left over from before the web remote existed, with a browse-a-list-then-
confirm menu:

| Key            | Action                        |
|----------------|--------------------------------|
| w / Up arrow   | Rotate one direction (move up)  |
| s / Down arrow | Rotate other direction (move down) |
| Enter / Space  | Push the selector button (confirm) |
| k              | Press the skip button (next track) |
| q              | Back out of a menu / stop playback and return to menu |

It's dev/testing-only now -- run it directly with `venv/bin/python3
menu.py`; `main.py` no longer starts it, since running it alongside the web
remote would mean two independent mpv processes fighting over the same
screen and speaker.

Both the genre and era lists have one extra entry past the real values:
**"Anything"** (genre) and **"Anytime"** (era). Picking either relaxes that
half of the match -- e.g. genre `Rock` + era `Anytime` plays all Rock
regardless of era; `Anything` + a specific era plays that era across every
genre; `Anything` + `Anytime` shuffles the entire library.

### Coming: radio-tuner model (real hardware)

Once the dials and LCD are installed, the interaction changes from a menu
tree to something closer to tuning an old car radio:

- Turning the **genre dial** (left) live-updates the genre shown on the
  LCD. Turning the **era dial** (right) live-updates the era. No
  confirmation press needed for either.
- Once both dials have been still for about a second, that combination is
  considered selected and the jukebox automatically starts caching and
  playing a shuffled set -- the LCD's bottom row shows "loading..." then
  the current track.
- Turning either dial again -- even mid-playback -- stops the current
  video and drops back into live browsing, like re-tuning a station.
- **Genre dial's push-button** = skip the current track.
- **Era dial's push-button** = stop playback and return to browsing.
- Each dial has one extra detent past its real values -- "Anything" on the
  genre dial, "Anytime" on the era dial -- for playing across whichever
  half you leave wide open (see "Anything"/"Anytime" above).

This means the dials' built-in push-buttons are *not* used to confirm a
genre/era pick -- only for skip and stop, since selection happens
automatically once you stop turning.

## Project layout

- `config.py` - paths, yt-dlp format string, mpv settings. Edit this first.
- `config/library.csv` - your actual video library: artist, song, genre,
  era, url. Easiest file to hand-edit; open it in any text editor or
  spreadsheet app.
- `library.py` - loads `library.csv` into the genre -> era -> tracks
  structure, and resolves a genre/era pick (including the
  "Anything"/"Anytime" wildcards) into a track list. Also runnable
  standalone to sanity-check the file (`python3 library.py`).
- `video_cache.py` - lazy caching layer. Also runnable standalone to
  pre-warm the whole library (`python3 video_cache.py`).
- `controller.py` - `JukeboxController`, the live playback engine behind
  the web remote: tracks the current genre/era/track, and shuffles/plays/
  skips/stops on a background thread as selections change. Logs each
  track play/skip/error to `config.PLAYBACK_LOG`. Intentionally decoupled
  from `input_device.py`'s `Event` model so a future GPIO dial input could
  drive it too.
- `library_server.py` - LAN-only web server for the whole web remote:
  serves `web/index.html`/`style.css`/`app.js`, a JSON API
  (`/api/status`, `/api/genre`, `/api/era`, `/api/skip`, `/api/stop`,
  `/api/logs/...`) backed by a `JukeboxController`, and the
  library-management routes (`/upload`, `/library.csv` download,
  `/warm-cache`). `main.py` starts it automatically in a background
  thread; it's also runnable standalone (`python3 library_server.py`) for
  library maintenance without full playback (the controller-backed routes
  503 in that mode).
- `web/` - the browser UI: `index.html`, `style.css`, `app.js` (vanilla
  JS, no build step, polls `/api/status`).
- `player.py` - mpv subprocess wrapper (play / skip).
- `input_device.py` - input abstraction. `KeyboardInput`, built for the
  discrete menu model in `menu.py`. Not used by `main.py` -- see below.
- `menu.py` - dev/testing-only terminal keyboard mockup (Genre -> Era ->
  shuffled playback), superseded by the web remote. Run it directly
  (`python3 menu.py`) if you want it; `main.py` doesn't start it.
- `main.py` - entry point, dependency check, creates the
  `JukeboxController` and starts `library_server.py` in the background,
  then just waits (the web remote owns all interactivity).

## Moving to the rotary encoders and LCD

The current `menu.py`/`input_device.py` pair is built around a
press-to-confirm menu tree (`NEXT`/`PREV`/`SELECT`/`SKIP`/`QUIT` events),
which doesn't map cleanly onto "two continuously-live dials with
settle-based auto-commit." Rather than bolting the radio-tuner behavior
onto the old event model, both files get rewritten together around:

1. A **settle timer** per dial -- each rotation resets a "last moved"
   timestamp; a dial is "locked" once ~700ms-1000ms pass with no movement.
2. An `RPLCD`-based display layer for the 16x2 I2C LCD (top row = live
   genre/era, bottom row = status/errors).
3. `gpiozero.RotaryEncoder` + `gpiozero.Button` for the two dials and
   their push-buttons.

`player.py` and `video_cache.py` stay as-is -- this rework is scoped to
the input/menu layer only.

## Why H.264, not VP9/AV1

The Pi 4's V4L2 M2M hardware decoder handles H.264 (and HEVC) but not
VP9/AV1, which is what YouTube serves by default at higher resolutions.
`config.FORMAT_SELECTOR` forces yt-dlp to grab the H.264 variant of each
video so playback stays hardware-accelerated instead of falling back to
slow software decode.
