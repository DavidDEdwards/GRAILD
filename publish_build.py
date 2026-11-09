"""Publish a finished Windows build without overwriting a running executable."""
import argparse
import os
from pathlib import Path
import shutil
import tempfile
from datetime import datetime


def publish_build(source, target):
    source, target = Path(source).resolve(), Path(target).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Built executable was not found: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, staging_name = tempfile.mkstemp(prefix=".juicespot-build-", suffix=".exe", dir=target.parent)
    os.close(descriptor)
    staging = Path(staging_name)
    try:
        shutil.copy2(source, staging)
        try:
            os.replace(staging, target)
            return target, False
        except PermissionError:
            # A running Windows .exe cannot be replaced. Keep it intact and
            # publish the completed build under a fresh name instead.
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            alternate = target.with_name(f"{target.stem}-updated-{stamp}{target.suffix}")
            os.replace(staging, alternate)
            return alternate, True
    finally:
        if staging.exists():
            staging.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("target")
    args = parser.parse_args()
    try:
        path, alternate = publish_build(args.source, args.target)
    except OSError as error:
        print(f"Could not save the completed build: {error}")
        return 1
    if alternate:
        print("The existing executable is in use or cannot be replaced.")
        print("Your running app was left open. Close it, then launch the new file below.")
    print(f"Build finished! Updated executable: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
