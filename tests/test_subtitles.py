"""Synthetic-only subtitle tests. No account data, network or protected media."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import subtitle_utils as subs
import fod_demo as demo


class SubtitleTests(unittest.TestCase):
    def test_hls_timed_subtitles(self):
        master=('#EXTM3U\n#EXT-X-MEDIA:TYPE=SUBTITLES,NAME="日本語",'
                'LANGUAGE="ja",URI="sub.m3u8"\n')
        tracks=subs.hls_tracks(master, "https://example.test/v/master.m3u8")
        self.assertEqual(len(tracks), 1)
        texts={
            "https://example.test/v/sub.m3u8":
                "#EXTM3U\n#EXTINF:5.0,\na.vtt\n#EXTINF:5.0,\nb.vtt",
            "https://example.test/v/a.vtt":
                "WEBVTT\nX-TIMESTAMP-MAP=MPEGTS:900000,LOCAL:00:00:00.000\n\n"
                "00:00:01.000 --> 00:00:03.000\nこんにちは\n",
            "https://example.test/v/b.vtt":
                "WEBVTT\nX-TIMESTAMP-MAP=LOCAL:00:00:00.000,MPEGTS:1350000\n\n"
                "00:00:01.000 --> 00:00:03.000\nさようなら\n",
        }
        with tempfile.TemporaryDirectory() as directory:
            path,count=subs.materialize(tracks[0],
                 lambda u: texts[u].encode(), directory)
            self.assertEqual(count,2)
            self.assertIn("00:00:06,000 --> 00:00:08,000",path.read_text())

    def test_dash_and_ttml(self):
        root=ET.fromstring('<MPD><Period><AdaptationSet mimeType="text/vtt" lang="ja">'
            '<Representation><BaseURL>ja.vtt</BaseURL></Representation>'
            '</AdaptationSet></Period></MPD>')
        tracks=subs.dash_tracks(root,"https://example.test/video/manifest.mpd")
        self.assertEqual(tracks[0].url,"https://example.test/video/ja.vtt")
        t='<tt xmlns="http://www.w3.org/ns/ttml"><body><div><p begin="00:00:01.000" end="00:00:02.000">字幕</p></div></body></tt>'
        self.assertEqual(subs.ttml_cues(t),[(1.,2.,'字幕')])

    def test_absent_subtitles(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(demo,"get",return_value=b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=100\nvideo.m3u8"):
                tracks,checked=demo.available_subtitles(
                    None,"hls","https://example.test/stream.m3u8",
                    None,Path(directory),None,lambda x:None)
            self.assertEqual(tracks,[])
            self.assertTrue(checked)

    def test_clip_and_merge(self):
        with tempfile.TemporaryDirectory() as directory:
            f=Path(directory)/"caption.srt"
            count=subs.make_srt([(1,3,"日本語"),(6,10,"次の字幕")],f,8)
            self.assertEqual(count,2)
            self.assertIn("00:00:06,000 --> 00:00:08,000",f.read_text())


if __name__=="__main__":
    unittest.main()
