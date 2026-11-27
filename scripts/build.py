"""Build a portable desktop bundle for the current OS."""

import os
import platform
import json
import importlib.metadata
import subprocess
import sys
from pathlib import Path
from third_party import collect
from create_icon import create
from videobot import __version__

if sys.platform != "darwin" or platform.machine() != "arm64":
    raise SystemExit("Maintained desktop releases target Apple silicon macOS only.")

root = Path(__file__).resolve().parents[1]
os.chdir(root)

create(root)

commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
(root / "build/build-info.json").write_text(
    json.dumps(
        {
            "version": __version__,
            "commit": commit,
            "architecture": platform.machine(),
            "python": platform.python_version(),
            "qt": importlib.metadata.version("PySide6-Essentials"),
            "dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()),
        },
        indent=2,
    )
)

collect(root / "build" / "third-party-notices")
subprocess.run([sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", "packaging/videobot.spec"], check=True)
