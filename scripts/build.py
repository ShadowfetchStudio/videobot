"""Build a portable desktop bundle for the current OS."""

import os
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
os.chdir(root)
from third_party import collect

collect(root / "build" / "third-party-notices")
subprocess.run([sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", "packaging/videobot.spec"], check=True)
