# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

Music video jukebox for a Raspberry Pi 4, built into a 3D-printed case
styled like an old car stereo. Two rotary dials (genre on the left, era on
the right) pick what plays; a horizontal LCD in the middle shows the
selection. Videos come from a local library that only stores YouTube URLs;
a lazy caching layer downloads each video once via yt-dlp and plays the
local copy on every subsequent request, so runtime playback never depends
on network availability.

## Target hardware / environment

- **Raspberry Pi 4**, Raspberry Pi OS (64-bit, current `vc4-kms-v3d` driver
  stack -- not the legacy FKMS stack `omxplayer` needed).
- Playback via **mpv** with `--hwdec=v4l2m2m`. This is the load-bearing
  constraint of the whole project: the Pi 4's hardware decoder handles
  H.264 (and HEVC) but *not* VP9/AV1, which is what YouTube serves by
  default at higher resolutions. `config.FORMAT_SELECTOR` forces yt-dlp to
  select the H.264 (`avc1`) stream. Don't relax that format string without
  understanding this tradeoff -- it's the difference between smooth
  hardware-decoded playback and a Pi choking on software VP9 decode.
- Video cache lives on an external USB 3 SSD, not the SD card (`JUKEBOX_CACHE_ROOT`
  env var, see `config.py`). SD cards have weak write endurance; don't
  route heavy video I/O through one.

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

## Interaction model (target design -- not yet implemented)

This is a **radio-tuner** model, not a menu tree with confirm clicks:

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

This is a bigger change than swapping `KeyboardInput` for a `GpioInput`
with the same interface. The current `Event` model (`NEXT`/`PREV`/
`SELECT`/`SKIP`/`QUIT`) was built for a discrete "browse a list, press to
confirm" menu tree and doesn't map cleanly onto "two continuously-live
dials with settle-based auto-commit." Expect to redesign `input_device.py`
and `menu.py` together for this -- don't try to force the old `SELECT`
event into the new model. `player.py` and `video_cache.py` should be
largely unaffected.

## Architecture (current code, pre-radio-redesign)

| File | Responsibility |
|---|---|
| `config.py` | Paths, yt-dlp format selector, mpv args. Start here for any environment-specific change. |
| `library.py` | Parses `config/library.csv` into `{genre: {era: [track_dict]}}`. Track dicts have `artist`/`song`/`url`. Also exposes `genre_options()`/`era_options()`/`tracks_for()`, which layer the `ANY_GENRE`/`ANY_ERA` ("Anything"/"Anytime") wildcard picks on top of the raw structure -- `menu.py` (and eventually the dial-driven picker) should go through these rather than indexing the dict directly. |
| `video_cache.py` | Lazy caching: `ensure_cached(url)` returns a local path, downloading via yt-dlp only if not already indexed. `warm_cache()` walks the whole library (used by the standalone `python3 video_cache.py` pre-warm run). Index is a JSON file (`url -> local path`), written atomically. |
| `player.py` | Thin mpv subprocess wrapper. One subprocess per video; `skip()` just terminates it. |
| `input_device.py` | Input abstraction. Currently `KeyboardInput` (w/s or arrows, Enter/Space, k, q) built for the old menu-tree model -- **will be replaced** per the interaction model above, not just extended. |
| `menu.py` | Currently a discrete state machine: Genre list -> Era list -> shuffle -> play loop, reshuffling and looping forever once the set is exhausted until skip/quit. **Will be replaced** with the dual-dial live-tuning model above. |
| `main.py` | Entry point; dependency check (mpv installed? yt-dlp importable?) before touching the menu. |
| `library_server.py` | Standalone HTTP endpoint (no auth, LAN-only) for replacing `config/library.csv` from the network without ssh/scp, and for triggering/monitoring a `video_cache.warm_cache()` run with a persisted failure log (`config.WARM_CACHE_LOG`). Not imported by `main.py`. |

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

## Commands

```bash
# Sanity-check the library parses correctly
python3 library.py

# Pre-warm the video cache (walks entire library, downloads anything missing)
python3 video_cache.py

# Run the jukebox (keyboard-driven menu mockup, pre-radio-redesign)
python3 main.py

# Start the library-management web server (upload a new library.csv,
# trigger/monitor cache warming) -- binds 0.0.0.0:8080 by default
python3 library_server.py

# Syntax-check everything
python3 -m py_compile config.py library.py video_cache.py player.py input_device.py menu.py main.py library_server.py
```

There's no test suite yet -- `library.py`'s `__main__` block and manual runs
of `video_cache.py`/`main.py` are the current verification loop. If adding
real tests, prefer testing `library.py`'s CSV parsing (pure, no external
deps) and `video_cache.py`'s index read/write logic over anything that
touches mpv, yt-dlp, GPIO, or I2C directly (those need real
network/hardware). The settle-timer logic in the new interaction model is
a good candidate for a pure unit test (feed it fake timestamps, assert
lock/unlock transitions) once it exists.

## Conventions

- Python 3, no framework, minimal dependencies (only `yt-dlp` in
  `requirements.txt`; `mpv`, `gpiozero`, and the I2C LCD library (`RPLCD`)
  are the other expected runtime dependencies once hardware lands --
  `mpv` is a system package, `gpiozero`/`RPLCD` are pip packages).
- f-strings throughout, keep that style.
- Errors during playback (a video fails to fetch) should be logged and
  skipped, not crash the whole playback loop -- someone's mid-party when
  this runs. Under the new model, an error should also surface on the
  LCD's bottom row, not just stdout.
- Don't add a database. The CSV + JSON index pattern is intentional: it's
  meant to be hand-editable and inspectable without tooling.

## Known gaps / next steps

- Hardware (LCD, 2x rotary encoders) is on order, not yet on the bench --
  `input_device.py`/`menu.py` still reflect the old discrete-menu keyboard
  mockup, not the radio-tuner model described above.
- Once hardware arrives: build the settle-timer input abstraction, the
  `RPLCD`-based display layer (top row genre/era, bottom row status), and
  rewrite `menu.py` around live dual-dial state instead of a list-based
  state machine.
- No systemd service file yet for auto-start on boot.
- No 3D-printed case files in this repo yet -- consider a `case/` directory
  once STL/CAD files exist, with panel cutout dimensions matching the
  final LCD and encoder bushing sizes.
