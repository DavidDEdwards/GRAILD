import tempfile
import unittest
from pathlib import Path

from web_app import CHALLENGE_MODES, JuiceSpotApp


class ChallengeBestTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.app = JuiceSpotApp.__new__(JuiceSpotApp)
        self.app.account_db_path = str(Path(temporary.name) / "accounts.sqlite3")
        self.app.initialize_account_store()
        self.app.current_user_id = "a"
        for user in ("a", "b"):
            with self.app.account_connection() as db:
                db.execute("INSERT INTO accounts (user_id, username, username_key, password_salt, password_hash, password_iterations, display_name, avatar, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (user, user, user, b"salt", b"hash", 1, user, "*", "2026-11-07T00:00:00+00:00"))

    def test_first_run_is_a_new_best_and_counts_one_run(self):
        result = self.app.save_challenge_result("sudden_death", 4, 4)
        self.assertTrue(result["success"])
        self.assertTrue(result["new_best"])
        self.assertEqual(result["bests"]["sudden_death"], {"best_score": 4, "best_songs": 4, "runs": 1})

    def test_worse_run_keeps_best_but_still_counts(self):
        self.app.save_challenge_result("time_attack", 120, 5)
        result = self.app.save_challenge_result("time_attack", 80, 7)
        self.assertFalse(result["new_best"])
        self.assertEqual(result["bests"]["time_attack"], {"best_score": 120, "best_songs": 7, "runs": 2})
        self.assertTrue(self.app.save_challenge_result("time_attack", 130, 5)["new_best"])

    def test_zero_score_first_run_is_not_a_best(self):
        self.assertFalse(self.app.save_challenge_result("three_lives", 0, 0)["new_best"])

    def test_bests_are_per_player(self):
        self.app.save_challenge_result("sprint", 300, 10)
        self.app.current_user_id = "b"
        self.assertEqual(self.app.get_challenge_bests(), {})

    def test_bad_input_is_rejected_and_nothing_is_saved(self):
        for args in (("classic", 1, 1), ("sprint", "lots", 1), ("sprint", -1, 1), ("sprint", 5, 99999), ("sprint", None, 1)):
            self.assertFalse(self.app.save_challenge_result(*args)["success"], args)
        self.assertEqual(self.app.get_challenge_bests(), {})

    def test_signed_out_players_cannot_save(self):
        self.app.current_user_id = None
        self.assertFalse(self.app.save_challenge_result("sprint", 10, 1)["success"])
        self.assertEqual(self.app.get_challenge_bests(), {})

    def test_known_modes(self):
        self.assertEqual(set(CHALLENGE_MODES), {"sudden_death", "three_lives", "time_attack", "sprint"})


if __name__ == "__main__":
    unittest.main()
