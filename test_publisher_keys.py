from pathlib import Path
import tempfile
import unittest
from publisher_keys import generate_key,load_key,HEADER


class PublisherKeyTests(unittest.TestCase):
    def test_windows_protected_key_roundtrip_without_plaintext_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'key.dpapi'
            first=generate_key(path,windows_protected=True)
            self.assertTrue(path.read_bytes().startswith(HEADER))
            second=load_key(path)
            first.public_key().verify(second.sign(b'publisher key test'),b'publisher key test')
            with self.assertRaises(FileExistsError):generate_key(path,windows_protected=True)

    def test_private_key_generation_inside_project_is_rejected(self):
        with self.assertRaises(ValueError):generate_key(Path(__file__).parent/'do-not-create.dpapi',windows_protected=True)


if __name__=='__main__':unittest.main()
