"""Build metadata must not weaken legacy updater version or signature checks."""
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app_version import APP_VERSION
from test_updater import public_keys, resign, signed_release
from update_security import UpdateError, verify_manifest


class HotfixBuildTests(unittest.TestCase):
    def setUp(self):
        self.private = Ed25519PrivateKey.generate()
        self.keys = public_keys(self.private)

    def envelope(self, version, architecture):
        manifest = signed_release(self.private, version=version)['manifest']
        if architecture:
            manifest.update(platform='macos', architecture=architecture,
                            asset=f'GRAILD-{version}-macOS-{architecture}.zip',
                            bundle_id='com.graild.desktop', bundle_sha256='0' * 64)
        return resign(self.private, manifest)

    def verify(self, envelope, current, architecture):
        return verify_manifest(envelope, self.keys, 'example/graild', 'beta', current,
                               platform='macos' if architecture else 'windows',
                               architecture=architecture)

    def test_public_and_internal_identity(self):
        self.assertEqual(APP_VERSION, '0.9.3')

    def test_published_installs_accept_this_release(self):
        # 0.9.1 and 0.9.2 are public; both must see this version as an upgrade, never the reverse.
        for architecture in (None, 'x86_64', 'arm64'):
            for installed in ('0.9.1', '0.9.2'):
                newer = self.envelope(APP_VERSION, architecture)
                self.assertEqual(self.verify(newer, installed, architecture)['version'], APP_VERSION)
                with self.assertRaisesRegex(UpdateError, 'not newer'):
                    self.verify(self.envelope(installed, architecture), APP_VERSION, architecture)

    def test_upgrade_matrix_on_all_platforms(self):
        for architecture in (None, 'x86_64', 'arm64'):
            newer = self.envelope('0.9.2', architecture)
            self.assertEqual(self.verify(newer, '0.9.1', architecture)['version'], '0.9.2')
            with self.assertRaisesRegex(UpdateError, 'not newer'):
                self.verify(self.envelope('0.9.1', architecture), '0.9.2', architecture)

    def test_build_metadata_does_not_change_semantic_precedence(self):
        for architecture in (None, 'x86_64', 'arm64'):
            envelope = self.envelope('0.9.2+9011', architecture)
            self.assertEqual(self.verify(envelope, '0.9.1', architecture)['version'], '0.9.2+9011')
            with self.assertRaisesRegex(UpdateError, 'not newer'):
                self.verify(self.envelope('0.9.1+9011', architecture), '0.9.1', architecture)


if __name__ == '__main__':
    unittest.main()
