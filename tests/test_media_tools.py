import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock

import pytest

from videobot.library import verify
from videobot.media_tools import create_clip, file_record, relink, save_transcript, transcribe
from videobot.models import Candidate, Options
from videobot.runtime import Cancellation, Cancelled
from videobot.storage import Store


@pytest.fixture
def saved(tmp_path, media_site):
    _, web = media_site
    store = Store(tmp_path / "queue.sqlite3")
    options = Options(destination=str(tmp_path / "original"), min_free_bytes=0)
    job_id, _ = store.add(Candidate("https://example.org/media", title="Fixture"), options)
    store.claim("fixture")
    root = tmp_path / "original" / ("VideoBot-" + job_id)
    root.mkdir(parents=True)
    media = root / "fixture.mp4"
    shutil.copy2(web / "tiny.mp4", media)
    manifest = {
        "schema": 1,
        "job_id": job_id,
        "options": options.public_dict(),
        "files": [file_record(media, Cancellation())],
        "source_url": "https://example.org/media",
        "title": "Fixture",
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    store.finish(job_id, "fixture", "completed", output=str(root))
    yield store, store.rows()[0]
    store.close()


def test_relink_verifies_moved_bundle_and_transcripts(saved, tmp_path):
    store, job = saved
    transcript = save_transcript(
        store, job, [{"start": 0.1, "end": 0.5, "text": "Straße and Earth"}], "tiny", "en", "abc", Cancellation()
    )
    moved = tmp_path / "new-drive" / "renamed-bundle"
    moved.parent.mkdir()
    shutil.move(job["output"], moved)
    result = relink(store, [job["id"]], moved.parent, Cancellation(), lambda *a, **k: None)
    assert result[0]["ok"]
    assert store.rows()[0]["output"] == str(moved)
    assert store.search_transcripts("STRASSE")[0]["start"] == 0.1
    assert (moved / Path(transcript).name / "transcript.vtt").is_file()
    assert verify(store.rows()[0], Cancellation())["ok"]


def test_relink_duplicate_corrupt_wrong_revision_fail_closed(saved, tmp_path):
    store, job = saved
    target = tmp_path / "duplicates"
    shutil.copytree(job["output"], target / "one")
    shutil.copytree(job["output"], target / "two")

    def emit(*a, **k):
        pass

    assert not relink(store, [job["id"]], target, Cancellation(), emit)[0]["ok"]
    (target / "one" / "fixture.mp4").write_bytes(b"corrupt")
    assert not relink(store, [job["id"]], target / "one", Cancellation(), emit)[0]["ok"]
    manifest_path = target / "two" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["options"]["quality"] = "720"
    manifest_path.write_text(json.dumps(manifest))
    assert not relink(store, [job["id"]], target / "two", Cancellation(), emit)[0]["ok"]
    assert store.rows()[0]["output"] == job["output"]


def test_local_clip_is_new_verified_bundle_and_preserves_original(saved, tmp_path):
    store, job = saved
    original = (Path(job["output"]) / "fixture.mp4").read_bytes()
    result = create_clip(store, job["id"], 0.2, 0.7, tmp_path / "clips", Cancellation(), lambda *a, **k: None)
    clip = next(j for j in store.rows() if j["id"] == result["job_id"])
    assert verify(clip, Cancellation())["ok"]
    manifest = json.loads((Path(clip["output"]) / "manifest.json").read_text())
    assert manifest["derived_from"]["job_id"] == job["id"]
    assert manifest["duration"] == pytest.approx(0.5)
    assert (Path(job["output"]) / "fixture.mp4").read_bytes() == original
    for start, end in [(1, 0), (0, 10), (float("nan"), 1)]:
        with pytest.raises(ValueError):
            create_clip(store, job["id"], start, end, tmp_path / "clips", Cancellation(), lambda *a, **k: None)
    assert len(store.rows()) == 2


def test_cancelled_clip_and_transcript_leave_no_index_or_final(saved, tmp_path):
    store, job = saved
    cancel = Cancellation()
    cancel.event.set()
    with pytest.raises(Cancelled):
        create_clip(store, job["id"], 0, 0.5, tmp_path / "clips", cancel, lambda *a, **k: None)
    with pytest.raises(Cancelled):
        save_transcript(store, job, [{"start": 0, "end": 0.5, "text": "Do not index"}], "tiny", "en", "abc", cancel)
    assert store.transcript(job["id"]) is None
    assert not list(Path(job["output"]).glob("*transcript*"))
    assert len(store.rows()) == 1


def test_transcript_replace_search_removal_backup(saved, tmp_path):
    store, job = saved
    cancel = Cancellation()

    def save(text):
        return save_transcript(store, job, [{"start": 0.1, "end": 0.5, "text": text}], "tiny", "en", "abc", cancel)

    first = save("old phrase")
    second = save("new 100% phrase")
    assert Path(first).is_dir() and Path(second).is_dir()
    assert not store.search_transcripts("old")
    assert store.search_transcripts("100%")[0]["start"] == 0.1
    assert not store.search_transcripts("' OR 1=1 --")
    store.backup(tmp_path / "backup.sqlite3")
    restored = Store(tmp_path / "backup.sqlite3")
    assert restored.transcript(job["id"])["segments"][0]["text"] == "new 100% phrase"
    restored.close()
    store.remove([job["id"]])
    assert not store.search_transcripts("new")
    store.restore([job["id"]])
    assert len(store.search_transcripts("new")) == 1


def test_transcription_backend_offline_policy_and_failure_atomicity(saved):
    store, job = saved
    engine = SimpleNamespace(
        transcribe=lambda *a, **k: (
            iter([SimpleNamespace(start=0, end=0.5, text="spoken words")]),
            SimpleNamespace(duration=1, language="en"),
        )
    )
    factory = Mock(return_value=engine)
    # Production loads PyAV/Whisper in a child, never beside Qt's FFmpeg backend.
    with (
        patch("videobot.media_tools.media_probe"),
        patch.dict(sys.modules, {"faster_whisper": SimpleNamespace(WhisperModel=factory)}),
    ):
        result = transcribe(store, job["id"], "tiny", False, Cancellation(), lambda *a, **k: None)
        assert result["segments"] == 1
        assert factory.call_args.kwargs["local_files_only"] is True
    before = store.transcript(job["id"])
    with (
        patch("videobot.media_tools.media_probe"),
        patch.dict(
            sys.modules, {"faster_whisper": SimpleNamespace(WhisperModel=Mock(side_effect=RuntimeError("no model")))}
        ),
    ):
        with pytest.raises(RuntimeError):
            transcribe(store, job["id"], "tiny", False, Cancellation(), lambda *a, **k: None)
    assert store.transcript(job["id"]) == before


def test_player_load_seek_and_persist_markers(saved, qtbot):
    from videobot.app import MainWindow
    from videobot.player import MediaDialog

    store, job = saved
    window = MainWindow(store.path)
    qtbot.addWidget(window)
    dialog = MediaDialog(window, job, 0.2)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitUntil(lambda: dialog.player.duration() > 0, timeout=15000)
    assert dialog.player.duration() >= 900
    dialog.mark_in.setValue(0.2)
    dialog.mark_out.setValue(0.7)
    assert dialog.timeline.markers == (200, 700)
    assert window.store.setting("markers:" + job["id"]) == [0.2, 0.7]
    frames = []
    dialog.video.videoSink().videoFrameChanged.connect(lambda frame: frames.append(frame.isValid()))
    dialog.player.play()
    qtbot.waitUntil(lambda: dialog.player.position() > 200, timeout=5000)
    qtbot.waitUntil(lambda: any(frames), timeout=5000)
    dialog.close()
    assert store.setting("markers:" + job["id"]) == [0.2, 0.7]
    window.close()


def test_real_audio_decoder_compatibility(tmp_path):
    import wave

    path = tmp_path / "silence.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0\0" * 16000)
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from faster_whisper.audio import decode_audio; assert len(decode_audio(sys.argv[1])) == 16000",
            str(path),
        ],
        check=True,
        timeout=30,
    )


def test_audio_backend_fallback_preserves_explicit_and_active_services(tmp_path, monkeypatch):
    from videobot.runtime import configure_audio_backend

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("PIPEWIRE_RUNTIME_DIR", str(tmp_path))
    monkeypatch.delenv("QT_AUDIO_BACKEND", raising=False)
    monkeypatch.delenv("PIPEWIRE_REMOTE", raising=False)
    configure_audio_backend()
    assert __import__("os").environ["QT_AUDIO_BACKEND"] == "pulseaudio"
    monkeypatch.setenv("QT_AUDIO_BACKEND", "pipewire")
    configure_audio_backend()
    assert __import__("os").environ["QT_AUDIO_BACKEND"] == "pipewire"
    monkeypatch.delenv("QT_AUDIO_BACKEND")
    (tmp_path / "pipewire-0").touch()
    configure_audio_backend()
    assert "QT_AUDIO_BACKEND" not in __import__("os").environ
