import base64
from contextlib import nullcontext
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import uuid

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from auto_update import UpdateManager, validate_asset_url
import graild_updater
from update_security import (UpdateError, SemVer, canonical, strict_json, verify_manifest,
                             sha256_file, atomic_json, update_root)


def signed_release(private, data=b"MZverified-build", version="0.8.1-beta.1", channel="beta"):
    now = datetime.now(timezone.utc)
    manifest = {"schema": 1, "app": "GRAILD", "repository": "example/graild", "channel": channel,
                "version": version, "tag": "v" + version, "asset": "GRAILD.exe", "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(), "issued_at": now.isoformat(),
                "expires_at": (now + timedelta(days=30)).isoformat(), "notes": "A signed beta update."}
    return resign(private, manifest)


def resign(private, manifest):
    return {"manifest": manifest, "key_id": "test", "signature": base64.b64encode(private.sign(canonical(manifest))).decode()}


def public_keys(private):
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return {"test": base64.b64encode(public).decode()}


class Response:
    def __init__(self, data, status=200, headers=None, chunks=None):
        self.data, self.status_code, self.headers = data, status, headers or {}
        self.chunks = chunks
        self.closed = False
    def iter_content(self, size):
        yield from (self.chunks() if self.chunks else [self.data])
    def close(self):
        self.closed = True


class UpdaterSecurityTests(unittest.TestCase):
    def setUp(self):
        self.private = Ed25519PrivateKey.generate()
        self.keys = public_keys(self.private)
        self.envelope = signed_release(self.private)

    def test_semantic_version_order(self):
        versions = ['0.8.0-alpha', '0.8.0-alpha.1', '0.8.0-alpha.beta', '0.8.0-beta', '0.8.0-beta.2', '0.8.0-beta.11', '0.8.0-rc.1', '0.8.0', '0.8.1', '0.8.10']
        self.assertEqual(sorted(versions, key=SemVer.parse), versions)
        self.assertEqual(SemVer.parse('0.8.0+one'), SemVer.parse('0.8.0+two'))
        for invalid in ('0.8', '01.8.0', '0.8.0-beta.01', 'latest', '../1.2.3', '1\u0662.0.0'):
            with self.assertRaises(UpdateError): SemVer.parse(invalid)

    def test_stop_launched_process_ignores_missing_or_manipulated_systemroot(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        system_directory = Path(temporary.name) / 'trusted-system'
        system_directory.mkdir(parents=True)
        taskkill = system_directory / 'taskkill.exe'
        taskkill.write_bytes(b'test executable placeholder')
        for systemroot in (None, '', 'not-a-windows-path', r'\\attacker\share\Windows'):
            process = Mock()
            process.poll.return_value = None
            process.pid = 1234
            with self.subTest(systemroot=systemroot), \
                    patch('graild_updater.os', SimpleNamespace(name='nt')), \
                    patch('graild_updater.ctypes.windll', create=True) as windll, \
                    patch('graild_updater.subprocess.run') as run:
                windll.kernel32.GetSystemDirectoryW.side_effect = lambda buffer, size: (setattr(buffer, 'value', str(system_directory)) or len(str(system_directory)))
                environment = {} if systemroot is None else {'SystemRoot': systemroot}
                with patch.dict(os.environ, environment, clear=True):
                    graild_updater.stop_launched_process(process)
                self.assertEqual(Path(run.call_args.args[0][0]), system_directory / 'taskkill.exe')
                self.assertEqual(run.call_args.args[0][1:], ['/PID', '1234', '/T', '/F'])
                self.assertFalse(run.call_args.kwargs['shell'])
                process.wait.assert_called_once_with(timeout=30)

    def test_stop_launched_process_fails_closed_when_system_directory_unavailable(self):
        process = Mock()
        process.poll.return_value = None
        process.pid = 1234
        with patch('graild_updater.os', SimpleNamespace(name='nt')), \
                patch('graild_updater.ctypes.windll', create=True) as windll, \
                patch('graild_updater.subprocess.run') as run:
            windll.kernel32.GetSystemDirectoryW.return_value = 0
            with self.assertRaises(UpdateError):
                graild_updater.stop_launched_process(process)
        run.assert_not_called()

    def test_signed_beta_and_channel_policy(self):
        self.assertEqual(verify_manifest(self.envelope, self.keys, 'example/graild', 'beta', '0.8.0')['version'], '0.8.1-beta.1')
        with self.assertRaises(UpdateError): verify_manifest(self.envelope, self.keys, 'example/graild', 'stable', '0.8.0')
        with self.assertRaises(UpdateError): verify_manifest(self.envelope, self.keys, 'other/repo', 'beta', '0.8.0')
        with self.assertRaises(UpdateError): verify_manifest(self.envelope, self.keys, 'example/graild', 'beta', '0.9.0')
        stable = signed_release(self.private, version='0.8.1', channel='stable')
        verify_manifest(stable, self.keys, 'example/graild', 'stable', '0.8.0')
        verify_manifest(stable, self.keys, 'example/graild', 'beta', '0.8.0')

    def test_tampering_unknown_keys_and_expiry_are_rejected(self):
        changed = json.loads(json.dumps(self.envelope))
        changed['manifest']['sha256'] = '0' * 64
        with self.assertRaises(UpdateError): verify_manifest(changed, self.keys, 'example/graild', 'beta', '0.8.0')
        with self.assertRaises(UpdateError): verify_manifest(self.envelope, {}, 'example/graild', 'beta', '0.8.0')
        old = dict(self.envelope['manifest'], expires_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat())
        with self.assertRaises(UpdateError): verify_manifest(resign(self.private, old), self.keys, 'example/graild', 'beta', '0.8.0')

    def test_manifest_paths_urls_and_duplicate_json_are_rejected(self):
        bad = dict(self.envelope['manifest'], asset='../GRAILD.exe')
        with self.assertRaises(UpdateError): verify_manifest(resign(self.private, bad), self.keys, 'example/graild', 'beta', '0.8.0')
        with self.assertRaises(UpdateError): strict_json(b'{"manifest":{},"manifest":{}}')
        for url in ('http://github.com/example/graild/releases/download/v1/GRAILD.exe',
                    'https://evil.example/GRAILD.exe', 'https://github.com/other/repo/releases/download/v1/GRAILD.exe'):
            with self.assertRaises(UpdateError): validate_asset_url(url, 'example/graild', 'v1', 'GRAILD.exe')


class DownloadTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.private = Ed25519PrivateKey.generate()
        self.envelope = signed_release(self.private)
        self.data = b'MZverified-build'
        self.session = Mock()
        self.session.headers = {}
        version = patch('auto_update.APP_VERSION', '0.8.0')
        version.start(); self.addCleanup(version.stop)
        self.manager = UpdateManager(Path(temporary.name) / 'updates', public_keys(self.private), self.session)
        self.manager.save_settings('example/graild', 'beta')
        self.url = 'https://github.com/example/graild/releases/download/v0.8.1-beta.1/'
        self.release = {'tag_name': 'v0.8.1-beta.1', 'prerelease': True, 'draft': False,
                        'assets': [{'name': name, 'browser_download_url': self.url + name} for name in ('graild-update.json', 'GRAILD.exe')]}
        def response(url, **kwargs):
            if url.startswith('https://api.github.com/'):
                return Response(json.dumps([self.release]).encode())
            if url.endswith('graild-update.json'):
                return Response(canonical(self.envelope))
            return Response(self.data)
        self.session.get.side_effect = response

    def test_check_signed_download_and_dev_install_rejection(self):
        self.manager._check_worker()
        self.assertEqual(self.manager.snapshot()['status'], 'available')
        self.manager._download_worker(self.manager.candidate)
        self.assertEqual(self.manager.snapshot()['status'], 'ready')
        self.assertEqual((self.manager.ready_job / 'payload.exe').read_bytes(), self.data)
        with patch('sys.frozen', False, create=True), self.assertRaises(UpdateError):
            self.manager.install('not-used')

    def test_bad_signature_never_downloads_payload(self):
        self.envelope['signature'] = base64.b64encode(b'x' * 64).decode()
        self.manager._check_worker()
        self.assertEqual(self.manager.snapshot()['status'], 'error')
        self.assertFalse(any(call.args[0].endswith('GRAILD.exe') for call in self.session.get.call_args_list))

    def test_corrupt_payload_and_interruption_leave_no_installable_file(self):
        self.manager._check_worker()
        self.data = b'wrong bytes'
        self.manager._download_worker(self.manager.candidate)
        self.assertEqual(self.manager.snapshot()['status'], 'error')
        self.assertIsNone(self.manager.ready_job)
        self.assertFalse(list((self.manager.root / 'jobs').glob('*/download.part')))
        self.assertFalse(list((self.manager.root / 'jobs').glob('*/payload.exe')))

    def test_cancel_cleans_partial_download(self):
        self.manager._check_worker()
        def chunks():
            yield self.data[:2]
            self.manager.cancel.set()
            yield self.data[2:]
        self.session.get.side_effect = lambda *args, **kwargs: Response(self.data, chunks=chunks)
        self.manager._download_worker(self.manager.candidate)
        self.assertEqual(self.manager.snapshot()['status'], 'cancelled')
        self.assertFalse(list((self.manager.root / 'jobs').glob('*/download.part')))
        self.assertIsNone(self.manager.ready_job)

    def test_stable_skips_prereleases_and_unconfigured_check_has_no_network(self):
        self.manager.save_settings('example/graild', 'stable')
        self.manager._check_worker()
        self.assertEqual(self.manager.snapshot()['status'], 'up_to_date')
        self.manager.save_settings('', 'beta')
        self.session.get.reset_mock()
        self.assertEqual(self.manager.check()['status'], 'unconfigured')
        self.session.get.assert_not_called()

    def test_inaccessible_update_storage_is_fail_closed(self):
        from auto_update import UnavailableUpdateManager
        manager = UnavailableUpdateManager(PermissionError('update folder is read only'))
        self.assertEqual(manager.check()['status'], 'error')
        self.assertFalse(manager.snapshot()['can_download'])
        with self.assertRaises(UpdateError): manager.download()
        with self.assertRaises(UpdateError): manager.install('unused')

    def test_unsafe_redirect_is_rejected(self):
        self.session.get.side_effect = None
        self.session.get.return_value = Response(b'', 302, {'Location': 'http://evil.example/payload.exe'})
        with self.assertRaises(UpdateError): self.manager._response(self.url + 'GRAILD.exe')


class InstallerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        version = patch('graild_updater.APP_VERSION', '0.8.0')
        version.start(); self.addCleanup(version.stop)
        environment = patch.dict(os.environ, {'LOCALAPPDATA': str(self.root / 'local'), 'APPDATA': str(self.root / 'roaming')})
        environment.start()
        self.addCleanup(environment.stop)
        self.private = Ed25519PrivateKey.generate()
        self.keys = public_keys(self.private)
        self.data = b'MZverified-build'
        self.job = update_root() / 'jobs' / uuid.uuid4().hex
        self.job.mkdir(parents=True)
        self.target = self.root / 'install' / 'GRAILD.exe'
        self.target.parent.mkdir()
        self.target.write_bytes(b'old local app')
        self.old_digest = sha256_file(self.target)
        self.envelope = signed_release(self.private, self.data)
        atomic_json(self.job / 'manifest.json', self.envelope)
        (self.job / 'payload.exe').write_bytes(self.data)
        atomic_json(self.job / 'request.json', {'target': str(self.target), 'parent_pid': os.getpid(), 'old_sha256': self.old_digest,
                    'current_version': '0.8.0', 'repository': 'example/graild', 'channel': 'beta', 'health_token': 'a' * 64})
        self.user_data = self.root / 'roaming' / 'JuiceSpot' / 'session.dat'
        self.user_data.parent.mkdir(parents=True)
        self.user_data.write_bytes(b'persistent discord login')
        lock = patch('graild_updater.install_lock', side_effect=lambda target: nullcontext())
        lock.start(); self.addCleanup(lock.stop)
        self.parent = Mock()
        self.factory = Mock(return_value=self.parent)

    def test_install_waits_for_parent_and_preserves_user_data(self):
        self.parent.wait.side_effect = lambda: self.assertEqual(sha256_file(self.target), self.old_digest)
        startup = Mock(side_effect=lambda target, *args: self.assertEqual(target.read_bytes(), self.data))
        graild_updater.install_job(self.job, self.keys, self.factory, startup)
        self.parent.wait.assert_called_once()
        startup.assert_called_once()
        self.assertEqual(strict_json((self.job / 'result.json').read_bytes())['status'], 'installed')
        self.assertEqual(self.user_data.read_bytes(), b'persistent discord login')

    def test_payload_changed_during_shutdown_is_never_executed(self):
        self.parent.wait.side_effect = lambda: (self.job / 'payload.exe').write_bytes(b'tampered')
        startup = Mock()
        with self.assertRaises(UpdateError): graild_updater.install_job(self.job, self.keys, self.factory, startup)
        startup.assert_not_called()
        self.assertEqual(sha256_file(self.target), self.old_digest)

    def test_failed_startup_rolls_back(self):
        with patch('graild_updater.launch') as launch:
            with self.assertRaises(UpdateError):
                graild_updater.install_job(self.job, self.keys, self.factory, Mock(side_effect=UpdateError('startup failed')))
        self.assertEqual(sha256_file(self.target), self.old_digest)
        self.assertEqual(strict_json((self.job / 'result.json').read_bytes())['status'], 'rolled_back')
        launch.assert_called_once_with([str(self.target)])
        self.assertEqual(self.user_data.read_bytes(), b'persistent discord login')

    def test_new_app_health_requires_trusted_manifest_and_matching_version(self):
        import update_health
        self.target.write_bytes(self.data)
        with patch('sys.frozen', True, create=True), patch('sys.executable', str(self.target)), patch('update_health.APP_VERSION', '0.8.1-beta.1'), patch('update_health.TRUSTED_PUBLIC_KEYS', self.keys), patch('update_health._HANDOFF', (str(self.job), 'a' * 64)):
            update_health.acknowledge_startup()
        health = strict_json((self.job / 'health.json').read_bytes())
        self.assertEqual(health['version'], '0.8.1-beta.1')
        (self.job / 'health.json').unlink()
        with patch('sys.frozen', True, create=True), patch('sys.executable', str(self.target)), patch('update_health.APP_VERSION', '0.8.1-beta.1'), patch('update_health.TRUSTED_PUBLIC_KEYS', {}), patch('update_health._HANDOFF', (str(self.job), 'a' * 64)):
            update_health.acknowledge_startup()
        self.assertFalse((self.job / 'health.json').exists())

    def test_ui_failure_never_acknowledges_update_health(self):
        from web_app import JuiceSpotApp
        app = JuiceSpotApp.__new__(JuiceSpotApp)
        app._window = Mock()
        app._window.evaluate_js.return_value = False
        app._updates = Mock()
        with patch('update_health.acknowledge_startup') as acknowledge:
            app._on_window_loaded()
            acknowledge.assert_not_called()
        app._updates.check.assert_not_called()

    def test_interrupted_commit_recovery(self):
        backup = self.target.parent / ('.graild-backup-' + self.job.name + '.exe')
        backup.write_bytes(self.target.read_bytes())
        self.target.write_bytes(self.data)
        atomic_json(self.job / 'journal.json', {'phase': 'installed'})
        graild_updater.recover_job(self.job, self.keys)
        self.assertEqual(sha256_file(self.target), self.old_digest)
        self.assertEqual(strict_json((self.job / 'result.json').read_bytes())['status'], 'rolled_back')


if __name__ == '__main__':
    unittest.main()
