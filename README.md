# FOD Streaming Research Demo

Private repository for a command-line demonstration of FOD streaming compatibility and content-protection behavior. The script accepts user-supplied authentication files and a FOD page URL and selects the playback stream format automatically.

## Requirements

- Python 3.13 (the version used for verification)
- Chromium browser, available at `/usr/bin/chromium` by default
- FFmpeg and FFprobe, available at `/usr/bin/ffmpeg` and `/usr/bin/ffprobe`
- Packages in `requirements.txt`

### Setup (Debian/Ubuntu)

```bash
sudo apt-get install -y chromium ffmpeg python3-venv
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

The browser executable can be overridden with the `CHROME_PATH` environment variable; FFmpeg can be overridden with `FOD_FFMPEG_BIN`.

## Usage

### A single episode

```bash
.venv/bin/python fod_demo.py \
  --cookie /path/to/cookie.txt \
  --wvd /path/to/device.wvd \
  --url 'https://fod.fujitv.co.jp/title/4534/4534110002/' \
  --output episode.mp4
```

### List episodes from a series

```bash
.venv/bin/python fod_demo.py \
  --cookie /path/to/cookie.txt \
  --wvd /path/to/device.wvd \
  --url 'https://fod.fujitv.co.jp/title/4534/' \
  --list-only
```

### Series output

```bash
.venv/bin/python fod_demo.py \
  --cookie /path/to/cookie.txt \
  --wvd /path/to/device.wvd \
  --url 'https://fod.fujitv.co.jp/title/4534/' \
  --output ./series_4534/
```

The `--seconds N` flag limits each episode to N seconds. Without it, the entire episode is selected. Use `--episodes 1,3-5` to select episodes by position in the series listing, or `--overwrite` to replace a previously validated file. Existing valid MP4s are skipped by default when running on a series.

`--cookie` expects Netscape-format cookies; `--wvd` expects a WVD device file. **Neither file is included in this repository.**

## Outputs and testing

- Single episode: MP4 file and JSON result.
- Series: one MP4 per episode and a `series_results.json` progress report in the requested output directory.
- The code creates ordinary seekable MP4 files with both video and audio, then verifies the container before publishing the final output filename.

Tested on CT104 with Chromium 154, FFmpeg 7.1.5, and Python 3.13. Series page discovery was validated on `title/4534` (10 episodes). Single-episode full-length MP4 output was validated on episode `4534110002`. Series batch selection/resume logic was unit-tested; an end-to-end full-series acquisition has not been verified.

Store cookies, WVD files, output media and logs outside the repository directory. `.gitignore` additionally excludes common sensitive and generated file types.
