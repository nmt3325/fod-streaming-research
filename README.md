# FOD Streaming Research Demo

Private command-line demo for studying streaming delivery and playback compatibility. The script accepts user-supplied authentication files, automatically detects the stream format, and saves ordinary seekable MP4 files. Store credentials and media outside this repository.

## Requirements

- Python 3.13 (verified), packages in `requirements.txt`
- Chromium / Google Chrome or Playwright-managed Chromium
- FFmpeg and FFprobe (Linux and macOS/Homebrew paths detected automatically)

### macOS

```bash
brew install ffmpeg
python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
python -m playwright install chromium
```

### Debian / Ubuntu

```bash
sudo apt-get install -y chromium ffmpeg python3-venv
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Environment variables: `CHROME_PATH`, `FOD_FFMPEG_BIN`, and `FOD_FFPROBE_BIN` override automatic executable discovery.

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

## Outputs and testing

- Episodes: standard MP4 under `Show (Year)/Season NN/` plus per-episode JSON report.
- Series: the same episode structure plus `series_results.json` in the show folder.
- Media is verified for video/audio tracks and MP4 structure before publication under the final name.
- Series page `title/4534` was verified to return ten episodes and year 2013.
- Jellyfin path/name generation, single-episode and series batch placement, resume/skip and overrides were tested without downloading protected media.
- Actual macOS Jellyfin library recognition is not yet confirmed.

Official Jellyfin TV-show naming guide: https://jellyfin.org/docs/general/server/media/shows/
