# Raspberry Pi (console) deployment target

One physical Raspberry Pi 4 plugged into a TV over HDMI -- mpv renders
straight to the display via DRM/KMS, and `install.sh` sets this up as a
systemd-managed Podman container running a single `SpinCycleController`
for the device's whole lifetime. See the main
[README.md](../../README.md) for the overall project description, and
[`deploy/container/README.md`](../container/README.md) for the other
deployment target (a multi-viewer web deployment with no physical
device).

## Hardware

- Raspberry Pi 4 (any RAM size), HDMI to TV
- External USB 3 SSD for the video cache (don't use the SD card for this)

## Setup (Raspberry Pi OS 64-bit)

The Spin Cycle app itself lives in [`app/`](../../app/): a device-agnostic
codebase with a `Dockerfile`, no assumptions baked in about which machine
it runs on. Per-target install scripts live under `deploy/` -- this
directory is the Raspberry Pi one; a different device or deployment
method later would be a new sibling folder that builds the same `app/`
image rather than a fork of the codebase. Clone the repo anywhere your
user can write -- no fixed install path required:

```
git clone <repo-url> spincycle
cd spincycle/deploy/raspberrypi
./install.sh
```

`install.sh` does everything by hand-setup used to require:

- installs **Podman** (a daemonless container runtime -- ships directly in
  Raspberry Pi OS's own apt repo, no third-party repo needed)
- forces 720p HDMI output by editing `config.txt` and `cmdline.txt` in
  `/boot/firmware` (older Raspberry Pi OS: `/boot`) -- see "Customizing
  the HDMI resolution" below for *why* three separate places need this
  if you ever need to change it
- builds the spincycle container image from `app/`
- installs and enables a systemd service (`spincycle.service`, generated via
  `podman generate systemd`) that runs Spin Cycle as a **privileged**
  container -- broad host device access (GPU/DRM, V4L2 hardware decode,
  ALSA, the physical console) in exchange for not having to hand-enumerate
  exact device nodes. Consistent with the trust level already implied by
  the web remote having no authentication -- this is a single-purpose LAN
  appliance, not a multi-tenant server.
- also bind-mounts the host's `/usr/share/alsa` into the container
  read-only. Device *node* access (`/dev/snd`) isn't enough on its own --
  Raspberry Pi OS's `alsa-utils`/`libasound2` build ships card-specific
  config (`/usr/share/alsa/cards/vc4-hdmi.conf`) that the container's
  plain-Debian base image doesn't have, and without it ALSA's format
  negotiation against `vc4-hdmi` fails even though the device is visible.
  Confirmed by testing on real hardware: video (DRM/V4L2) worked from the
  first container run with no changes needed; audio needed this fix.

It prompts for confirmation before editing boot files or installing the
service, and prompts for your video cache location (see below). Non-
interactive re-runs (e.g. after a `git pull`) can skip both prompts:

```
./install.sh --cache-root=/media/pi/SPINCYCLE/spincycle_cache --yes
```

Re-run `install.sh` any time you update the code -- every step is
idempotent (it won't duplicate boot config lines, and it rebuilds the
image and recreates the systemd service cleanly even if one's already
installed), which doubles as the upgrade path after a `git pull`.

Once it's done, the service is already enabled and running:

```
sudo systemctl status spincycle     # is it up?
journalctl -u spincycle -f          # live logs
sudo systemctl restart spincycle    # after editing config.py, etc.
```

A few things are still manual, since they're about your specific setup
rather than anything `install.sh` can decide for you:

1. **Video cache location.** `install.sh` prompts for your external USB
   SSD's mount point (e.g. `/media/pi/SPINCYCLE`) and bind-mounts it into
   the container at `/cache` (`SPINCYCLE_CACHE_ROOT=/cache` inside the
   container). This is fixed for the life of the deployment -- since
   `SPINCYCLE_CACHE_ROOT` is always set in the container's environment,
   the app itself refuses to change it at runtime (the web remote's
   Settings panel shows it read-only, under "Deployment info," rather
   than as an editable field). To change it later, re-run `install.sh`
   with a different `--cache-root` (see below) -- that regenerates the
   systemd service with the new bind mount. Leaving it blank at install
   time falls back to a local dir under `data/cache` in this directory --
   it's `.gitignore`'d and works everywhere, but it lives on the SD card,
   which defeats the point of using an external drive (see "Target
   hardware" in `../../CLAUDE.md`). Don't leave it there for real
   parties; a bad or unmounted path is never fatal (the web remote still
   comes up so you can fix it), and the main page shows a warning banner
   whenever the configured cache folder isn't actually usable.

2. **Add your videos.** Open the web remote's **Library** panel from any
   browser on your LAN at `http://<pi-ip>/` (or `http://raspberrypi.local/`
   -- Raspberry Pi OS runs Avahi/mDNS by default, so the `.local` hostname
   resolves on the LAN without knowing the Pi's IP). It's a sortable table
   of every track with Add/Edit/Delete/Preview per row -- adding a song
   only needs artist/song/genre/era; a "Search YouTube" button finds and
   fills in the URL for you (preferring an official-video result), and a
   Preview button opens it in a new tab so you can double check before
   saving. **No authentication** -- LAN-only, same trust level as ssh. See
   the main [README.md](../../README.md)'s "Using the web remote" section
   for how to drive playback once it's up.

   For bulk changes, the Library panel's Export/Import CSV buttons round-
   trip the same `artist,song,genre,era,url` format the library used to be
   stored as directly:
   ```
   artist,song,genre,era,url
   Example Artist,Example Song,Rock,80s,https://www.youtube.com/watch?v=XXXXXXXXXXX
   ```
   Export, edit in any spreadsheet app or text editor, then re-import in
   either "append" (adds rows, keeps the existing library) or "replace all"
   mode -- uploads are validated before being accepted, so a malformed CSV
   never overwrites the live library. Rows missing a genre, era, or url are
   skipped with a warning rather than breaking the app. A starter library
   of 18 well-known tracks across Rock/Pop/Hip-Hop and the 80s/90s/2000s
   ships in the repo. `install.sh` bind-mounts `app/config` into the
   container (rather than baking it into the image), so the library
   persists across image rebuilds without any extra step.

3. **(Optional but recommended) Pre-warm the cache** so party night
   doesn't depend on your internet connection:
   ```
   sudo podman run --rm -v "$PWD/../../app/config:/app/config" \
     -v "$PWD/data/cache:/cache" -e SPINCYCLE_CACHE_ROOT=/cache \
     spincycle:latest python3 video_cache.py
   ```
   (adjust the cache volume path to match whatever you gave `--cache-root`
   at install time). This walks the whole library and downloads anything
   not yet cached, printing progress as it goes. Safe to re-run any time
   you add new URLs -- already-cached videos are skipped instantly. The
   web remote's Library panel also has a "Warm cache" button that does
   this remotely, with a live progress line; any track that fails shows a
   "Failed" badge in the table (click it for the error) so a bad link can
   be fixed or deleted right there without downloading the whole file. That
   badge reflects only the most recent warm-cache run for that track, not
   an accumulating history.

## Customizing the HDMI resolution / connector

`install.sh` defaults to forcing 720p on `HDMI-A-1` (auto-detecting a
different connected port and warning you if it finds one). You shouldn't
need to touch this unless you're changing resolution or moving the TV to
the Pi's other HDMI port, but it's worth understanding *why* it takes
three separate places to actually stick, in case something needs
hand-tuning:

1. **Firmware-level boot splash** -- `hdmi_force_hotplug=1` /
   `hdmi_group=1` / `hdmi_mode=4` in `config.txt` (`hdmi_mode=4` is
   1280x720@60Hz in the CEA mode table, the right table for a TV rather
   than a PC monitor). This alone only covers the firmware splash, though.
2. **Kernel/KMS-level lock** -- with the full `vc4-kms-v3d` KMS driver
   this project requires (see `../../CLAUDE.md`'s "Target hardware"), the
   kernel's DRM driver does its own EDID negotiation once Linux takes
   over and reverts to the TV's preferred (usually highest) mode,
   ignoring `hdmi_mode`. That's the "starts at 720p, then jumps back up"
   symptom. Locking the post-boot mode needs a `video=HDMI-A-1:1280x720@60D`
   argument appended to `cmdline.txt` (single line, no newline inserted).
   The `D` suffix forces that exact timing rather than a fallback hint the
   driver can still override. If you move the TV to the Pi 4's other HDMI
   port, re-run `install.sh` (it re-detects the connector) or edit
   `cmdline.txt` by hand with `HDMI-A-2`. Check which connector is live:
   ```
   for f in /sys/class/drm/card*-HDMI-*; do echo "$f: $(cat $f/status)"; done
   ```
   Reboot after editing. Confirm the active mode with `dmesg | grep -i
   drm` or `modetest -c` (from `libdrm-tests`) -- don't rely on
   `tvservice`, it's a legacy-firmware-driver tool and doesn't reflect
   reality under `vc4-kms-v3d`.
3. **mpv's own DRM output** -- even with 1 and 2 locked, mpv's
   `--gpu-context=drm` defaults `--drm-mode` to `preferred`, re-reading
   the TV's EDID and requesting its highest-resolution mode the instant
   mpv opens the display, independent of the `cmdline.txt` lock. That's
   why the TV can jump back to 4K (and drift out of audio/video sync)
   specifically when a track starts playing. `config.py`'s
   `DRM_CONNECTOR`/`DRM_MODE` pin mpv to the same connector/mode as
   `cmdline.txt` -- **`install.sh` does not edit this file**; if you use a
   non-default connector or resolution, update `DRM_CONNECTOR`/`DRM_MODE`
   in `../../app/config.py` by hand to match, then `sudo systemctl restart
   spincycle` (no image rebuild needed if you only touched `config.py`
   values that are read at runtime -- but note `config.py` itself *is*
   baked into the image, so a source change here does need a re-run of
   `install.sh` to rebuild). Use `mpv --drm-connector=help` /
   `--drm-mode=help` on the Pi to see valid values for your hardware.

## `/dev/tty1` and the console splash

`main.py` prints a retro "Spin Cycle" splash and tries to write it
directly to the physical console (`/dev/tty1` by default, see
`config.CONSOLE_TTY`) so the idle screen looks like part of the device on
the TV, not just in your SSH session -- mpv already renders straight to
that display over DRM/KMS regardless of how the process was launched, so
the splash does the same. Current Raspberry Pi OS ships `/dev/tty1` as
`root`-only (`crw-------`) -- console access is granted dynamically per
logged-in session rather than via static group permissions, so a
non-root process on the host can't normally open it. The container
sidesteps this entirely: `spincycle.service` runs the container as a
privileged root process, which can open `/dev/tty1` directly, no
`TTYPath=` dance needed the way a bare host process would.
