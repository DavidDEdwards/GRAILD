"""Audit a signed release and exercise its actual EXE outside the project."""
import argparse
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid
import pefile

from PyInstaller.archive.readers import CArchiveReader
from update_security import verify_manifest, verify_file, sha256_file
from update_trust import TRUSTED_PUBLIC_KEYS, DEFAULT_REPOSITORY


class References(HTMLParser):
    def __init__(self):
        super().__init__(); self.local = []; self.remote = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag not in ('script', 'link', 'img'): return
        value = attrs.get('src') or attrs.get('href')
        if not value or value.startswith(('data:', '#')): return
        (self.remote if value.startswith(('https:', 'http:', '//')) else self.local).append(value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', default='dist/releases/v0.8.0')
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    project = Path(__file__).resolve().parent
    release = Path(args.release).resolve()
    source = release / 'GRAILD.exe'
    digest = sha256_file(source)
    envelope = json.loads((release / 'graild-update.json').read_bytes())
    manifest = verify_manifest(envelope, TRUSTED_PUBLIC_KEYS, DEFAULT_REPOSITORY, 'beta', '0.0.0', 'v' + envelope['manifest']['version'])
    verify_file(source, manifest)
    archive = CArchiveReader(str(source))
    members = {name.replace('\\', '/'): name for name in archive.toc}
    pyz = archive.open_embedded_archive(next(name for name in archive.toc if name.endswith('.pyz')))
    expected = ['web_app', 'auto_update', 'update_security', 'update_health', 'canary_client', 'canary_integration', 'audio_files',
                'pygame', 'webview', 'requests', 'mutagen', 'cryptography', 'imageio_ffmpeg', 'sqlite3', 'ssl', 'pythonnet', 'clr_loader']
    for name in expected: assert name in pyz.toc, name
    assert 'tkinter' not in pyz.toc, 'Legacy Tkinter frontend was included in the production executable'
    assert 'JuiceGuesserMain' in archive.scripts, 'Production entry-point script was not found in the executable archive'
    assert any(name.endswith('python313.dll') for name in members)
    assert any('ffmpeg' in name and name.endswith('.exe') for name in members)
    assert any('WebView2Loader.dll' in name for name in members)
    assert 'GRAILDUpdater.exe' in members
    assert not any(name.startswith(('discord_oauth_broker', 'publisher_keys', 'release_tools')) for name in pyz.toc)
    for name in members:
        assert not name.endswith(('.dpapi', '.private', '.key', 'session.dat', '.sqlite3')), name
        assert Path(name).name not in ('.env', '.env.local'), name
        if name.endswith('.pem'):
            assert b'PRIVATE KEY' not in archive.extract(members[name]), 'Private key in PEM asset'
    references = References()
    references.feed(archive.extract(members['index.html']).decode('utf-8'))
    assert not references.remote, 'Remote UI resources: ' + repr(references.remote)
    for name in references.local: assert name in members, name
    for name in ['assets/fonts.css', 'assets/tailwind.css']:
        css = archive.extract(members[name]).decode('utf-8')
        for url in re.findall(r'url\([\'\"]?([^\)\'\"]+)', css):
            if url.startswith('data:'): continue
            assert not url.startswith(('https:', 'http:')), url
            assert 'assets/' + url in members, url
    bundled_names = {name.rsplit('/', 1)[-1].lower() for name in members}
    native_count = 0
    unresolved = {}
    for name in members:
        if not name.lower().endswith(('.dll', '.pyd')) or '/win-arm64/' in name or '/win-x86/' in name:
            continue
        try:
            pe = pefile.PE(data=archive.extract(members[name]), fast_load=True)
            pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT']])
        except pefile.PEFormatError:
            continue
        native_count += 1
        for entry in getattr(pe, 'DIRECTORY_ENTRY_IMPORT', []):
            dll = entry.dll.decode().lower()
            if dll in bundled_names or dll.startswith(('api-ms-', 'ext-ms-')) or (Path(os.environ['SystemRoot']) / 'System32' / dll).is_file():
                continue
            unresolved.setdefault(dll, []).append(name)
    assert not unresolved, unresolved
    root = Path(os.environ['LOCALAPPDATA']) / 'GRAILD-StandaloneValidation' / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=False)
    target = root / 'GRAILD.exe'
    shutil.copy2(source, target)
    env = dict(os.environ)
    for key in list(env):
        if key.startswith(('PYTHON', 'GRAILD_', '_PYI')): env.pop(key, None)
    env['PATH'] = str(Path(os.environ['SystemRoot']) / 'System32') + ';' + os.environ['SystemRoot']
    env['APPDATA'] = str(root / 'roaming')
    env['LOCALAPPDATA'] = str(root / 'local')
    env['GRAILD_STANDALONE_DENY_PROJECT'] = str(project)
    env['GRAILD_SMOKE_REAL_AUDIO'] = '1'
    # Avoid parent development/frozen loader settings leaking into the new EXE.
    env['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
    reports = []
    for flag, filename in [('--standalone-smoke-test', 'offline.json')] + ([('--canary-smoke-test', 'live.json')] if args.live else []):
        output = root / filename
        result = subprocess.run([str(target), flag, str(output)], cwd=root, env=env,
                                capture_output=True, timeout=360)
        assert output.is_file(), 'Packaged diagnostic produced no report; exit ' + str(result.returncode)
        report = json.loads(output.read_text())
        reports.append(report)
        assert result.returncode == 0 and report['passed'], report
        print(json.dumps({'diagnostic': flag, 'report': report}), flush=True)
    assert sha256_file(source) == digest == sha256_file(target), 'Signed executable changed during verification'
    summary = {'passed': True, 'version': manifest['version'], 'sha256': digest,
               'test_directory': str(root), 'bundled_modules': expected,
               'remote_ui_assets': references.remote, 'signature_and_checksum': True,
               'native_binaries_audited': native_count, 'unresolved_non_system_dlls': unresolved,
               'project_folder_read_denial': True, 'python_removed_from_child_path': True,
               'existing_installations_modified': False, 'reports': reports}
    output = project / 'build' / 'standalone-audit' / ('v' + manifest['version'] + '-results.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print('Verification report:', output, flush=True)


if __name__ == '__main__': main()
