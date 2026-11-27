"""Cancellation, diagnostics and safe event reporting."""

import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def configure_tool_path():
    """Finder does not inherit shell profiles; find standard user-installed tools."""
    if sys.platform != "darwin":
        return
    entries = [entry for entry in os.environ.get("PATH", "").split(os.pathsep) if entry]
    for directory in (
        Path("/opt/homebrew/bin"),
        Path("/usr/local/bin"),
        Path.home() / ".local/bin",
        Path.home() / ".deno/bin",
    ):
        value = str(directory)
        if directory.is_dir() and value not in entries:
            entries.append(value)
    os.environ["PATH"] = os.pathsep.join(entries)


class Cancelled(Exception):
    pass


class Cancellation:
    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.event = threading.Event()

    def cancelled(self):
        return self.event.is_set() or bool(self.path and self.path.exists())

    def check(self):
        if self.cancelled():
            raise Cancelled("Stopped; unfinished jobs can be retried.")

    def wait(self, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.check()
            self.event.wait(min(0.1, max(0, end - time.monotonic())))
        self.check()


def redact(text):
    def clean(match):
        try:
            p = urlsplit(match.group(0))
            host = p.hostname or ""
            if ":" in host:
                host = "[" + host + "]"
            if p.port:
                host += ":" + str(p.port)
            return urlunsplit((p.scheme, host, p.path, "[redacted]" if p.query else "", ""))
        except ValueError:
            return "[redacted URL]"

    text = re.sub(r'https?://[^\s<>"\']+', clean, str(text))
    # Header values can contain spaces (Bearer credentials) and multiple cookies.
    # Redact the whole remainder of that line, not merely its first token.
    text = re.sub(
        r"(?im)\b(proxy-authorization|authorization|set-cookie|cookie|token|password)[ \t]*[:=][^\r\n]*",
        r"\1=[redacted]",
        text,
    )
    return text[:4000]


def public_data(value):
    """Recursively sanitize strings at public log/export boundaries."""
    if isinstance(value, dict):
        return {
            key: public_data(item)
            for key, item in value.items()
            if key.lower() not in {"cookie_file", "cookie_browser", "password", "authorization", "cookies"}
        }
    if isinstance(value, list):
        return [public_data(item) for item in value]
    if isinstance(value, str):
        return redact(value)
    return value


def emit_stdout(kind, **data):
    print(json.dumps({"type": kind, **data}, ensure_ascii=True), flush=True)


class Logger:
    def __init__(self, emit):
        self.emit = emit

    def debug(self, msg):
        if not msg.startswith("[debug] "):
            self.emit("log", message=redact(msg))

    def warning(self, msg):
        self.emit("log", message=redact(msg), level="warning")

    def error(self, msg):
        self.emit("log", message=redact(msg), level="error")


def diagnostics():
    from . import __version__

    result = {"version": __version__, "python": sys.version.split()[0], "tools": {}, "packages": {}}
    for name in ("ffmpeg", "ffprobe", "deno", "node"):
        result["tools"][name] = shutil.which(name)
    for name in ("yt-dlp", "yt-dlp-ejs", "playwright", "PySide6-Essentials"):
        try:
            result["packages"][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result["packages"][name] = None
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, timeout=15000)
            browser.close()
            result["chromium"] = True
    except Exception:
        result["chromium"] = False
    return result


def run_checked(command, cancel, timeout=120, guard=None):
    """Poll child operations so cancellation does not wait for ffprobe/ffmpeg."""
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    started = time.monotonic()
    try:
        while True:
            cancel.check()
            if guard:
                guard()
            if time.monotonic() - started > timeout:
                raise TimeoutError(f"{Path(command[0]).name} exceeded its time budget")
            try:
                out, err = process.communicate(timeout=0.2)
                if process.returncode:
                    raise RuntimeError(redact(err[-2000:]) or "Media operation failed")
                return out
            except subprocess.TimeoutExpired:
                pass
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()


def media_probe(path, cancel, audio_only=False):
    if not shutil.which("ffprobe"):
        raise RuntimeError("ffprobe is missing. Install FFmpeg and run Diagnostics.")
    # Probe formats/streams only, not untrusted embedded URLs or playlists.
    data = json.loads(
        run_checked(
            [
                "ffprobe",
                "-v",
                "error",
                "-protocol_whitelist",
                "file,pipe,crypto",
                "-show_format",
                "-show_streams",
                "-of",
                "json",
                str(path),
            ],
            cancel,
        )
    )
    types = {s.get("codec_type") for s in data.get("streams", [])}
    if "audio" not in types if audio_only else "video" not in types:
        raise ValueError("The downloaded file does not contain the requested media stream.")
    if not audio_only:
        video = [
            s
            for s in data.get("streams", [])
            if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")
        ]
        format_name = data.get("format", {}).get("format_name", "")
        if not video or format_name.endswith("_pipe") or format_name in ("image2", "image2pipe"):
            raise ValueError("The input is a still image or cover art, not a video.")
    if Path(path).stat().st_size == 0:
        raise ValueError("The downloaded file is empty.")
    return data


def terminate_process_tree(process):
    """Terminate a managed process and descendants, including detached children."""
    import os
    import signal
    import psutil

    try:
        children = psutil.Process(process.pid).children(recursive=True)
    except psutil.NoSuchProcess:
        children = []
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=10)
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        process.kill()
    for child in children:
        try:
            if child.is_running():
                child.kill()
        except psutil.NoSuchProcess:
            pass
    psutil.wait_procs(children, timeout=2)
    process.wait(timeout=5)
