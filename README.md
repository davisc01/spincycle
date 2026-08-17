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

<p align="center">
  <img src="images/Screenshot 1.png" alt="Spin Cycle remote -- genre and era dials" width="45%">
  &nbsp;&nbsp;
  <img src="images/Screenshot 2.png" alt="Spin Cycle Library panel -- track list and add-song form" width="45%">
</p>

## Installation

Spin Cycle ships as two deployment targets, both built from the same
codebase ([`app/`](app/)) -- pick whichever fits how you want to run it,
and follow that target's README for the actual install steps:

- **[Web (container)](deploy/container/README.md)** -- run the image on
  a home server, NAS, or Kubernetes cluster; a browser tab you open
  becomes the player instead of mpv/DRM, and it supports multiple
  simultaneous viewers, each with their own session.
- **[macOS (windowed app)](deploy/macos/README.md)** -- the same web-mode
  experience, packaged as `Spin Cycle.app`: a normal Mac app (Dock icon,
  Cmd-Q) whose window is the web remote -- runs on your Mac, no Docker,
  no volumes, nothing to provision if you've already got a Mac.

Once it's running, load your video library -- see "Using the web remote"
below, and [`My_Video_List.csv`](My_Video_List.csv) in this repo for an
example of a full library ready to import via the Library panel's Import
CSV button.

## Using the web remote

Open the app's address in a browser on your LAN -- exactly where depends
on how you exposed it (see the deploy READMEs linked above). Works the
same on desktop and mobile, no app install needed.

The landing page is a session picker -- **+ New Session** (optionally
paired with a dropdown to start from a saved playlist instead of the
whole library -- see "Playlists" below), **Select** to open a session's
own genre/era/skip/stop controls plus a **Launch Player** button,
**Close** to tear one down -- since each browser tab/device gets its own
independent selection and player.

Picking a genre and an era starts playback automatically -- no separate
confirm step, since picking from a dropdown is already a deliberate
action. Changing either selection mid-playback re-tunes: stops the
current video and starts the new combination. Skip moves to the next
track without changing the selection; Stop halts playback and returns to
browsing. A Library button opens a sortable table of every track (with
per-row Preview/Edit/Delete, an add-song form with a YouTube-search
helper, and CSV export/import for bulk changes), a Playlists section
(see below), plus the cache-warm trigger and playback log panels.

Below Skip/Stop, a **DJ Request** button opens an inline panel listing
every song in the current genre/era, sorted by artist, with the
currently-playing track highlighted. Hit **Queue** on any song to have
it play right after the current one -- go back and hit Skip to jump to
it immediately, or just let the current video finish. An "Up next" line
above the panel always shows what's coming up: whichever song you
queued, or, if you haven't queued anything, a preview of the next
randomly-shuffled pick.

### Library

The **Library** button opens a panel with everything for managing your
video collection and the app's playback behavior:

- **Tracks** -- a sortable table of every song in the library (Artist,
  Song, Genre, Era, Cache status), with per-row Preview/Edit/Delete and
  checkbox-based bulk delete. **+ Add song** opens a form for adding one
  track at a time (with a "Search YouTube" helper that fills in the URL
  for you to preview before saving). **Export CSV** downloads the whole
  library as a CSV file; **Import CSV** loads one back in, either
  appending to the existing library or replacing it outright -- see
  [`My_Video_List.csv`](My_Video_List.csv) in this repo for an example
  file in the expected format.
- **Playlists** -- build a named, reusable subset of the library: filter
  by genre/era, check off songs, and save. Starting a new session offers
  a dropdown to pick one of your saved playlists instead of the whole
  library -- once picked, the genre/era dials and shuffle work exactly
  as usual, just limited to that playlist's tracks for the life of that
  session. Editing or deleting a playlist afterward never affects a
  session already running from it, and there's no route to switch a
  live session's playlist -- close it and start a new one instead.
- **Overlays** -- a logo + phrase banner (e.g. "Intermission...") shown
  across the top of the player during playback. Only one overlay can be
  active at a time.
- **Cache warming** -- kicks off a background pass that downloads any
  library track not already cached locally, so playback never has to
  stall waiting on a first-time download.
- **Playback log** -- a running log of what's played, skipped, or
  failed to cache, for troubleshooting a session after the fact.

Both the genre and era lists have one extra entry past the real values:
**"Anything"** (genre) and **"Anytime"** (era). Picking either relaxes that
half of the match -- e.g. genre `Rock` + era `Anytime` plays all Rock
regardless of era; `Anything` + a specific era plays that era across every
genre; `Anything` + `Anytime` shuffles the entire library.
