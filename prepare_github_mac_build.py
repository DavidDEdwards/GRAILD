"""Package an allowlisted source tree for GitHub Mac builds, without secrets."""
from pathlib import Path
import json
import hashlib
import zipfile
from prepare_mac_release import FILES
from app_version import APP_VERSION


def main():
    root = Path(__file__).resolve().parent
    target = root / 'dist/releases' / ('v' + APP_VERSION) / 'GRAILD-GitHub-Mac-Build.zip'
    if target.exists():
        raise SystemExit('The upload bundle already exists. Archive it before recreating; nothing was overwritten.')
    files = [root / name for name in FILES]
    files += [root / '.github/workflows/build-macos.yml', root / 'GITHUB_MAC_BUILDS.md', root / '.gitignore']
    files += [root / 'release-notes' / ('v' + APP_VERSION + '.md')]
    files += [path for path in (root / 'assets').rglob('*') if path.is_file()]
    for path in files:
        if not path.is_file(): raise SystemExit('Missing build input: ' + str(path))
        if path.suffix.lower() in {'.pem', '.key', '.dpapi', '.p8', '.pfx', '.p12'}:
            raise SystemExit('Refusing private-key file in source package.')
    target.parent.mkdir(parents=True, exist_ok=True)
    hashes = {}
    with zipfile.ZipFile(target, 'x', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(set(files)):
            name = path.relative_to(root).as_posix()
            data = path.read_bytes()
            hashes[name] = hashlib.sha256(data).hexdigest()
            archive.writestr(name, data)
        archive.writestr('source-checksums.json', json.dumps(hashes, indent=2))
    print('Prepared (not uploaded):', target)


if __name__ == '__main__': main()
