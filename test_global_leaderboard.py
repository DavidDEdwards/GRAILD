import ast
import base64
import json
import sqlite3
import urllib.error
import unittest
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

# Exercise bridge methods without starting pygame, a webview, or real account storage.
source = ast.parse(Path('web_app.py').read_text(encoding='utf-8'))
cls = next(n for n in source.body if isinstance(n, ast.ClassDef) and n.name == 'JuiceSpotApp')
methods = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in ('save_global_identity', 'get_global_leaderboard')]
scope = dict(base64=base64, json=json, sqlite3=sqlite3, urllib=__import__('urllib'))
exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ClassDef(name='Bridge', bases=[], keywords=[], body=methods, decorator_list=[])], type_ignores=[])), 'web_app.py', 'exec'), scope)
Bridge = scope['Bridge']

class LeaderboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / 'accounts.sqlite3')
        self.app = Bridge()
        self.app.current_user_id = 'player'
        @contextmanager
        def connection():
            db = sqlite3.connect(self.path)
            db.row_factory = sqlite3.Row
            try:
                yield db
                db.commit()
            finally:
                db.close()
        self.app.account_connection = connection
        self.app.get_discord_broker_url = lambda: 'https://example.test'
        self.app.protect_session_data = lambda data, decrypt=False: data[::-1]
        with connection() as db:
            db.executescript("CREATE TABLE app_meta (key TEXT PRIMARY KEY, value TEXT); CREATE TABLE accounts (user_id TEXT, display_name TEXT, total_points INTEGER, total_correct INTEGER, total_wrong INTEGER); INSERT INTO accounts VALUES ('player', 'Player', 120, 3, 2);")
        self.calls = []
        def request(url, payload=None, headers=None):
            self.calls.append((url, payload, headers))
            return {'entries': [{'rank': 1, 'display_name': 'Player', 'points': 120}]}
        self.app.oauth_json_request = request

    def test_verified_score_sync_and_private_credentials(self):
        self.app.save_global_identity('player', {'global_token': 'secret'})
        result = self.app.get_global_leaderboard()
        self.assertTrue(result['synced'])
        self.assertEqual(self.calls[0][1]['points'], 120)
        self.assertEqual(self.calls[0][2]['Authorization'], 'Bearer secret')
        self.assertNotIn('secret', json.dumps(result))

    def test_guest_only_reads_public_board(self):
        self.app.current_user_id = None
        self.assertTrue(self.app.get_global_leaderboard()['success'])
        self.assertEqual(len(self.calls), 1)
        self.assertIsNone(self.calls[0][1])

    def test_expired_token_still_loads_board(self):
        self.app.save_global_identity('player', {'global_token': 'expired'})
        original = self.app.oauth_json_request
        def request(url, payload=None, headers=None):
            if payload:
                raise urllib.error.HTTPError(url, 401, 'expired', {}, None)
            return original(url)
        self.app.oauth_json_request = request
        result = self.app.get_global_leaderboard()
        self.assertTrue(result['success'])
        self.assertFalse(result['synced'])
        self.assertIn('Reconnect', result['message'])

    def test_other_account_cannot_use_saved_token(self):
        self.app.save_global_identity('other-player', {'global_token': 'secret'})
        self.assertFalse(self.app.get_global_leaderboard()['synced'])
        self.assertEqual(len(self.calls), 1)

    def test_damaged_credential_does_not_hide_public_board(self):
        with self.app.account_connection() as db:
            db.execute("INSERT INTO app_meta VALUES (?, ?)",
                       ("global_identity:player", '{"broker":"https://example.test"}'))
        result = self.app.get_global_leaderboard()
        self.assertTrue(result['success'])
        self.assertFalse(result['synced'])
        self.assertIn('Reconnect', result['message'])

    def test_old_server_reports_missing_deployment(self):
        def request(*args, **kwargs):
            raise urllib.error.HTTPError(args[0], 404, 'not found', {}, None)
        self.app.oauth_json_request = request
        result = self.app.get_global_leaderboard()
        self.assertFalse(result['success'])
        self.assertIn('deploy', result['message'])

    def test_service_failure_is_recoverable(self):
        self.app.oauth_json_request = lambda *args, **kwargs: (_ for _ in ()).throw(OSError('offline'))
        self.assertFalse(self.app.get_global_leaderboard()['success'])

if __name__ == '__main__':
    unittest.main()
