# Music Video Jukebox

A Raspberry Pi 4 powered music video jukebox, built into a 3D-printed case
styled like an old car stereo: two rotary dials up front (genre on the
left, era on the right) and a horizontal LCD in the middle. Turn the dials
like tuning a radio -- stop turning, and it starts loading and playing a
shuffled set of music videos on the connected TV over HDMI. Videos are
sourced from YouTube via yt-dlp and lazily cached to local storage so
playback never depends on the network once a video's been played once.

**Status:** software (caching, playback, library) works today via a
keyboard-driven mockup. Physical hardware (LCD, rotary encoders) is on
order -- see "Controls" below for what exists now vs. what's coming.

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

1. System packages:
   ```
   sudo apt update
   sudo apt install mpv python3-pip
   ```

2. Python dependencies:
   ```
   pip3 install -r requirements.txt
   ```

3. Plug in your external USB drive and note its mount point, e.g. `/media/pi/JUKEBOX`.
   Point the app at it:
   ```
   export JUKEBOX_CACHE_ROOT=/media/pi/JUKEBOX/jukebox_cache
   ```
   (Add this line to `~/.bashrc` or a systemd service's `Environment=` so it's
   always set. Default if unset is `/mnt/usbdrive/jukebox_cache` -- edit
   `config.py` directly if you'd rather hardcode your path.)

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

5. (Optional but recommended) Pre-warm the cache so party night doesn't
   depend on your internet connection:
   ```
   python3 video_cache.py
   ```
   This walks the whole library and downloads anything not yet cached,
   printing progress as it goes. Safe to re-run any time you add new URLs --
   already-cached videos are skipped instantly.

6. Run the jukebox:
   ```
   python3 main.py
   ```

## Controls

### Today: keyboard mockup (discrete menu)

Until the rotary encoders and LCD are wired up, `main.py` runs a
keyboard-driven stand-in with a browse-a-list-then-confirm menu:

| Key            | Action                        |
|----------------|--------------------------------|
| w / Up arrow   | Rotate one direction (move up)  |
| s / Down arrow | Rotate other direction (move down) |
| Enter / Space  | Push the selector button (confirm) |
| k              | Press the skip button (next track) |
| q              | Back out of a menu / stop playback and return to menu |

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

This means the dials' built-in push-buttons are *not* used to confirm a
genre/era pick -- only for skip and stop, since selection happens
automatically once you stop turning.

## Project layout

- `config.py` - paths, yt-dlp format string, mpv settings. Edit this first.
- `config/library.csv` - your actual video library: artist, song, genre,
  era, url. Easiest file to hand-edit; open it in any text editor or
  spreadsheet app.
- `library.py` - loads `library.csv` into the genre -> era -> tracks
  structure the menu uses. Also runnable standalone to sanity-check the
  file (`python3 library.py`).
- `video_cache.py` - lazy caching layer. Also runnable standalone to
  pre-warm the whole library (`python3 video_cache.py`).
- `player.py` - mpv subprocess wrapper (play / skip).
- `input_device.py` - input abstraction. `KeyboardInput` today, built for
  the discrete menu model above. Will be replaced (not just extended) by a
  GPIO-based input source once hardware lands -- see below.
- `menu.py` - the current discrete state machine (Genre -> Era -> shuffled
  playback). Will be replaced by the live dual-dial model above.
- `main.py` - entry point, dependency check.

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
