"""Regression tests for FOD metadata handlers using no browser or live API."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import fod_demo as demo


class Response:
    def __init__(self,payload):
        self.payload=payload
    def raise_for_status(self):
        return None
    def json(self):
        return self.payload


class Session:
    def __init__(self,payload):
        self.payload=payload
        self.calls=[]
        self.closed=False
    def get(self,url,**kwargs):
        self.calls.append((url,kwargs))
        return Response(self.payload)
    def close(self):
        self.closed=True


class HttpOnlyTests(unittest.TestCase):
    def test_public_series_metadata_selects_normal_episodes(self):
        metadata={
            "detail":{"lu_title":"架空番組","period":"2026"},
            "episodes":[
                {"ep_id":"ep001","ep_title":"第1話 本編","disp_ep_no":"第1話",
                 "sort_number":10,"is_teaser":False},
                {"ep_id":"ep001cc","ep_title":"第1話 【解説放送版】本編",
                 "disp_ep_no":"第1話","sort_number":1010,"is_teaser":False},
                {"ep_id":"ep002","ep_title":"第2話 つづき","disp_ep_no":"第2話",
                 "sort_number":20,"is_teaser":False},
                {"ep_id":"int001","ep_title":"インタビュー","disp_ep_no":"",
                 "sort_number":999,"is_teaser":False}
            ]
        }
        session=Session(metadata)
        with patch.object(demo,"new_http_session",return_value=(session,{"UT":"dummy"})):
            name,episodes,year=demo.discover_series(
                "https://fod.fujitv.co.jp/title/TEST/",None,"TEST")
        self.assertEqual((name,year),("架空番組",2026))
        self.assertEqual([e["episode_id"] for e in episodes],["ep001","ep002"])
        self.assertTrue(session.closed)

    def test_player_caption_reference_is_extracted_from_api_metadata(self):
        sample={
            "url":"https://example.test/streams/master.m3u8?signature=not-a-real-key",
            "ticket":None,
            "vtt_url":"https://example.test/subtitles/ep_ja.vtt",
        }
        session=Session(sample)
        with patch.object(demo,"new_http_session",return_value=(session,{"uuid":"dummy"})):
            data=demo.authorized_manifest(
                "https://fod.fujitv.co.jp/title/ABCD/ABCD0001/",None)
        self.assertEqual(data["player_subtitles"],
                         ["https://example.test/subtitles/ep_ja.vtt"])
        self.assertEqual(data["ticket"],"")
        self.assertTrue(session.closed)

    def test_application_does_not_import_browser_modules(self):
        self.assertNotIn("playwright",sys.modules)


if __name__=="__main__":
    unittest.main()
