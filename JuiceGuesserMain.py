"""Production entry point for the GRAIL'D desktop application."""

import os
import sys


def main():
    args = sys.argv[1:]
    if len(args) == 2 and args[0] == "--standalone-smoke-test":
        from standalone_smoke import run

        return run(args[1])
    if len(args) == 2 and args[0] == "--canary-smoke-test":
        from canary_smoke import run

        return run(args[1])
    if len(args) == 2 and args[0] == "--beta-update-smoke-test":
        from beta_update_smoke import run

        return run(args[1])
    if len(args) == 3 and args[0] == "--post-update":
        from update_health import set_handoff

        set_handoff(args[1], args[2])

    from web_app import main as run_app

    run_app()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
