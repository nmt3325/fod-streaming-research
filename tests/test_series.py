"""Real-page findings reproduced with synthetic episode listings and reports."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fod_demo as m


class SeriesTests(unittest.TestCase):
    def test_target_show_promotional_link_does_not_shift_episode_number(self):
        root = "https://fod.fujitv.co.jp/title/01bl/"
        links = [
            {"href":"/title/01bl/01bl110032/","title":"新着エピソード 第3話 怒り 44分"},
            {"href":"/title/01bl/01bl110030/","title":"続きを見る"},
            {"href":"/title/01bl/01bl110001/","title":"＜インタビュー動画＞スペシャル 1分"},
            {"href":"/title/01bl/01bl110030/","title":"無料 第1話 箱の中の娘 44分"},
            {"href":"/title/01bl/01bl110031/","title":"無料新着エピソード 第2話 17区 44分"},
            {"href":"/title/01bl/01bl110032/","title":"第3話 怒り 44分"},
        ]
        result = m.select_numbered_episodes(links, "01bl", root)
        self.assertEqual([(x["episode_number"],x["episode_id"]) for x in result],
                         [(1,"01bl110030"),(2,"01bl110031"),(3,"01bl110032")])
        expected = m.jellyfin_paths(
            Path("/tmp/Shows"),"ポリティカルパン",2026,1,
            result[0]["episode_number"],result[0]["title"])
        self.assertEqual(expected.name,"ポリティカルパン S01E01 - 箱の中の娘.mp4")

    def test_resume_does_not_confuse_short_sample_and_full_episode(self):
        uri="https://fod.fujitv.co.jp/title/01bl/01bl110030/"
        with tempfile.TemporaryDirectory() as dir:
            path=Path(dir)/"episode.mp4"
            path.write_bytes(b"fake -- media validation mocked separately")
            result={
                "status":"success","requested_seconds":60.,
                "video_url_path":"/title/01bl/01bl110030/",
                "subtitle_checked":True,"subtitle_tracks":[]}
            path.with_suffix(".json").write_text(json.dumps(result))
            short=SimpleNamespace(seconds=60.,no_subtitles=False)
            full=SimpleNamespace(seconds=None,no_subtitles=False)
            with patch.object(m,"valid_existing_mp4",return_value=True):
                self.assertTrue(m.completed_episode(path,short,uri))
                self.assertFalse(m.completed_episode(path,full,uri))
                self.assertFalse(m.completed_episode(path,short,uri.replace("110030","110031")))
                result["subtitle_checked"]=False
                path.with_suffix(".json").write_text(json.dumps(result))
                self.assertFalse(m.completed_episode(path,short,uri))

    def test_caption_free_media_is_not_marked_as_subtitled(self):
        self.assertEqual(m.subtitle_language("ja-JP"),"jpn")


if __name__ == "__main__":
    unittest.main()
