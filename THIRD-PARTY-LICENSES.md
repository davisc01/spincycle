# Third-party licenses

Spin Cycle's own code is [MIT-licensed](LICENSE). The prebuilt macOS and
Windows downloads on the [Releases
page](https://github.com/davisc01/spincycle/releases) also bundle a few
third-party components directly into the app so a fresh install doesn't
need anything else set up first. This file covers those.

## ffmpeg (GPL)

`deploy/macos/build.sh` and `deploy/windows/build.ps1` each bundle a
prebuilt `ffmpeg` binary into the packaged app (Homebrew's `ffmpeg`
formula on macOS, the `Gyan.FFmpeg` winget package on Windows), so
`yt-dlp` can mux downloaded video/audio streams without requiring the
user to install ffmpeg themselves. Both of those builds are compiled
with `--enable-gpl` (they include `libx264`/`libx265`), which makes the
bundled binary itself **GPL-licensed** -- see
<https://www.ffmpeg.org/legal.html> and the license text at
<https://www.gnu.org/licenses/gpl-3.0.html>.

Spin Cycle only ever invokes this binary as a separate subprocess (the
same way `yt-dlp` and `mpv` do elsewhere in this codebase) -- it's never
linked into Spin Cycle's own code, so this doesn't place Spin Cycle
itself under the GPL. It does mean the *ffmpeg binary specifically*,
wherever it's redistributed as part of a Spin Cycle download, remains
governed by its own GPL terms, independent of the MIT license on
everything else in this repo. ffmpeg's source is publicly available at
<https://github.com/FFmpeg/FFmpeg>; the exact build configs used here are
Homebrew's
([formula](https://github.com/Homebrew/homebrew-core/blob/master/Formula/f/ffmpeg.rb))
and Gyan Doshi's
([builds](https://www.gyan.dev/ffmpeg/builds/)) respectively.

## yt-dlp (Unlicense)

[`yt-dlp`](https://github.com/yt-dlp/yt-dlp) is used as a Python library
dependency (`app/requirements.txt`) for fetching video/audio from
YouTube. It's released into the public domain under the
[Unlicense](https://github.com/yt-dlp/yt-dlp/blob/master/LICENSE) --
no attribution or license-passthrough obligations.

## rich (MIT)

[`rich`](https://github.com/Textualize/rich) is used as a Python library
dependency (`app/requirements.txt`) for the console splash/startup
output (`splash.py`). Released under the
[MIT license](https://github.com/Textualize/rich/blob/master/LICENSE),
same terms as Spin Cycle's own code.
