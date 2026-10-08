"""Entry point for ``python -m app.cli``."""

from __future__ import annotations

import sys

from app.cli.seed import main

if __name__ == "__main__":
 sys.exit(main())
