"""Release acceptance: actual codecs/streams, cancellation and retry semantics."""

import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch

import psutil
import pytest

from videobot.discovery import Discovery
from videobot.downloader import Downloader
from videobot.models import Candidate, Options
from videobot.runtime import Cancellation, media_probe
from videobot.storage import Store
from videobot.worker import TaskWorker


def opt(tmp_path, **extra):
    return Options(destination=str(tmp_path / "library"), min_free_bytes=0, retries=0, **extra)


def test_actual_webm_output(media_site, tmp_path):
    origin, web = media_site
    subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(web / "tiny.mp4"), "-c:v", "libvpx-vp9", str(web / "video.webm")],
        check=True,
    )
    result = Path(
        Downloader(opt(tmp_path, container="webm"), Cancellation(), lambda *a, **k: None).download(
            "webm", Candidate(origin + "/video.webm", direct=True)
        )
    )
    manifest = json.loads((result / "manifest.json").read_text())
    assert manifest["files"][0]["name"].endswith(".webm")
    assert media_probe(result / manifest["files"][0]["name"], Cancellation())["streams"][0]["codec_name"] == "vp9"


def test_editing_preset_actual_codec_and_unicode(media_site, tmp_path):
    origin, _ = media_site
    output = Path(
        Downloader(opt(tmp_path, editing_compatible=True), Cancellation(), lambda *a, **k: None).download(
            "edit", Candidate(origin + "/tiny.mp4", title="日本語 🎬", direct=True)
        )
    )
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    probe = media_probe(output / manifest["files"][0]["name"], Cancellation())
    assert probe["streams"][0]["codec_name"] == "h264"
    assert probe["streams"][0]["pix_fmt"] == "yuv420p"
    assert manifest["title"] == "日本語 🎬"


def test_hls_manifest_actual_download(media_site, tmp_path):
    origin, web = media_site
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(web / "tiny.mp4"),
            "-c",
            "copy",
            "-hls_time",
            "1",
            "-hls_list_size",
            "0",
            str(web / "stream.m3u8"),
        ],
        check=True,
    )
    items = Discovery(opt(tmp_path), Cancellation(), lambda *a, **k: None).inspect([origin + "/stream.m3u8"])
    assert len(items) == 1 and not items[0].direct
    output = Path(Downloader(opt(tmp_path), Cancellation(), lambda *a, **k: None).download("hls", items[0]))
    manifest = json.loads((output / "manifest.json").read_text())
    assert media_probe(output / manifest["files"][0]["name"], Cancellation())["streams"]


def test_embed_discovery_does_not_raw_download(browser):
    from videobot.discovery import SCAN

    page = browser.new_page()
    page.route(
        "**/*",
        lambda r: r.fulfill(
            body='<iframe src="https://www.youtube.com/embed/example"></iframe>', content_type="text/html"
        ),
    )
    page.goto("https://example.com/page")
    data = page.evaluate(SCAN)
    assert data["media"] == ["https://www.youtube.com/embed/example"]
    from videobot.discovery import is_native

    assert is_native("https://www.youtube.com/embed/abcdefghijk")
    page.close()


def test_retry_after_honored_and_response_closed(tmp_path, media_site):
    _, web = media_site
    limited = MagicMock()
    limited.status_code = 429
    limited.headers = {"Retry-After": "7"}
    limited.__enter__.return_value = limited
    success = MagicMock()
    success.status_code = 200
    success.headers = {}
    success.iter_content.return_value = iter([(web / "tiny.mp4").read_bytes()])
    success.__enter__.return_value = success
    cancel = Cancellation()
    o = opt(tmp_path)
    o.retries = 1
    with patch("requests.Session.get", side_effect=[limited, success]), patch.object(cancel, "wait") as wait:
        result = Downloader(o, cancel, lambda *a, **k: None).download(
            "retry", Candidate("https://example.com/a.mp4", direct=True)
        )
    assert Path(result).is_dir()
    wait.assert_called_once_with(7)
    limited.__exit__.assert_called_once()
    success.__exit__.assert_called_once()


def test_low_space_prevents_network(tmp_path):
    o = opt(tmp_path)
    o.min_free_bytes = 100
    with (
        patch("shutil.disk_usage", return_value=type("Usage", (), {"free": 10})()),
        patch("requests.Session.get") as get,
    ):
        with pytest.raises(OSError, match="Free space"):
            Downloader(o, Cancellation(), lambda *a, **k: None).download(
                "space", Candidate("https://example.com/a.mp4", direct=True)
            )
        get.assert_not_called()


def test_live_transfer_stop_bounded_and_queue_cancelled(qtbot, tmp_path):
    entered = threading.Event()
    release = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "100000000")
            self.end_headers()
            entered.set()
            release.wait(12)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    store = Store(tmp_path / "queue.sqlite3")
    job, _ = store.add(Candidate(f"http://127.0.0.1:{server.server_port}/slow.mp4", direct=True), opt(tmp_path))
    worker = TaskWorker({"action": "run", "db": str(store.path)})
    events = []
    worker.event.connect(events.append)
    try:
        worker.start()
        qtbot.waitUntil(entered.is_set, timeout=8000)
        started = time.monotonic()
        worker.stop()
        qtbot.waitUntil(lambda: not worker.isRunning(), timeout=8000)
        assert time.monotonic() - started < 7
        assert store.rows()[0]["status"] == "cancelled"
        assert not (tmp_path / "library" / ("VideoBot-" + job)).exists()
        assert any(e.get("status") == "cancelled" for e in events)
    finally:
        release.set()
        worker.stop()
        worker.wait(10000)
        store.close()
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.skipif(os.name == "nt", reason="Unix SIGTERM-specific descendant fixture")
def test_process_group_kills_stubborn_child(tmp_path):
    marker = tmp_path / "pid"
    child = "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)"
    parent = 'import subprocess,sys,time;from pathlib import Path;p=subprocess.Popen([sys.executable,"-c",sys.argv[2]]);Path(sys.argv[1]).write_text(str(p.pid));time.sleep(60)'
    process = subprocess.Popen([sys.executable, "-c", parent, str(marker), child], start_new_session=True)
    try:
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert marker.exists()
        pid = int(marker.read_text())
        TaskWorker._kill_tree(process)
        assert process.poll() is not None
        assert not psutil.pid_exists(pid) or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
    finally:
        if process.poll() is None:
            TaskWorker._kill_tree(process)
