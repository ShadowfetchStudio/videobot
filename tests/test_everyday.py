import json
import os
import stat
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from videobot.models import Candidate, Options
from videobot.storage import Store
from videobot.runtime import Cancellation
from videobot.downloader import Downloader


def test_private_sqlite_sidecars(tmp_path):
    if os.name == "nt":
        pytest.skip("POSIX modes; Windows relies on the user's application-data ACL")
    before = os.umask(0o022)
    store = None
    try:
        store = Store(tmp_path / "data" / "queue.sqlite3")
        store.add(Candidate("https://example.org/?token=secret"), Options())
        for file in store.path.parent.iterdir():
            assert stat.S_IMODE(file.stat().st_mode) == 0o600
    finally:
        if store:
            store.close()
        os.umask(before)


def test_cli_sanitizes_all_nested_fields(tmp_path, capsys):
    from videobot.cli import main

    store = Store(tmp_path / "queue.sqlite3")
    store.add(
        Candidate(
            "https://example.org/",
            thumbnail="https://example.org/image?token=SECRET",
            formats=[{"url": "https://example.org/video?key=SECRET"}],
        ),
        Options(),
    )
    store.close()
    assert main(["--db", str(store.path), "list"]) == 0
    assert "SECRET" not in capsys.readouterr().out


def test_recovery_cannot_cancel_new_owner(tmp_path):
    import psutil

    store = Store(tmp_path / "queue.sqlite3")
    other = Store(store.path)
    job, _ = store.add(Candidate("https://example.org/a"), Options())
    store.claim("old")
    real = psutil.Process

    class Dead:
        def create_time(self):
            other.interrupt_owner("old")
            other.retry([job])
            with patch("videobot.storage.psutil.Process", real):
                other.claim("new")
            raise psutil.NoSuchProcess(123)

    with patch("videobot.storage.psutil.Process", return_value=Dead()):
        assert store.recover() == 0
    assert store.rows()[0]["status"] == "running"
    assert store.rows()[0]["owner"] == "new"
    store.close()
    other.close()


def test_thumbnail_lifetime(qtbot, tmp_path):
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication
    from videobot.app import MainWindow

    win = MainWindow(tmp_path / "queue.sqlite3")
    qtbot.addWidget(win)
    win.preview.blockSignals(True)
    win.add_candidate(Candidate("https://example.org/a", thumbnail="http://127.0.0.1:9/image").to_dict())
    win.add_candidate(Candidate("https://example.org/b").to_dict())
    win.preview.setCurrentCell(0, 1)
    win.preview_selected()
    win.preview.setCurrentCell(1, 1)
    win.preview_selected()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()
    assert win._thumbnail_reply is None
    win.preview_selected()
    win.close()


def test_broken_gallery_and_mixed_add_preserve_success(media_site, tmp_path, capsys):
    from videobot.discovery import Discovery
    from videobot.cli import main

    origin, web = media_site
    (web / "broken.html").write_text(
        '<div class="card"><a href="/missing.html">Broken</a><a href="/single.html">Valid</a></div>'
    )
    discovery = Discovery(Options(), Cancellation(), lambda *a, **k: None)
    results = discovery.inspect([origin + "/broken.html"])
    assert len(results) == 1 and results[0].url.endswith("tiny.mp4")
    assert len(discovery.errors) == 1
    db = tmp_path / "queue.sqlite3"
    assert main(["--db", str(db), "add", origin + "/tiny.mp4", origin + "/missing.html"]) == 1
    store = Store(db)
    assert len(store.rows()) == 1
    store.close()
    assert '"status": "partial"' in capsys.readouterr().out


def test_mov_metadata_stays_quicktime(media_site, tmp_path):
    origin, web = media_site
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=64x64:d=1",
            "-c:v",
            "qtrle",
            str(web / "clip.mov"),
        ],
        check=True,
    )
    folder = Path(
        Downloader(
            Options(destination=str(tmp_path / "out"), min_free_bytes=0), Cancellation(), lambda *a, **k: None
        ).download("mov", Candidate(origin + "/clip.mov", title="QuickTime sample", direct=True))
    )
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["files"][0]["name"] == "QuickTime sample.mov"


def test_edit_retry_priority_schedule_and_restore(tmp_path):
    store = Store(tmp_path / "queue.sqlite3")
    low, _ = store.add(Candidate("https://example.org/low"), Options(max_bytes=1000))
    high, _ = store.add(Candidate("https://example.org/high"), Options())
    store.organize([high], priority=10, not_before=32503679999)
    assert store.claim("worker")["id"] == low
    with pytest.raises(ValueError):
        store.edit(low, Options())
    store.finish(low, "worker", "failed")
    store.edit(low, Options(max_bytes=2000))
    row = next(r for r in store.rows() if r["id"] == low)
    assert row["options"]["max_bytes"] == 2000 and row["revision"] == 0
    store.edit(low, Options(max_bytes=2000, audio_only=True))
    assert next(r for r in store.rows() if r["id"] == low)["revision"] == 1
    store.retry([low])
    store.organize([high], not_before=0)
    assert store.claim("worker")["id"] == high
    store.remove([low, high])
    assert len(store.rows()) == 1  # running cannot be removed
    store.restore([low])
    assert len(store.rows()) == 2
    backup = tmp_path / "backup.sqlite3"
    store.backup(backup)
    duplicate = Store(backup)
    assert len(duplicate.rows()) == 2
    duplicate.close()
    store.close()


@pytest.mark.parametrize("format", ["mp3", "m4a", "flac", "wav", "opus"])
def test_audio_formats(media_site, tmp_path, format):
    origin, web = media_site
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=duration=2", str(web / "tone.wav")], check=True)
    options = Options(
        destination=str(tmp_path / "out"),
        audio_only=True,
        audio_format=format,
        min_free_bytes=0,
        segment_start=0.3,
        segment_end=1.3,
        accurate_range=True,
    )
    output = Path(
        Downloader(options, Cancellation(), lambda *a, **k: None).download(
            format, Candidate(origin + "/tone.wav", title="Tone", direct=True)
        )
    )
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["files"][0]["name"].endswith("." + format)
    assert abs(float(manifest["duration"]) - 1) < 0.15


def test_precise_clip_and_integrity(media_site, tmp_path):
    from videobot.library import verify, export_library

    origin, _ = media_site
    options = Options(
        destination=str(tmp_path / "out"), min_free_bytes=0, segment_start=0.2, segment_end=0.8, accurate_range=True
    )
    output = Path(
        Downloader(options, Cancellation(), lambda *a, **k: None).download(
            "precise", Candidate(origin + "/tiny.mp4", title="=Formula", direct=True)
        )
    )
    manifest = json.loads((output / "manifest.json").read_text())
    assert abs(float(manifest["duration"]) - 0.6) < 0.1
    job = {"output": str(output), "id": "precise", "status": "completed"}
    assert verify(job, Cancellation())["ok"]
    csv = tmp_path / "library.csv"
    export_library([job], csv)
    assert "'=Formula" in csv.read_text()
    (output / manifest["files"][0]["name"]).write_bytes(b"changed")
    assert not verify(job, Cancellation())["ok"]


def test_diagnostics_async_and_ui_workflows(qtbot, tmp_path):
    import time
    from PySide6.QtCore import QTimer
    from videobot.app import MainWindow

    win = MainWindow(tmp_path / "queue.sqlite3")
    qtbot.addWidget(win)
    win.show()
    ticks = []
    timer = QTimer(win)
    timer.setInterval(10)
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start()
    started = time.monotonic()
    win.show_diagnostics()
    assert time.monotonic() - started < 0.2
    qtbot.waitUntil(lambda: win.worker is None, timeout=15000)
    assert ticks and win.last_report
    win.store.add(Candidate("https://example.org/alpha", title="Alpha"), Options(project="Research"))
    win.store.add(Candidate("https://example.org/beta", title="Beta"), Options())
    win.refresh_jobs()
    win.tabs.setCurrentIndex(1)
    win.search.setText("research")
    assert win.jobs.rowCount() == 1
    win.jobs.selectRow(0)
    win.edit_selected()
    assert win.tabs.currentIndex() == 3 and win.editing_job
    assert win.apply_edit_btn.isVisible() and win.cancel_edit_btn.isVisible()
    win.project.setText("Discard this")
    win.cancel_job_edit()
    assert all(r["options"].get("project") != "Discard this" for r in win.store.rows())
    win.edit_selected()
    win.project.setText("Edited")
    win.apply_job_edit()
    assert any(r["options"]["project"] == "Edited" for r in win.store.rows())
    win.search.clear()
    win.jobs.selectRow(0)
    win.remove_selected()
    assert len(win.store.rows()) == 1
    win.undo_remove()
    assert len(win.store.rows()) == 2
    win.close()


def test_maintenance_never_removes_completed_media_or_running_partials(tmp_path):
    from videobot.maintenance import staging, restore_backup

    store = Store(tmp_path / "queue.sqlite3")
    job, _ = store.add(Candidate("https://example.org/a"), Options(destination=str(tmp_path / "media")))
    partial = tmp_path / "media" / ".videobot-staging" / job
    partial.mkdir(parents=True)
    (partial / "download.part").write_bytes(b"123")
    completed = tmp_path / "media" / ("VideoBot-" + job)
    completed.mkdir()
    (completed / "keep.mp4").write_bytes(b"keep")
    assert staging(store, [job])[0]["bytes"] == 3
    assert partial.exists()
    store.claim("worker")
    with pytest.raises(ValueError):
        staging(store, [job], delete=True)
    backup = tmp_path / "backup.sqlite3"
    store.backup(backup)
    target = tmp_path / "restored.sqlite3"
    restore_backup(backup, target)
    restored = Store(target)
    assert restored.rows()[0]["status"] == "cancelled"
    restored.close()
    store.interrupt_owner("worker")
    staging(store, [job], delete=True)
    assert not partial.exists() and (completed / "keep.mp4").read_bytes() == b"keep"
    with pytest.raises(ValueError):
        restore_backup(backup, target)
    store.close()


def test_legacy_identity_and_nonfinite_limits(tmp_path):
    import hashlib

    store = Store(tmp_path / "queue.sqlite3")
    candidate = Candidate("https://example.org/old")
    options = Options(destination=str(tmp_path / "out")).validate()
    old_keys = (
        "destination",
        "quality",
        "container",
        "audio_only",
        "subtitles",
        "automatic_subtitles",
        "thumbnail",
        "embed_metadata",
        "editing_compatible",
        "segment_start",
        "segment_end",
    )
    old_identity = hashlib.sha256(
        json.dumps([candidate.url, {k: options.public_dict()[k] for k in old_keys}], sort_keys=True).encode()
    ).hexdigest()
    job, _ = store.add(candidate, options)
    with store.db:
        store.db.execute("UPDATE jobs SET identity=? WHERE id=?", (old_identity, job))
    assert store.add(candidate, options) == (job, False)
    store.remove([job])
    assert store.add(candidate, options) == (job, False)
    assert len(store.rows()) == 1
    store.close()
    for changes in (
        {"cooldown": float("nan")},
        {"segment_start": 0, "segment_end": float("inf")},
        {"rate_limit": float("nan")},
    ):
        with pytest.raises(ValueError, match="finite"):
            Options(**changes).validate()


def test_cli_edit_export_and_selected_run(tmp_path, capsys):
    from videobot.cli import main

    store = Store(tmp_path / "queue.sqlite3")
    a, _ = store.add(Candidate("https://example.org/a"), Options())
    b, _ = store.add(Candidate("https://example.org/b"), Options())
    store.close()
    prefix = ["--db", str(store.path)]
    changes = tmp_path / "changes.json"
    changes.write_text(json.dumps({"max_bytes": 100000}))
    assert main(prefix + ["edit", a, str(changes)]) == 0
    with patch("videobot.engine.Downloader.download", return_value=str(tmp_path)), patch.object(Cancellation, "wait"):
        assert main(prefix + ["run", "--ids", a]) == 0
    store = Store(store.path)
    states = {r["id"]: r for r in store.rows()}
    assert states[a]["status"] == "completed" and states[a]["options"]["max_bytes"] == 100000
    assert states[b]["status"] == "queued"
    store.close()


def test_image_disguised_as_video_is_rejected(tmp_path):
    from videobot.runtime import media_probe

    image = tmp_path / "fake.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=32x32",
            "-frames:v",
            "1",
            "-c:v",
            "png",
            "-f",
            "image2",
            str(image),
        ],
        check=True,
    )
    with pytest.raises(ValueError, match="still image"):
        media_probe(image, Cancellation())
