"""Entry point for the `peerchat` command."""

import sys


def main() -> None:
    try:
        from .ui import run_app
    except Exception as e:
        print("Failed to import UI:", e)
        print("Try: pip install textual websockets")
        sys.exit(1)
    run_app()


if __name__ == '__main__':
    main()
