import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock

import requests
from canary_client import CanaryClient, CanaryError


class CanaryClientTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.session = Mock()
        self.client = CanaryClient(Path(temporary.name) / "cache.sqlite3", session=self.session, interval=0)

    def response(self, data, status=200, headers=None):
        response = Mock(status_code=status, headers=headers or {})
        response.json.return_value = data
        self.session.get.return_value = response
        return response

    def test_search_uses_documented_filters_and_caches(self):
        self.response({"songs": [{"id": "rental", "title": "Rental", "audio_url": "forbidden"}], "total": 1})
        first = self.client.search_songs("Rental", era="DRFL", category="Songs")
        params = self.session.get.call_args.kwargs["params"]
        self.assertEqual(params["q"], "Rental")
        self.assertEqual(params["era"], "DRFL")
        self.assertEqual(params["category"], "Songs")
        self.assertNotIn("audio_url", first["songs"][0])
        self.assertTrue(self.client.search_songs("Rental", era="DRFL", category="Songs")["_cached"])
        self.assertEqual(self.session.get.call_count, 1)

    def test_http_errors_are_friendly(self):
        for status in (400, 404, 429, 503):
            with self.subTest(status=status):
                self.client.cooldown = 0
                self.response({}, status=status)
                with self.assertRaises(CanaryError) as result:
                    self.client.get_song("song" + str(status))
                self.assertEqual(result.exception.status, status)

    def test_offline_expired_cache_is_available(self):
        self.response({"songs": [], "total": 0})
        self.client.search_songs("saved")
        with self.client._db() as db:
            db.execute("UPDATE api_cache SET saved = 0")
        self.session.get.side_effect = requests.ConnectionError("offline")
        self.assertTrue(self.client.search_songs("saved")["_stale"])

    def test_timeout_without_cache_and_rate_limit_cooldown(self):
        self.session.get.side_effect = requests.Timeout()
        with self.assertRaisesRegex(CanaryError, "timed out"):
            self.client.get_catalog()
        self.session.get.side_effect = None
        self.response({}, 429, {"Retry-After": "30"})
        with self.assertRaises(CanaryError):
            self.client.get_catalog()
        count = self.session.get.call_count
        with self.assertRaises(CanaryError):
            self.client.get_catalog()
        self.assertEqual(self.session.get.call_count, count)

    def test_random_song_uses_documented_metadata_pages_and_era(self):
        from unittest.mock import patch
        self.response({"songs": [{"id": "rental", "title": "Rental", "era": "DRFL", "page_url": "https://canary.best/song/rental"}], "total": 1})
        with patch("canary_client.random.randrange", return_value=0):
            result = self.client.random_song("DRFL")
        self.assertEqual(result["song"]["id"], "rental")
        self.assertEqual(self.session.get.call_args.kwargs["params"]["era"], "DRFL")
        self.assertTrue(self.session.get.call_args.args[0].endswith("/songs"))
        self.response({"songs": [], "total": 0})
        with self.assertRaisesRegex(CanaryError, "no songs"):
            self.client.random_song("EMPTY")

    def test_eras_are_derived_from_canary_metadata_and_cached(self):
        self.response({"songs": [{"id": "a", "title": "Title containing WOD", "era": "DRFL"},
                                  {"id": "b", "title": "Another", "era": "JUTE"}], "total": 2})
        self.assertEqual(self.client.get_recording_eras()["eras"], ["DRFL", "JUTE"])
        self.assertEqual(self.client.cached_recording_eras(), ["DRFL", "JUTE"])
        self.assertTrue(self.client.get_recording_eras()["_cached"])
        self.assertEqual(self.session.get.call_count, 1)

    def test_detail_and_cover_routes_are_metadata_only(self):
        self.response({"id": "rental", "title": "Rental", "tracker": {"alt_names": ["Alias"]}})
        self.assertEqual(self.client.get_song("rental")["tracker"]["alt_names"], ["Alias"])
        response = self.response({}, headers={"Content-Type": "image/png"})
        response.iter_content.return_value = [b"image"]
        self.assertTrue(self.client.get_cover("rental")["image"].startswith("data:image/png"))
        self.assertTrue(self.session.get.call_args.args[0].endswith("/songs/rental/cover"))
        with self.assertRaises(CanaryError):
            self.client.get_song("../private/audio")


if __name__ == "__main__":
    unittest.main()
