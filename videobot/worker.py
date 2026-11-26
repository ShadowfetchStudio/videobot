"""Desktop worker supervises a process group, allowing bounded stop and cleanup."""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from .runtime import redact, terminate_process_tree
from .storage import Store


class TaskWorker(QThread):
    event = Signal(dict)

    def __init__(self, request, parent=None):
        super().__init__(parent)
        self.request = dict(request)
        self.owner = uuid.uuid4().hex
        self.request["owner"] = self.owner
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        process = None
        seen_result = False
        try:
            with tempfile.TemporaryDirectory(prefix="videobot-") as temporary:
                root = Path(temporary)
                request = root / "request.json"
                cancel = root / "cancel"
                self.request["cancel_path"] = str(cancel)
                self.request["event_path"] = str(root / "events.jsonl")
                request.write_text(json.dumps(self.request), encoding="utf-8")
                request.chmod(0o600)
                command = [sys.executable, "-m", "videobot.cli", "_task", str(request)]
                if getattr(sys, "frozen", False):
                    command = [sys.executable, "--worker-task", str(request)]
                kwargs = (
                    {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
                    if os.name == "nt"
                    else {"start_new_session": True}
                )
                env = os.environ.copy()
                env["PYTHONUNBUFFERED"] = "1"
                # File-backed event pipe avoids an uninterruptible readline on a silent downloader.
                log = root / "events.jsonl"
                with (
                    log.open("w", encoding="utf-8") as output,
                    log.open("r", encoding="utf-8", errors="replace") as incoming,
                ):
                    if self._stop.is_set():
                        self.event.emit({"type": "result", "status": "cancelled"})
                        return
                    process = subprocess.Popen(command, stdout=output, stderr=output, env=env, **kwargs)
                    stopped_at = None
                    buffer = ""
                    while True:
                        if self._stop.is_set():
                            cancel.touch(exist_ok=True)
                            stopped_at = stopped_at or time.monotonic()
                            if process.poll() is None and time.monotonic() - stopped_at > 2:
                                self._kill_tree(process)
                        chunk = incoming.read()
                        if chunk:
                            buffer += chunk
                            lines = buffer.split("\n")
                            buffer = lines.pop()
                            for line in lines:
                                try:
                                    event = json.loads(line)
                                    if not isinstance(event, dict) or "type" not in event:
                                        continue
                                    seen_result |= event["type"] in ("result", "error")
                                    self.event.emit(event)
                                except json.JSONDecodeError:
                                    if line.strip():
                                        self.event.emit({"type": "log", "message": redact(line)})
                        if process.poll() is not None:
                            # Drain one more iteration after process exit to include buffered final events.
                            if not chunk:
                                break
                        time.sleep(0.05)
                if not seen_result:
                    self.event.emit(
                        {
                            "type": "result",
                            "status": "cancelled" if self._stop.is_set() else "failed",
                            "message": "Stopped."
                            if self._stop.is_set()
                            else f"Worker exited with status {process.returncode}.",
                        }
                    )
        except Exception as exc:
            self.event.emit({"type": "error", "message": redact(exc)})
        finally:
            if process and process.poll() is None:
                self._kill_tree(process)
            if self.request.get("action") == "run":
                store = Store(self.request.get("db"))
                try:
                    store.interrupt_owner(self.owner)
                finally:
                    store.close()

    _kill_tree = staticmethod(terminate_process_tree)
