from videobot.models import Candidate, Options
from videobot.storage import Store, output_identity
from videobot.app import MainWindow
from videobot.discovery import MEDIA_EXTENSIONS


def test_generic_identity_is_scoped_to_url(tmp_path):
    store = Store(tmp_path / "q.sqlite3")
    options = Options(destination=str(tmp_path))
    a = Candidate("https://example.org/a/master.m3u8", extractor="Generic", media_id="master")
    b = Candidate("https://example.org/b/master.m3u8", extractor="Generic", media_id="master")
    assert store.add(a, options)[1]
    assert store.add(b, options)[1]
    assert not store.add(a, options)[1]
    assert len(store.rows()) == 2
    store.close()
    assert output_identity(a, options) != output_identity(b, options)


def test_filter_selection_restored_by_id(qtbot, tmp_path):
    win = MainWindow(tmp_path / "q.sqlite3")
    qtbot.addWidget(win)
    for name in ("Alpha", "Beta", "Gamma"):
        win.store.add(Candidate("https://example.org/" + name, title=name), Options())
    win.tabs.setCurrentIndex(1)
    win.refresh_jobs()
    win.search.setText("Gamma")
    win.jobs.selectRow(0)
    chosen = win.selected_ids()
    win.search.clear()
    assert win.selected_ids() == chosen
    assert len(win.jobs.selectionModel().selectedRows()) == 1
    win.library_search.setText("unrelated")
    assert win.selected_ids() == chosen
    win.close()


def test_typed_tools_path_and_raw_audio(qtbot, tmp_path):
    win = MainWindow(tmp_path / "q.sqlite3")
    qtbot.addWidget(win)
    win.tool_path.setText(str(tmp_path))
    win.tool_path.editingFinished.emit()
    assert win.store.setting("tool_path") == str(tmp_path)
    win.close()
    assert all(ext in MEDIA_EXTENSIONS for ext in (".flac", ".aac", ".opus"))


def test_indexed_phrase_search_and_background_config(tmp_path):
    import json
    from videobot.background import agent_config

    store = Store(tmp_path / "q.sqlite3")
    jid, _ = store.add(Candidate("https://example.org/media", title="Example"), Options())
    with store.db:
        store.db.execute("UPDATE jobs SET status='completed' WHERE id=?", (jid,))
        store.db.execute("INSERT INTO transcript_segments VALUES(?,?,?,?,?)", (jid, 0, 0, 1, "A source document"))
    assert store.search_transcripts("source", words=True)
    assert not store.search_transcripts("sour", words=True)
    assert store.search_transcripts("sour")
    with store.db:
        store.db.execute("DELETE FROM transcript_segments")
    assert not store.search_transcripts("source", words=True)
    store.close()
    config = agent_config(
        "/Applications/VideoBot.app/Contents/MacOS/VideoBot", "/tmp/queue with spaces.sqlite3", tmp_path
    )
    assert config["ProgramArguments"][2] == "/tmp/queue with spaces.sqlite3"
    assert config["StartInterval"] == 60
    assert "cookie" not in json.dumps(config)


def test_scheduling_does_not_change_untouched_fields(qtbot, tmp_path):
    from unittest.mock import patch
    from PySide6.QtWidgets import QDialog, QSpinBox

    win = MainWindow(tmp_path / "q.sqlite3")
    qtbot.addWidget(win)
    jid, _ = win.store.add(Candidate("https://example.org/media"), Options())
    win.store.organize([jid], priority=8, not_before=2000000000)
    win.tabs.setCurrentIndex(1)
    win.refresh_jobs()
    win.jobs.selectRow(0)

    def edit(dialog):
        dialog.findChild(QSpinBox).setValue(12)
        return QDialog.DialogCode.Accepted

    with patch.object(QDialog, "exec", edit):
        win.organize_selected()
    job = win.store.rows()[0]
    assert job["priority"] == 12
    assert job["not_before"] == 2000000000
    win.close()


def test_raw_audio_links_and_audio_only_height_ceiling(media_site, tmp_path):
    import subprocess
    from videobot.discovery import Discovery
    from videobot.downloader import Downloader
    from videobot.runtime import Cancellation

    origin, web = media_site
    for ext in ("flac", "aac"):
        subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=duration=0.3", str(web / ("audio." + ext))], check=True
        )
    (web / "audio.html").write_text('<a href="/audio.flac">FLAC</a><a href="/audio.aac">AAC</a>')
    options = Options(destination=str(tmp_path / "output"), audio_only=True, quality="360", min_free_bytes=0)
    for endpoints in (("audio.flac", "audio.aac"), ("audio.html",)):
        discovery = Discovery(options, Cancellation(), lambda *a, **k: None)
        items = discovery.inspect([origin + "/" + p for p in endpoints])
        assert {i.url for i in items} == {origin + "/audio.flac", origin + "/audio.aac"}
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=red:s=640x480:d=0.3",
            "-f",
            "lavfi",
            "-i",
            "sine=duration=0.3",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(web / "large.mp4"),
        ],
        check=True,
    )
    output = Downloader(options, Cancellation(), lambda *a, **k: None).download(
        "audio-ceiling", Candidate(origin + "/large.mp4", direct=True)
    )
    assert __import__("pathlib").Path(output, "manifest.json").is_file()


def test_paged_native_controls_keep_selection_and_bound_widgets(qtbot):
    from videobot.table import StableTable

    view = StableTable(5)
    qtbot.addWidget(view)
    view.setHorizontalHeaderLabels(["Title", "Project", "Tags", "Folder", "ID"])
    values = [[f"Item {i}", "", "", "/fixture", str(i)] for i in range(250)]
    view.replace_rows(values)
    view.selectRow(0)
    view._change_page(1)
    view._slots[0][1].setChecked(True)
    assert {i.row() for i in view.selectionModel().selectedRows()} == {0, 100}
    assert len(view._slots) == 100
    view.replace_rows(list(reversed(values)))
    assert {view.item(i.row(), 4).text() for i in view.selectionModel().selectedRows()} == {"0", "100"}
    view.replace_rows([values[100]])
    assert view.rowCount() == 1
    assert view.selectionModel().selectedRows()[0].row() == 0
    assert view._slots[0][1].isChecked()
    view.replace_rows(values)
    assert {i.row() for i in view.selectionModel().selectedRows()} == {100}
