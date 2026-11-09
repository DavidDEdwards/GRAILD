"""Offline publisher key generation and signed GitHub release manifests."""
import argparse
import base64
from datetime import datetime, timezone, timedelta
import getpass
import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app_version import APP_VERSION
from update_trust import TRUSTED_PUBLIC_KEYS
from update_security import SemVer, canonical, repository, sha256_file
from publisher_keys import generate_key, load_key, export_encrypted


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    key = commands.add_parser("keygen")
    key.add_argument("--private-key", required=True)
    key.add_argument("--key-id", required=True)
    key.add_argument("--windows-protected", action="store_true")
    key.add_argument("--public-output")
    public = commands.add_parser("public-key")
    public.add_argument("--private-key", required=True)
    public.add_argument("--key-id", required=True)
    public.add_argument("--public-output")
    export = commands.add_parser("export-key")
    export.add_argument("--private-key", required=True)
    export.add_argument("--output", required=True)
    sign = commands.add_parser("manifest")
    sign.add_argument("--private-key", required=True)
    sign.add_argument("--key-id", required=True)
    sign.add_argument("--repository", required=True)
    sign.add_argument("--channel", choices=("beta", "stable"), default="beta")
    sign.add_argument("--version", default=APP_VERSION)
    sign.add_argument("--asset", required=True)
    sign.add_argument("--notes", required=True)
    sign.add_argument("--output", required=True)
    sign.add_argument('--platform', choices=('windows', 'macos'), default='windows')
    sign.add_argument('--architecture', choices=('arm64', 'x86_64'))
    args = parser.parse_args()
    if args.command == "export-key":
        export_encrypted(args.private_key, args.output)
        print("Encrypted backup created outside the repository.")
        return
    if args.command in ("keygen", "public-key"):
        private = generate_key(args.private_key, args.windows_protected) if args.command == "keygen" else load_key(args.private_key)
        public = base64.b64encode(private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode("ascii")
        record = {"key_id": args.key_id, "public_key": public}
        if args.public_output:
            Path(args.public_output).write_text(json.dumps(record, indent=2), encoding="utf-8")
        print("Public verification key:", json.dumps(record))
        return
    private = load_key(args.private_key)
    public = base64.b64encode(private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode("ascii")
    if TRUSTED_PUBLIC_KEYS.get(args.key_id) != public:
        parser.error("Configure this public key in update_trust.py and rebuild both executables before signing a release.")
    version = SemVer.parse(args.version)
    if args.channel == "stable" and version.prerelease:
        parser.error("Stable releases cannot use prerelease versions.")
    asset = Path(args.asset)
    now = datetime.now(timezone.utc)
    manifest = {"schema": 1, "app": "GRAILD", "repository": repository(args.repository),
                "channel": args.channel, "version": args.version, "tag": "v" + args.version,
                "asset": asset.name, "size": asset.stat().st_size, "sha256": sha256_file(asset),
                "issued_at": now.isoformat(), "expires_at": (now + timedelta(days=90)).isoformat(),
                "notes": Path(args.notes).read_text(encoding="utf-8")}
    if args.platform == 'macos':
        if not args.architecture or asset.name != f'GRAILD-{args.version}-macOS-{args.architecture}.zip':
            parser.error('Choose the matching Mac app ZIP and --architecture.')
        from mac_update_security import archive_bundle_digest, BUNDLE_ID
        manifest.update(platform='macos', architecture=args.architecture, bundle_id=BUNDLE_ID,
                        bundle_sha256=archive_bundle_digest(asset))
    envelope = {"manifest": manifest, "key_id": args.key_id,
                "signature": base64.b64encode(private.sign(canonical(manifest))).decode("ascii")}
    Path(args.output).write_bytes(canonical(envelope))
    print("Signed manifest written. Upload " + Path(args.output).name + " alongside " + asset.name + ".")


if __name__ == "__main__":
    main()
