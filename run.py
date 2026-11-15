"""Main entry point: forwards all arguments to the `analog` CLI (contracts/cli.md)."""

import sys

from analogfinder.cli import main

if __name__ == "__main__":
    sys.exit(main())
