from videobot.app import MainWindow
from videobot.worker import TaskWorker


def test_plain_bounded_log_and_persisted_settings(qtbot, tmp_path):
    win = MainWindow(tmp_path / "queue.sqlite3")
    qtbot.addWidget(win)
    win.on_event({"type": "log", "message": "<b>not markup</b>"})
    assert "<b>not markup</b>" in win.log.toPlainText()
    assert win.log.maximumBlockCount() == 1200
    win.destination.setText(str(tmp_path / "media"))
    win.close()
    win2 = MainWindow(tmp_path / "queue.sqlite3")
    qtbot.addWidget(win2)
    assert win2.destination.text() == str(tmp_path / "media")
    win2.close()


def test_early_worker_stop_is_retained(qtbot, tmp_path):
    worker = TaskWorker({"action": "run", "db": str(tmp_path / "queue.sqlite3")})
    events = []
    worker.event.connect(events.append)
    worker.stop()
    with qtbot.waitSignal(worker.finished, timeout=3000):
        worker.start()
    assert any(e.get("status") == "cancelled" for e in events)


def test_actual_worker_and_close_shutdown(qtbot, tmp_path):
    win = MainWindow(tmp_path / "queue.sqlite3")
    qtbot.addWidget(win)
    win.show()
    win.start_task({"action": "inspect", "urls": ["http://10.255.255.1/never"], "options": win.options().public_dict()})
    win.close()
    qtbot.waitUntil(lambda: win.worker is None or not win.worker.isRunning(), timeout=8000)
    qtbot.waitUntil(lambda: not win.isVisible(), timeout=2000)


def test_builtin_profiles_and_no_persisted_auth(qtbot, tmp_path):
    win = MainWindow(tmp_path / "queue.sqlite3")
    qtbot.addWidget(win)
    profiles = win.store.setting("profiles")
    assert {"Source archive", "Editing H.264", "Audio MP3"} <= set(profiles)
    assert all("cookie_file" not in data and "cookie_browser" not in data for data in profiles.values())
    win.close()
