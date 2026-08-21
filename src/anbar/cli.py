"""anbarctl — operational CLI (auth toggle, link, list). Full implementation in F4."""
from __future__ import annotations

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(prog="anbarctl", description=__doc__)
    parser.add_argument("command", choices=["version"], help="Command to run")
    args = parser.parse_args()

    if args.command == "version":
        from . import __version__

        print(f"anbar {__version__}")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())