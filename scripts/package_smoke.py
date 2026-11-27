"""Exercise the packaged worker against generated local media, without accounts."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from videobot.models import Candidate, Options
from videobot.storage import Store


def executable():
    if sys.platform == "darwin":
        return Path("dist/VideoBot.app/Contents/MacOS/VideoBot")
    if os.name == "nt":
        return Path("dist/VideoBot/VideoBot.exe")
    return Path("dist/VideoBot/VideoBot")


def main():
    binary = executable().resolve()
    child_env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    if sys.platform == "darwin":
        # Finder launches do not inherit Homebrew/user tool paths from the shell.
        child_env["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
    with tempfile.TemporaryDirectory(prefix="videobot-smoke-") as temp:
        root = Path(temp)
        screenshot = root / "desktop.png"
        subprocess.run(
            [str(binary), "--smoke-ui", str(screenshot)],
            check=True,
            timeout=30,
            env={**child_env, "VIDEOBOT_HOME": str(root / "app-data")},
        )
        assert screenshot.is_file() and screenshot.stat().st_size > 1000
        web = root / "web"
        web.mkdir()
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=blue:s=128x96:d=5",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=16000:cl=mono",
                "-t",
                "5",
                "-c:a",
                "aac",
                "-c:v",
                "libx264",
                str(web / "clip.mp4"),
            ],
            check=True,
        )
        (web / "page.html").write_text(
            '<title>Packaged fixture</title><video src="/clip.mp4"></video>', encoding="utf-8"
        )

        class Handler(SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(web)))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"

        def task(data, label):
            request = root / (label + ".json")
            events = root / (label + "-events.jsonl")
            data.update(event_path=str(events), cancel_path=str(root / "cancel"))
            request.write_text(json.dumps(data), encoding="utf-8")
            result = subprocess.run(
                [str(binary), "--worker-task", str(request)],
                capture_output=True,
                text=True,
                timeout=240,
                env=child_env,
            )
            text = result.stdout + (events.read_text(encoding="utf-8") if events.exists() else "")
            rows = []
            for line in text.splitlines():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
            if result.returncode or not any(r.get("type") == "result" and r.get("status") == "completed" for r in rows):
                raise RuntimeError(f"{label}: exit={result.returncode}\n{text}\n{result.stderr}")
            return rows

        try:
            options = Options(destination=str(root / "media"), min_free_bytes=0)
            inspected = task(
                {"action": "inspect", "urls": [base + "/page.html"], "options": options.public_dict()}, "inspect"
            )
            assert any(r.get("type") == "candidate" for r in inspected)
            store = Store(root / "queue.sqlite3")
            # Force native generic extraction to exercise the nested transfer process.
            store.add(Candidate(base + "/page.html"), options)
            task({"action": "run", "db": str(store.path), "owner": "package-smoke"}, "download")
            job = store.rows()[0]
            assert job["status"] == "completed", job
            manifest = json.loads((Path(job["output"]) / "manifest.json").read_text(encoding="utf-8"))
            assert manifest["files"]
            subprocess.run(
                [str(binary), "--smoke-ui", str(root / "player.png")],
                check=True,
                timeout=30,
                env={**child_env, "VIDEOBOT_HOME": str(root), "VIDEOBOT_SMOKE_JOB": job["id"]},
            )
            task(
                {
                    "action": "clip",
                    "db": str(store.path),
                    "job_id": job["id"],
                    "start": 0.2,
                    "end": 0.8,
                    "destination": str(root / "clips"),
                },
                "clip",
            )
            # Exercise native speech libraries, model loading, PyAV and bundled VAD in the frozen executable.
            task(
                {
                    "action": "transcribe",
                    "db": str(store.path),
                    "job_id": job["id"],
                    "model": "tiny",
                    "allow_download": True,
                },
                "transcribe",
            )
            assert store.transcript(job["id"]) is not None
            store.close()
            print(
                json.dumps(
                    {
                        "packaged_gui": "passed",
                        "packaged_player": "passed",
                        "packaged_clip": "passed",
                        "packaged_transcription": "passed",
                        "packaged_browser_inspection": "passed",
                        "packaged_native_download": "passed",
                        "manifest_files": len(manifest["files"]),
                    }
                )
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    main()
