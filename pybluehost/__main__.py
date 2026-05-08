"""Module entry point so ``python -m pybluehost ...`` works."""
from __future__ import annotations

import sys

from pybluehost.cli import main

if __name__ == "__main__":
    sys.exit(main())
