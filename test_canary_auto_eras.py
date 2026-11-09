from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock

from canary_client import CanaryError
from canary_integration import CanaryIntegration, automatic_era, build_title_index
from web_app import JuiceSpotApp


class AutomaticEraTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.client = Mock()
        self.client.cached_recording_eras.return_value = []
        self.songs = [
            {"id": "rental", "title": "Rental", "era": "DRFL", "tracker": {"alt_names": ["Rent"]}},
            {"id": "rental-master", "title": "Rental (Master)", "era": "DRFL", "tracker": {"alt_names": ["Rental"]}},
            {"id": "session", "title": "Rental (Session Edit)", "era": "WOD"},
            {"id": "legends", "title": "Legends (Sessions)", "era": "WOD"},
            {"id": "conflict1", "title": "Shared Name", "era": "WOD"},
            {"id": "conflict2", "title": "Shared Name", "era": "DRFL"},
        ]
        self.client.get_song_index.return_value = {"songs": self.songs}
        self.service = CanaryIntegration(self.folder / "metadata", self.client)

    def files(self, *names):
        for name in names:
            (self.folder / name).write_bytes(b"local audio")
        return list(names)

    def scan(self, files, force=False):
        self.service.start_era_scan(self.folder, files, force=force)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            status = self.service.era_scan_status(self.folder)
            if status["status"] not in ("queued", "running"):
                return status
            time.sleep(0.01)
        self.fail("Era scan did not finish")

    def test_exact_title_alias_and_version_preservation(self):
        index = build_title_index(self.songs)
        self.assertEqual(automatic_era("Juice WRLD - Rental.mp3", index)["era"], "DRFL")
        self.assertEqual(automatic_era("Rent.flac", index)["era"], "DRFL")
        self.assertEqual(automatic_era("Legends (Session Edit).mp3", index)["era"], "WOD")
        self.assertEqual(automatic_era("Rental (Session Edit).mp3", index)["era"], "WOD")
        self.assertEqual(automatic_era("Rental (Alt Version).mp3", index)["era"], "")
        self.assertEqual(automatic_era("Rental [WOD era].mp3", index)["era"], "")
        self.assertEqual(automatic_era("Shared Name.mp3", index)["status"], "needs_review")

    def test_numeric_song_titles_are_not_treated_as_track_numbers(self):
        index = build_title_index(self.songs + [{"id": "ten", "title": "10 Feet", "era": "DRFL"},
                                              {"id": "feet", "title": "Feet", "era": "WOD"}])
        self.assertEqual(automatic_era("10 Feet.mp3", index)["era"], "DRFL")
        self.assertEqual(automatic_era("Feet.mp3", index)["era"], "WOD")
        self.assertEqual(automatic_era("01 - Rental.mp3", index)["era"], "DRFL")

    def test_auto_check_does_not_link_recordings_and_drives_era_filter(self):
        files = self.files("Rental.mp3", "Shared Name.mp3", "Unknown.mp3")
        status = self.scan(files)
        self.assertEqual(status["status"], "complete")
        self.assertEqual(status["resolved"], 1)
        self.assertEqual(status["review"], 2)
        self.assertEqual(self.service.library_matches(self.folder, files), {})
        app = JuiceSpotApp.__new__(JuiceSpotApp)
        app._canary = self.service
        app.tracks = files
        app.music_folder = str(self.folder)
        app.recording_era = "DRFL"
        self.assertEqual(app.get_eligible_tracks(), ["Rental.mp3"])
        self.assertEqual(app.get_recording_eras(), ["DRFL"])

    def test_unchanged_files_use_saved_checks_and_replacements_are_rechecked(self):
        files = self.files("Rental.mp3")
        self.scan(files)
        self.scan(files)
        self.assertEqual(self.client.get_song_index.call_count, 1)
        (self.folder / files[0]).write_bytes(b"changed audio file")
        self.assertEqual(self.service.library_era_checks(self.folder, files), {})
        self.scan(files)
        self.assertEqual(self.client.get_song_index.call_count, 2)

    def test_manual_confirmation_has_priority_and_offline_does_not_erase_era(self):
        files = self.files("Rental.mp3")
        self.scan(files)
        self.client.get_song_index.side_effect = CanaryError("offline")
        self.assertEqual(self.scan(files, force=True)["status"], "failed")
        self.assertEqual(self.service.library_era_checks(self.folder, files)["Rental.mp3"]["era"], "DRFL")
        self.client.get_song.return_value = {"id": "manual", "title": "Different recording", "era": "WOD"}
        self.client.get_cover.return_value = {"image": ""}
        self.service.confirm(self.folder / "Rental.mp3", "manual")
        self.assertEqual(self.scan(files, force=True)["status"], "complete")
        self.assertEqual(self.service.library_era_checks(self.folder, files)["Rental.mp3"]["era"], "WOD")


if __name__ == "__main__":
    unittest.main()
