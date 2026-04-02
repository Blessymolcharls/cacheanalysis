"""Top-level launcher for the cache analysis framework."""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.abspath("src"))

from cache_analysis.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
