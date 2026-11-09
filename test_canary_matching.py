from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock

from canary_integration import CanaryIntegration, rank_candidates, normalized_title


class CanaryMatchingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.song = self.folder / "Rental (Session Edit).mp3"
        self.song.write_bytes(b"local audio")
        self.client = Mock()
        self.client.cached_recording_eras.return_value = []
        self.service = CanaryIntegration(self.folder / "metadata", self.client)
        self.records = [{"id": "rental", "title": "Rental", "era": "DRFL", "category": "Songs"},
                        {"id": "rental-session", "title": "Rental (Session Edit)", "era": "DRFL", "category": "Sessions"},
                        {"id": "alias", "title": "Other Title", "tracker": {"alt_names": ["Rental (Session Edit)"]}}]
        self.client.search_songs.return_value = {"songs": self.records}
        self.client.get_song.return_value = self.records[1]
        self.client.get_cover.return_value = {"image": "data:image/png;base64,aW1hZ2U="}

    def test_versions_stay_distinct_and_aliases_rank(self):
        ranked = rank_candidates(self.song.name, self.records)
        self.assertEqual(ranked[0]["id"], "rental-session")
        self.assertEqual(ranked[1]["id"], "alias")
        self.assertNotEqual(normalized_title("Rental"), normalized_title("Rental (Session Edit)"))

    def test_search_never_automatically_saves_a_match(self):
        result = self.service.local_info(self.song)
        self.assertFalse(result["confirmed"])
        self.assertIsNone(self.service.local_match(self.song))
        self.assertEqual(self.client.search_songs.call_args.args[0], "Rental")

    def test_confirmation_is_per_file_and_invalidated_by_replacement(self):
        self.service.confirm(self.song, "rental-session")
        self.assertEqual(self.service.local_match(self.song)["song"]["id"], "rental-session")
        other = self.folder / "Rental.mp3"
        other.write_bytes(b"another recording")
        self.assertIsNone(self.service.local_match(other))
        self.song.write_bytes(b"replacement recording")
        self.assertIsNone(self.service.local_match(self.song))

    def test_era_filter_uses_only_confirmed_local_files(self):
        from web_app import JuiceSpotApp
        app = JuiceSpotApp.__new__(JuiceSpotApp)
        app._canary = self.service
        app.account_db_path = str(self.folder / "accounts.sqlite3")
        app.initialize_account_store()
        with app.account_connection() as db:
            db.execute("INSERT INTO accounts (user_id, username, username_key, password_salt, password_hash, password_iterations, display_name, avatar, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", ("player", "player", "player", b"s", b"h", 1, "Player", "*", "2026-10-30"))
        app.music_folder = str(self.folder)
        other = self.folder / "Other.mp3"
        other.write_bytes(b"another local song")
        app.tracks = [self.song.name, other.name]
        app.current_user_id = "player"
        app.current_track = other.name
        app.game_mode = "classic"
        app.current_difficulty = "Easy"
        app.recording_era = ""
        app.stop_audio = Mock()
        app.state = lambda: {"eligible": app.get_eligible_tracks()}
        self.service.confirm(self.song, "rental-session")
        self.assertFalse(app.set_recording_era("UNKNOWN")["success"])
        self.assertTrue(app.set_recording_era("DRFL")["success"])
        self.assertEqual(app.get_eligible_tracks(), [self.song.name])
        self.assertEqual(app.current_track, self.song.name)
        app.recording_era = ""
        app.load_game_preferences()
        self.assertEqual(app.recording_era, "DRFL")
        with app.account_connection() as db:
            db.execute("INSERT INTO accounts (user_id, username, username_key, password_salt, password_hash, password_iterations, display_name, avatar, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", ("other", "other", "other", b"s", b"h", 1, "Other", "*", "2026-10-30"))
        app.current_user_id = "other"
        app.load_game_preferences()
        self.assertEqual(app.recording_era, "")
        app.current_user_id = "player"
        app.load_game_preferences()
        self.assertEqual(app.recording_era, "DRFL")
        self.assertFalse(app.reroll_song()["changed"])
        self.assertTrue(app.set_library_source("canary")["success"])
        self.assertEqual(app.get_eligible_tracks(), [])
        app.library_source = "local"
        app.load_game_preferences()
        self.assertEqual(app.library_source, "canary")
        self.assertEqual(app.recording_era, "DRFL")
        self.assertTrue(app.set_library_source("local")["success"])
        self.service.forget(self.song)
        app.next_round()
        self.assertIsNone(app.current_track)
        self.assertEqual(app.get_eligible_tracks(), [])
        app.set_recording_era("")
        self.assertEqual(len(app.get_eligible_tracks()), 2)

    def test_era_never_comes_from_local_filename(self):
        from web_app import JuiceSpotApp
        filename = self.folder / "Rental [WOD era].mp3"
        filename.write_bytes(b"local audio")
        self.service.confirm(filename, "rental-session")
        app = JuiceSpotApp.__new__(JuiceSpotApp)
        app._canary = self.service
        app.music_folder = str(self.folder)
        app.tracks = [filename.name]
        app.recording_era = "WOD"
        self.assertEqual(app.get_recording_eras(), ["DRFL"])
        self.assertEqual(app.get_eligible_tracks(), [])
        app.recording_era = "DRFL"
        self.assertEqual(app.get_eligible_tracks(), [filename.name])

    def test_network_failure_keeps_confirmed_metadata(self):
        from canary_client import CanaryError
        self.service.confirm(self.song, "rental-session")
        self.client.get_song.side_effect = CanaryError("offline")
        saved = self.service.local_info(self.song)
        self.assertTrue(saved["confirmed"])
        self.assertEqual(saved["song"]["id"], "rental-session")
        self.assertIn("offline", saved["notice"])

    def test_background_job_returns_immediately(self):
        def delayed(*args, **kwargs):
            time.sleep(0.2)
            return {"songs": []}
        self.client.search_songs.side_effect = delayed
        start = time.monotonic()
        job = self.service.start("search", query="Rental")
        self.assertLess(time.monotonic() - start, 0.1)
        while self.service.poll(job["job_id"])["status"] == "running":
            time.sleep(0.02)
        self.assertEqual(self.service.poll(job["job_id"])["status"], "complete")


if __name__ == "__main__":
    unittest.main()
