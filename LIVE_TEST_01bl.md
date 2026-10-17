# FOD episode 01bl110030 — actual subtitle test

Test date: 2026-10-17. Environment: CT104.

## Observed result

- The target episode was successfully acquired as a 60-second demonstration sample; execution time was 10.19 seconds.
- FFprobe result: MP4 duration 60.027 seconds, size 22,827,069 bytes, H.264 video and AAC audio.
- The authenticated HLS master playlist had an EXT-X-STREAM-INF video variant, but no EXT-X-MEDIA entries, including no TYPE=SUBTITLES or TYPE=CLOSED-CAPTIONS declarations.
- The exported MP4 contained exactly video and audio streams; no subtitle stream. The video stream reported closed_captions=0. The inspected early video frames exposed no in-band caption side data.
- Accordingly, no real captions were embedded for this title in the tested stream. This is an observed non-detection, not proof that the program has no alternate player-only captions or a separately captioned edition.
- The synthetic WebVTT-to-MP4 soft-subtitle test passed, with an independently selectable Japanese mov_text subtitle stream.

## Other issues found and fixed

- Original episode discovery counted an interview clip as episode one and selected a Continue watching tile as an episode title. The target episode was incorrectly named S01E02 - 続きを見る.
- Episode lists now use an explicit 第N話 marker and ignore promotional / unnumbered links. The real series page correctly lists 3 numbered episodes.
- Correct filename: ポリティカルパン S01E01 - 箱の中の娘.mp4.
- Resume decisions now compare recorded requested_seconds, so a 60-second test is never mistaken for the full episode.

## Verification limits

The real Japanese subtitle extraction/embedding success case cannot be claimed for this title because no supported text subtitle resource was detected. FOD's optional separate 字幕ガイド(CC) player setting was not conclusively verified.
