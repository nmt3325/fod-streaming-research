# FOD Streaming Research Demo

Private command-line demo for studying streaming delivery and playback compatibility. The script accepts user-supplied authentication files, automatically detects the stream format, and saves ordinary seekable MP4 files. Store credentials and media outside this repository.

## Requirements

- Python 3.13 (verified), packages in `requirements.txt`
- No browser, Chromium or Playwright is required
- FFmpeg and FFprobe (Linux and macOS/Homebrew paths detected automatically)

### macOS

```bash
brew install ffmpeg
python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
```

### Debian / Ubuntu

```bash
sudo apt-get install -y ffmpeg python3-venv
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Environment overrides: FOD_FFMPEG_BIN and FOD_FFPROBE_BIN. No browser executable is needed.

## Browser-free HTTP mode

The CLI no longer imports Playwright or needs Chromium. It uses the account cookies in the user-provided Netscape cookie file to initialize an ordinary HTTPS session, fetch the series metadata, and obtain playback information. When the playback API provides a vtt_url field, the text subtitles are processed automatically as before.

CT104 verified: requests-only series discovery for 01bl and 4534, followed by a full 15-second episode workflow producing H.264 video, AAC audio, and a Japanese mov_text subtitle track in 2.46 seconds. No browser was launched in the revised workflow.

## Jellyfin TV-show layout

The `--output` argument specifies the Jellyfin **Shows library root directory**, not the name of an individual MP4 file. Default: `./Shows`.

```text
Shows/
└── リーガルハイ (2013)/
    ├── Season 01/
    │   ├── リーガルハイ S01E01 - 完全復活・古美門研介！….mp4
    │   └── リーガルハイ S01E02 - 逆ギレ天才起業家～….mp4
    └── series_results.json
```

- The series folder uses `Series Name (Year)`; the year is inferred from FOD when available, or overridden with `--year 2013`.
- Each episode is named `Series Name S01E01 - Episode Title.mp4` inside `Season 01`. Restricted filename characters are removed and long names are truncated to filesystem-safe lengths.
- The season defaults to `1`. Use `--season 2` if the FOD series corresponds to season 2 of the show in Jellyfin. The service's series ID is **not** necessarily the Jellyfin season number.
- Specials can be placed under `Season 00` with `--season 0`.
- Existing media files are not automatically migrated or renamed.

### Download one series

```bash
python fod_demo.py \
  --cookie /path/to/cookie.txt \
  --wvd /path/to/device.wvd \
  --url 'https://fod.fujitv.co.jp/title/4534/' \
  --season 2 \
  --output ./Shows
```

### Download one episode

```bash
python fod_demo.py \
  --cookie /path/to/cookie.txt \
  --wvd /path/to/device.wvd \
  --url 'https://fod.fujitv.co.jp/title/4534/4534110002/' \
  --season 2 \
  --output ./Shows
```

Even with a single episode URL, the script identifies the series, year and episode title to place the result in Jellyfin folders. For backward compatibility, if you specify `--output demo.mp4`, the parent folder is used as the Shows library root; the name `demo.mp4` is ignored.

### List episodes without downloading

```bash
python fod_demo.py \
  --cookie /path/to/cookie.txt \
  --wvd /path/to/device.wvd \
  --url 'https://fod.fujitv.co.jp/title/4534/' \
  --list-only
```

Other options: `--episodes 1,3-5` selects a subset of series episodes; `--seconds 15` limits the selected duration per episode (omitting it means full episodes); `--overwrite` replaces existing validated MP4 files. Successfully saved episode files are skipped on subsequent series runs.

`--cookie`, `--wvd` and `--url` remain required arguments. Store the Netscape-format cookie file and device WVD outside the repository. Neither is provided here. Only process media you are authorized to access.

## Automatically included subtitle tracks

The script checks for accessible **independent text subtitle tracks** in the HLS or MPEG-DASH manifest and separately requested WebVTT resources loaded by the browser player. On supported streams it downloads and converts the timed captions to SRT in a temporary directory and muxes them into the MP4 as **switchable `mov_text`** subtitle streams, tagged with their language. This is not a video burn-in; video and audio are copied without re-encoding.

- HLS: `#EXT-X-MEDIA:TYPE=SUBTITLES` with WebVTT media playlists or directly referenced WebVTT/SRT resources (including segmented WebVTT).
- DASH: text subtitle adaptations with directly accessible WebVTT, SRT or basic TTML files.
- Missing subtitles: ordinary MP4 output remains unchanged.
- Advertised subtitles which cannot be downloaded/parsed: the program reports the problem rather than silently reporting a subtitle-free file as successful.
- For troubleshooting, `--no-subtitles` explicitly bypasses subtitle extraction.
- Saved episode `.json` files list embedded subtitle languages and cue counts. If you have an older output without subtitle metadata, re-running the command will inspect subtitles again. `--overwrite` forces a new attempt.

Example:

```bash
python fod_demo.py \
  --cookie /path/to/cookie.txt \
  --wvd /path/to/device.wvd \
  --url 'https://fod.fujitv.co.jp/title/01bl/01bl110030/' \
  --output ./Shows
```

**Limitations:** WebVTT or TTML text tracks are distinct from closed captions stored inside video frames, image-based captions, encrypted subtitle representations, or fragmented DASH `wvtt` / `stpp` assets. These other formats are not automatically extractable by the current text-track implementation. Some FOD titles may have permanently burned-in subtitles or a separate in-player Japanese `字幕ガイド (CC)` switch instead of a downloadable text track. For episode 01bl110030, a real Japanese WebVTT track (712 total cues) was found through the browser player and a 60-second sample with 4 switchable Japanese subtitle cues was automatically generated by the updated script. The player CC ON control was located but its actual activation remains unverified. See LIVE_TEST_01bl.md for details.

## Outputs and testing

- Episodes: standard MP4 under `Show (Year)/Season NN/` plus per-episode JSON report.
- Series: the same episode structure plus `series_results.json` in the show folder.
- Media is verified for video/audio tracks and MP4 structure before publication under the final name.
- Series page `title/4534` was verified to return ten episodes and year 2013.
- Jellyfin path/name generation, single-episode and series batch placement, resume/skip and overrides were tested without downloading protected media.
- Actual macOS Jellyfin library recognition is not yet confirmed.

Official Jellyfin TV-show naming guide: https://jellyfin.org/docs/general/server/media/shows/

Real-world verification of subtitle availability for episode 01bl110030 and corrected episode numbering: see [LIVE_TEST_01bl.md](LIVE_TEST_01bl.md).
