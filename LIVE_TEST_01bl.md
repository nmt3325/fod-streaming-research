# FOD episode 01bl110030 — live subtitle verification

Test date: 2026-10-17. Host: CT104. Target: FOD episode 01bl110030 (ポリティカルパン, 第1話 箱の中の娘).

## Results: player-side Japanese subtitle capture and embedding succeeded

- FOD's HLS master playlist did not declare EXT-X-MEDIA subtitle tracks. The original manifest-only discovery therefore saved a subtitle-free 60-second sample.
- Browser playback requested a separate Japanese WebVTT file named 01bl11003037ow_ja.vtt (HTTP 200). The WebVTT contained 712 timed cues, beginning near 00:14 and ending near 44:27.
- The browser's video text track was present with kind=captions, label=Japanese, language=ja, and mode=disabled. The player contained the 字幕ガイド（CC） ON / OFF setting, but toggling ON was blocked by the remote tool safety check. The UI switch is not claimed as tested.
- The script was updated to observe caption files loaded by the browser player, as well as subtitle declarations in HLS/DASH manifests.
- Real end-to-end run using the updated script with --seconds 60 and no manually supplied subtitle URL detected one WebVTT subtitle and embedded 4 caption cues. Runtime: 9.59 seconds.
- FFprobe verified H.264 video + AAC audio + mov_text Japanese subtitle (language jpn), with duration 60.027 seconds and size 22,827,733 bytes.
- Re-extracting the subtitle track with FFmpeg succeeded; subtitle text was nonempty.
- Local verified output: /root/fod/demo15/subtitle_auto_live_test/ポリティカルパン (2026)/Season 01/ポリティカルパン S01E01 - 箱の中の娘.mp4

## Other fixes verified

- Numbered episode cards are preferred over unnumbered hero links and interview extras. The episode is correctly identified as S01E01, not S01E02.
- Saved short demonstration clips are not skipped as though they are full episodes.
- Eight offline unit tests passed, including a player-side WebVTT case without HLS subtitle declarations.

## Limitations

- The actual CC ON interface action was not successfully performed in the remote browser; the resulting on-screen rendering of subtitles remains unconfirmed.
- The complete episode with captions has not been downloaded by the revised end-to-end workflow. The test above validates a 60-second sample.
- This test does not establish that every other FOD series publishes the same sort of WebVTT caption track.
