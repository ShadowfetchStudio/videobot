"""Opt-in macOS launch agent. Runs due jobs without storing authentication cookies."""

import os
import plistlib
import subprocess
import sys
from pathlib import Path

LABEL = "com.shadowfetchstudio.videobot.queue"


def agent_config(executable, database, log_folder):
    return {
        "Label": LABEL,
        "ProgramArguments": [str(executable), "--background-queue", str(database)],
        "StartInterval": 60,
        "RunAtLoad": True,
        "ProcessType": "Background",
        "StandardOutPath": str(Path(log_folder) / "background.log"),
        "StandardErrorPath": str(Path(log_folder) / "background-error.log"),
    }


def install(database):
    if sys.platform != "darwin" or not getattr(sys, "frozen", False):
        raise ValueError("Install the Apple silicon application in Applications before enabling background runs.")
    exe = Path(sys.executable).resolve()
    if "/Applications/" not in str(exe):
        raise ValueError("Move VideoBot to Applications first; the launch agent needs a stable application path.")
    folder = Path(database).parent
    agent = Path.home() / "Library/LaunchAgents" / (LABEL + ".plist")
    agent.parent.mkdir(parents=True, exist_ok=True)
    if agent.exists():
        raise ValueError("Background queue already configured. Disable it before reconfiguring.")
    with agent.open("xb") as stream:
        plistlib.dump(agent_config(exe, Path(database).resolve(), folder), stream)
    agent.chmod(0o600)
    try:
        subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(agent)], check=True)
    except subprocess.CalledProcessError:
        agent.unlink()
        raise


def disable():
    agent = Path.home() / "Library/LaunchAgents" / (LABEL + ".plist")
    if agent.exists():
        result = subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(agent)], capture_output=True)
        if result.returncode:
            loaded = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{LABEL}"], capture_output=True)
            if loaded.returncode == 0:
                raise RuntimeError("Background service could not be stopped; its configuration was retained.")
        agent.unlink()


def run(database):
    from .storage import Store
    from .runtime import Cancellation, configure_tool_path
    from .engine import run_queue

    store = Store(database)
    try:
        configure_tool_path()
        folder = store.setting("tool_path", "")
        if folder and Path(folder).is_dir():
            os.environ["PATH"] = folder + os.pathsep + os.environ.get("PATH", "")
        store.recover()
        poll_watches(store, Cancellation())
    finally:
        store.close()
    # No auth persisted or inferred. Authenticated jobs must be run interactively.
    return run_queue(database, Cancellation(), lambda *a, **k: None)


def poll_watches(store, cancel):
    import time
    from .discovery import Discovery
    from .models import Options

    for watch in store.setting("watched_sources", []):
        cancel.check()
        key = "watch_last:" + watch["url"]
        if time.time() - store.setting(key, 0) < watch["minutes"] * 60:
            continue
        options = Options(**watch["options"])
        options.max_items = min(options.max_items, 100)
        discovery = Discovery(options, cancel, lambda *a, **k: None)
        items = discovery.inspect([watch["url"]])
        for item in items:
            store.add(item, options)
        store.set_setting(key, time.time())
        store.set_setting("watch_result:" + watch["url"], {"added_or_existing": len(items), "errors": discovery.errors})
