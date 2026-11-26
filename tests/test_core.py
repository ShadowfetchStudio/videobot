import json
from pathlib import Path
from unittest.mock import patch

import pytest
import requests
import yt_dlp

from videobot.models import Candidate, Options, normalize_url
from videobot.storage import Store
from videobot.runtime import Cancellation, Cancelled, redact
from videobot.downloader import Downloader, format_selector
from videobot.engine import run_queue


def options(tmp_path, **kw):
    return Options(destination=str(tmp_path / "output"), min_free_bytes=0, retries=0, **kw)


def test_urls_and_auth_not_persisted(tmp_path):
    assert normalize_url("HTTPS://EXAMPLE.com/a?x=1#top") == "https://example.com/a?x=1"
    for url in ["file:///tmp/a", "https://name:password@example.com/a"]:
        with pytest.raises(ValueError):
            normalize_url(url)
    opt = options(tmp_path, cookie_browser="firefox")
    store = Store(tmp_path / "jobs.sqlite3")
    store.add(Candidate("https://example.com/video"), opt)
    assert "cookie_browser" not in store.rows()[0]["options"]
    assert "secret" not in redact("https://user:secret@example.com/a?token=secret")
    store.close()


def test_queue_claim_dedupe_retry_and_recovery(tmp_path):
    store = Store(tmp_path / "jobs.sqlite3")
    other = Store(store.path)
    try:
        a, new = store.add(Candidate("https://example.com/video"), options(tmp_path))
        assert new
        assert store.add(Candidate("https://example.com/video"), options(tmp_path)) == (a, False)
        assert store.claim("first")["id"] == a
        assert other.claim("second") is None
        other.finish(a, "wrong-owner", "completed")
        assert store.rows()[0]["status"] == "running"
        store.finish(a, "first", "failed", error="disconnect")
        store.retry([a])
        assert other.claim("second")["attempts"] == 2
        other.interrupt_owner("second")
        assert store.rows()[0]["status"] == "cancelled"
        store.retry([a])
        assert store.claim("third")
        with patch("videobot.storage.psutil.Process", side_effect=ProcessLookupError):
            assert store.recover() == 1
        assert store.rows()[0]["status"] == "cancelled"
    finally:
        store.close()
        other.close()


def test_quality_never_exceeds_ceiling(tmp_path):
    fmt = {
        "format_id": "1080",
        "url": "https://example.com/video.mp4",
        "height": 1080,
        "width": 1920,
        "ext": "mp4",
        "vcodec": "avc1",
        "acodec": "mp4a",
        "protocol": "https",
    }
    for container in ("mp4", "webm", "native"):
        opt = options(tmp_path, quality="720", container=container)
        with yt_dlp.YoutubeDL({"quiet": True, "format": format_selector(opt)}) as ydl:
            with pytest.raises((yt_dlp.utils.DownloadError, yt_dlp.utils.ExtractorError)):
                ydl.process_ie_result(
                    {"id": "fixture", "title": "Fixture", "extractor": "fixture", "formats": [dict(fmt)]},
                    download=False,
                )


def test_direct_small_valid_preserved_and_atomic(media_site, tmp_path):
    origin, web = media_site
    original = (web / "tiny.mp4").read_bytes()
    events = []
    dl = Downloader(options(tmp_path), Cancellation(), lambda kind, **data: events.append((kind, data)))
    result = Path(dl.download("abc123", Candidate(origin + "/tiny.mp4", direct=True)))
    manifest = json.loads((result / "manifest.json").read_text())
    media = result / manifest["files"][0]["name"]
    assert media.read_bytes() == original
    assert (web / "tiny.mp4").exists()
    assert dl.download("abc123", Candidate(origin + "/tiny.mp4", direct=True)) == str(result)
    assert [e for e in events if e[0] == "progress"]
    assert len(list(Path(dl.options.destination).glob("VideoBot-*"))) == 1


def test_existing_unowned_output_never_removed(media_site, tmp_path):
    origin, _ = media_site
    opt = options(tmp_path)
    existing = Path(opt.destination) / "VideoBot-job"
    existing.mkdir(parents=True)
    (existing / "keep.txt").write_text("keep")
    with pytest.raises(FileExistsError):
        Downloader(opt, Cancellation(), lambda *a, **k: None).download(
            "job", Candidate(origin + "/tiny.mp4", direct=True)
        )
    assert (existing / "keep.txt").read_text() == "keep"


def test_non_video_rejected_without_final_folder(tmp_path):
    from unittest.mock import MagicMock

    resp = MagicMock()
    resp.headers = {}
    resp.iter_content.return_value = iter([b"<html>Bad</html>" * 10000])
    resp.__enter__.return_value = resp
    with patch("requests.Session.get", return_value=resp):
        with pytest.raises((ValueError, RuntimeError)):
            Downloader(options(tmp_path), Cancellation(), lambda *a, **k: None).download(
                "invalid", Candidate("https://example.com/a.mp4", direct=True)
            )
    assert not (tmp_path / "output" / "VideoBot-invalid").exists()


def test_disconnect_leaves_partial_only(tmp_path):
    from unittest.mock import MagicMock

    def chunks():
        yield b"x" * 131072
        raise requests.ConnectionError("Disconnected")

    resp = MagicMock()
    resp.headers = {}
    resp.iter_content.return_value = chunks()
    resp.__enter__.return_value = resp
    with patch("requests.Session.get", return_value=resp):
        with pytest.raises(requests.ConnectionError):
            Downloader(options(tmp_path), Cancellation(), lambda *a, **k: None).download(
                "partial", Candidate("https://example.com/a.mp4", direct=True)
            )
    assert not (tmp_path / "output" / "VideoBot-partial").exists()
    assert (tmp_path / "output/.videobot-staging/partial/work/direct.part").exists()


def test_cancelled_before_transfer(tmp_path):
    cancel = Cancellation()
    cancel.event.set()
    with pytest.raises(Cancelled):
        Downloader(options(tmp_path), cancel, lambda *a, **k: None).download(
            "cancel", Candidate("https://example.com/a.mp4", direct=True)
        )
    assert not (tmp_path / "output/VideoBot-cancel").exists()


def test_queue_reports_failed_not_completed(tmp_path):
    store = Store(tmp_path / "queue.sqlite3")
    job, _ = store.add(Candidate("https://example.com/video"), options(tmp_path))
    store.close()
    events = []
    with (
        patch("videobot.engine.Downloader.download", side_effect=ValueError("fixture")),
        patch.object(Cancellation, "wait"),
    ):
        status = run_queue(tmp_path / "queue.sqlite3", Cancellation(), lambda kind, **data: events.append((kind, data)))
    assert status == "failed"
    store = Store(tmp_path / "queue.sqlite3")
    assert store.rows()[0]["status"] == "failed"
    store.close()
    assert events[-1][1]["status"] == "failed"


def test_webm_merge_uses_webm(tmp_path):
    opt = options(tmp_path, container="webm")
    dl = Downloader(opt, Cancellation(), lambda *a, **k: None)
    work = tmp_path / "work"
    work.mkdir()
    with patch("yt_dlp.YoutubeDL") as ctor:
        ctor.return_value.__enter__.return_value.extract_info.return_value = {}
        with pytest.raises(ValueError):
            dl._ytdlp_inline(Candidate("https://example.com/video"), work)
    assert ctor.call_args.args[0]["merge_output_format"] == "webm"
    assert ctor.call_args.args[0]["progress_hooks"]


def test_options_invalid_inputs(tmp_path):
    for kw in ({"max_pages": 0}, {"cooldown": 0}, {"segment_start": 10, "segment_end": 5}, {"container": "exe"}):
        with pytest.raises(ValueError):
            options(tmp_path, **kw).validate()


def test_recovery_handles_reused_pid(tmp_path):
    store = Store(tmp_path / "queue.sqlite3")
    store.add(Candidate("https://example.com/a"), options(tmp_path))
    store.claim("old")
    with store.db:
        store.db.execute("UPDATE jobs SET process_created=1")
    assert store.recover() == 1
    assert store.rows()[0]["status"] == "cancelled"
    store.close()


def test_budget_failure_preserves_source(media_site, tmp_path):
    origin, web = media_site
    opt = options(tmp_path)
    opt.max_bytes = 10
    with pytest.raises(ValueError):
        Downloader(opt, Cancellation(), lambda *a, **k: None).download(
            "budget", Candidate(origin + "/tiny.mp4", direct=True)
        )
    assert (web / "tiny.mp4").exists()
    assert not (tmp_path / "output/VideoBot-budget").exists()


def test_real_ytdlp_exact_path_and_metadata(media_site, tmp_path):
    origin, _ = media_site
    events = []
    result = Path(
        Downloader(options(tmp_path), Cancellation(), lambda k, **v: events.append((k, v))).download(
            "native", Candidate(origin + "/single.html")
        )
    )
    manifest = json.loads((result / "manifest.json").read_text())
    assert manifest["files"] and all((result / i["name"]).is_file() for i in manifest["files"])
    assert any(k == "progress" for k, _ in events)


def test_raw_audio_only_and_segment(media_site, tmp_path):
    import subprocess

    origin, web = media_site
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-c:a",
            "pcm_s16le",
            str(web / "tone.wav"),
        ],
        check=True,
    )
    opt = options(tmp_path, audio_only=True, segment_start=0.2, segment_end=0.8)
    result = Path(
        Downloader(opt, Cancellation(), lambda *a, **k: None).download(
            "audio", Candidate(origin + "/tone.wav", direct=True)
        )
    )
    manifest = json.loads((result / "manifest.json").read_text())
    assert manifest["files"][0]["name"].endswith(".mp3")
    assert 0.5 < float(manifest["duration"]) < 1.0


def test_direct_browser_cookie_and_referrer(tmp_path):
    import subprocess
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    video = tmp_path / "input.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=64x64:d=1", "-c:v", "libx264", str(video)],
        check=True,
    )
    content = video.read_bytes()
    observed = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path == "/page":
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Set-Cookie", "session=fixture; Path=/")
                self.end_headers()
                self.wfile.write(b'<video src="/protected.mp4"></video>')
            elif self.path == "/protected.mp4":
                good = "session=fixture" in self.headers.get("Cookie", "") and self.headers.get("Referer", "").endswith(
                    "/page"
                )
                observed.append(good)
                self.send_response(200 if good else 403)
                self.send_header("Content-Length", str(len(content)) if good else "0")
                self.end_headers()
                if good:
                    self.wfile.write(content)
            else:
                self.send_response(404)
                self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    try:
        result = Downloader(options(tmp_path), Cancellation(), lambda *a, **k: None).download(
            "auth", Candidate(origin + "/protected.mp4", referer=origin + "/page", direct=True)
        )
        assert Path(result).is_dir() and any(observed)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_windowed_worker_event_protocol(tmp_path, monkeypatch):
    import sys
    from videobot.cli import task

    event_path = tmp_path / "events.jsonl"
    with monkeypatch.context() as patcher:
        patcher.setattr(sys, "stdout", None)
        patcher.setattr(sys, "stderr", None)
        assert task({"action": "run", "db": str(tmp_path / "queue.sqlite3"), "event_path": str(event_path)}) == 0
        sys.stdout.close()
    assert json.loads(event_path.read_text())["status"] == "completed"


def test_redaction_removes_entire_credential_headers():
    for line in (
        "Authorization: Bearer secret-credential",
        "Proxy-Authorization: Basic secret-credential",
        "Cookie: session=secret-credential; second=also-private",
        "Set-Cookie: session=secret-credential; Path=/",
        'password="secret-credential with spaces"',
    ):
        cleaned = redact(line + "\nnext diagnostic line")
        assert "secret-credential" not in cleaned
        assert "also-private" not in cleaned
        assert "[redacted]" in cleaned
        assert cleaned.endswith("next diagnostic line")
