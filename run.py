#!/usr/bin/env python3
"""Source and packaged desktop entry point."""

import sys
import os
from pathlib import Path
import multiprocessing

# Dispatch frozen resource-tracker/spawn children before importing Qt or the app.
if __name__ == "__main__":
    multiprocessing.freeze_support()

if getattr(sys, "frozen", False):
    bundled = Path(sys._MEIPASS) / "playwright" / "driver" / "package" / ".local-browsers"
    if bundled.is_dir():
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")
from videobot.app import main

if __name__ == "__main__":
    sys.exit(main())
