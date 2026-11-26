"""VideoBot desktop: inspect, select, queue, recover."""

import json
import sys
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from shiboken6 import delete
from PySide6.QtGui import QDesktopServices, QImageReader, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .models import Candidate, Options
from .runtime import configure_tool_path, diagnostics, redact
from .storage import Store
from .worker import TaskWorker


STYLE = """
QWidget { background:#10131d; color:#e8edf7; font-size:13px; }
QMainWindow, QScrollArea { background:#10131d; }
QGroupBox { border:1px solid #323a50; border-radius:8px; margin-top:12px; padding:14px 8px 8px; font-weight:600; }
QGroupBox::title { subcontrol-origin:margin; left:10px; }
QPushButton { background:#29334c; border:1px solid #455270; border-radius:6px; padding:8px 13px; }
QPushButton:hover { background:#394969; }
QPushButton:disabled { color:#778198; background:#1e2433; }
QPushButton#primary { background:#7657d9; color:white; border-color:#987cf0; font-weight:600; }
QLineEdit,QPlainTextEdit,QSpinBox,QDoubleSpinBox,QComboBox,QTableWidget { background:#181e2d; border:1px solid #35405a; border-radius:4px; padding:5px; selection-background-color:#504277; }
QHeaderView::section { background:#242c40; padding:7px; border:0; }
QProgressBar { border:1px solid #35405a; border-radius:4px; text-align:center; }
QProgressBar::chunk { background:#7657d9; }
QTabBar::tab { padding:10px 18px; background:#1b2334; }
QTabBar::tab:selected { background:#3a3157; }
QLabel#muted { color:#a9b5ca; }
"""


class MainWindow(QMainWindow):
    def __init__(self, db_path=None):
        super().__init__()
        self.setWindowTitle(f"VideoBot {__version__}")
        self.resize(1240, 860)
        self.setMinimumSize(950, 680)
        self._store_closed = False
        self.store = Store(db_path)
        self.store.recover()
        self.worker = None
        self.candidates = []
        self.closing = False
        self._thumbnail_reply = None
        self.network = QNetworkAccessManager(self)
        QImageReader.setAllocationLimit(32)
        self._build()
        self._load_options(self.store.setting("options", Options().public_dict()))
        if self.store.setting("profiles") is None:
            archive = Options().public_dict()
            editing = {**archive, "container": "mp4", "editing_compatible": True}
            audio = {**archive, "audio_only": True}
            self.store.set_setting(
                "profiles", {"Source archive": archive, "Editing H.264": editing, "Audio MP3": audio}
            )
        self._refresh_profiles()
        self.refresh_jobs()
        self.setStyleSheet(STYLE)

    def button(self, text, action, primary=False):
        button = QPushButton(text)
        button.clicked.connect(action)
        if primary:
            button.setObjectName("primary")
        return button

    def _build(self):
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(20, 16, 20, 16)
        header = QHBoxLayout()
        title = QLabel("VideoBot")
        title.setStyleSheet("font-size:28px;font-weight:700")
        header.addWidget(title)
        header.addWidget(QLabel("Discover. Choose. Preserve."))
        header.addStretch()
        header.addWidget(self.button("Diagnostics", self.show_diagnostics))
        header.addWidget(
            self.button(
                "Help", lambda: QDesktopServices.openUrl(QUrl("https://github.com/ShadowfetchStudio/videobot#readme"))
            )
        )
        layout.addLayout(header)
        splitter = QSplitter()
        splitter.setOrientation(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 10, 0)
        self.tabs = QTabWidget()
        discover = QWidget()
        d = QVBoxLayout(discover)
        self.urls = QPlainTextEdit()
        self.urls.setPlaceholderText("Paste video, playlist, channel or gallery URLs — one per line")
        self.urls.setMaximumHeight(105)
        d.addWidget(self.urls)
        toolbar = QHBoxLayout()
        self.inspect_btn = self.button("Inspect URLs", self.inspect, True)
        toolbar.addWidget(self.inspect_btn)
        toolbar.addWidget(self.button("Import URL file", self.import_urls))
        toolbar.addWidget(self.button("Select all", lambda: self.select_all(True)))
        toolbar.addWidget(self.button("Select none", lambda: self.select_all(False)))
        d.addLayout(toolbar)
        self.preview = QTableWidget(0, 5)
        self.preview.setHorizontalHeaderLabels(["Save", "Title / source", "Duration", "Available formats", "Creator"])
        self.preview.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.preview.setColumnWidth(0, 55)
        self.preview.setColumnWidth(2, 75)
        self.preview.setColumnWidth(3, 145)
        self.preview.setColumnWidth(4, 120)
        self.preview.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.preview.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.preview.itemSelectionChanged.connect(self.preview_selected)
        d.addWidget(self.preview)
        detail = QHBoxLayout()
        self.thumb = QLabel("Thumbnail")
        self.thumb.setFixedSize(160, 90)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.details = QLabel("Inspect first, then choose the items to queue.")
        self.details.setWordWrap(True)
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        detail.addWidget(self.thumb)
        detail.addWidget(self.details, 1)
        d.addLayout(detail)
        self.queue_btn = self.button("Queue selected videos", self.queue_selected, True)
        d.addWidget(self.queue_btn)
        self.tabs.addTab(discover, "Discover")
        queue = QWidget()
        q = QVBoxLayout(queue)
        self.jobs = QTableWidget(0, 5)
        self.jobs.setHorizontalHeaderLabels(["Title", "Status", "Attempts", "Output / error", "ID"])
        self.jobs.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.jobs.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.jobs.setColumnHidden(4, True)
        self.jobs.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.jobs.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        q.addWidget(self.jobs)
        controls = QHBoxLayout()
        self.run_btn = self.button("Run queue", self.run_queue, True)
        controls.addWidget(self.run_btn)
        controls.addWidget(self.button("Retry selected", self.retry_selected))
        controls.addWidget(self.button("Open output", self.open_output))
        controls.addWidget(self.button("Remove records", self.remove_selected))
        controls.addWidget(self.button("Export manifest", self.export_manifest))
        q.addLayout(controls)
        self.tabs.addTab(queue, "Queue && history")
        left_layout.addWidget(self.tabs)
        self.status = QLabel("Ready")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        left_layout.addWidget(self.status)
        progress = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        progress.addWidget(self.progress)
        self.stop_btn = self.button("Stop / pause", self.stop)
        self.stop_btn.setEnabled(False)
        progress.addWidget(self.stop_btn)
        left_layout.addLayout(progress)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(1200)
        self.log.setMaximumHeight(140)
        left_layout.addWidget(self.log)
        splitter.addWidget(left)
        options_area = QScrollArea()
        options_area.setWidgetResizable(True)
        options_area.setMinimumWidth(310)
        options_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right = QWidget()
        r = QVBoxLayout(right)
        r.setContentsMargins(5, 5, 5, 5)
        profiles = QHBoxLayout()
        self.profile = QComboBox()
        self.profile.setPlaceholderText("Saved profiles")
        profiles.addWidget(self.profile, 1)
        profiles.addWidget(self.button("Load", self.load_profile))
        profiles.addWidget(self.button("Save", self.save_profile))
        r.addLayout(profiles)
        group = QGroupBox("Output")
        form = QFormLayout(group)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.destination = QLineEdit()
        browse = QHBoxLayout()
        browse.addWidget(self.destination)
        browse.addWidget(self.button("…", self.browse_destination))
        form.addRow("Folder", browse)
        self.quality = QComboBox()
        self.quality.addItems(["best", "2160", "1080", "720", "480", "360", "worst"])
        form.addRow("Max resolution", self.quality)
        self.container = QComboBox()
        self.container.addItems(["native", "mp4", "webm"])
        form.addRow("Container", self.container)
        self.audio = QCheckBox("Audio only (MP3)")
        form.addRow(self.audio)
        self.editing = QCheckBox("Editing-compatible H.264/AAC")
        form.addRow(self.editing)
        note = QLabel(
            "Editing mode transcodes video: slower, with a new encoding. Each job gets its own folder and provenance manifest."
        )
        note.setWordWrap(True)
        note.setObjectName("muted")
        form.addRow(note)
        self.subtitles = QLineEdit()
        self.subtitles.setPlaceholderText("en,es or all")
        form.addRow("Subtitle languages", self.subtitles)
        self.auto_subs = QCheckBox("Include automatic captions")
        form.addRow(self.auto_subs)
        self.thumbnail = QCheckBox("Save thumbnail")
        form.addRow(self.thumbnail)
        self.metadata = QCheckBox("Embed metadata")
        self.metadata.setChecked(True)
        form.addRow(self.metadata)
        self.segment = QCheckBox("Download a time range")
        form.addRow(self.segment)
        self.start_time = QDoubleSpinBox()
        self.end_time = QDoubleSpinBox()
        for widget in (self.start_time, self.end_time):
            widget.setRange(0, 864000)
            widget.setSuffix(" s")
        form.addRow("Start", self.start_time)
        form.addRow("End", self.end_time)
        self.rights = QLineEdit()
        form.addRow("Rights notes", self.rights)
        r.addWidget(group)
        limits = QGroupBox("Limits")
        f = QFormLayout(limits)
        f.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.pages = QSpinBox()
        self.pages.setRange(1, 10000)
        f.addRow("Page budget", self.pages)
        self.items = QSpinBox()
        self.items.setRange(1, 100000)
        f.addRow("Item budget", self.items)
        self.size = QDoubleSpinBox()
        self.size.setRange(0.01, 10000)
        self.size.setSuffix(" GiB")
        f.addRow("Maximum job size", self.size)
        self.reserve = QDoubleSpinBox()
        self.reserve.setRange(0, 10000)
        self.reserve.setSuffix(" GiB")
        f.addRow("Free-space reserve", self.reserve)
        self.retries = QSpinBox()
        self.retries.setRange(0, 10)
        f.addRow("Transfer retries", self.retries)
        self.delay = QDoubleSpinBox()
        self.delay.setRange(5, 3600)
        self.delay.setSuffix(" s")
        f.addRow("Success cooldown", self.delay)
        r.addWidget(limits)
        auth = QGroupBox("Authentication · this session only")
        f = QFormLayout(auth)
        f.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.cookie_browser = QComboBox()
        self.cookie_browser.addItems(["", "chrome", "chromium", "firefox", "edge", "brave", "safari"])
        f.addRow("Use browser cookies", self.cookie_browser)
        self.cookie_file = QLineEdit()
        row = QHBoxLayout()
        row.addWidget(self.cookie_file)
        row.addWidget(self.button("…", self.browse_cookies))
        f.addRow("Or cookie file", row)
        note = QLabel(
            "Choose an account only when needed. Cookies are not saved in profiles or exported manifests. Browser access may prompt for OS permission."
        )
        note.setWordWrap(True)
        note.setObjectName("muted")
        f.addRow(note)
        r.addWidget(auth)
        r.addStretch()
        options_area.setWidget(right)
        splitter.addWidget(options_area)
        splitter.setSizes([850, 330])
        layout.addWidget(splitter)
        self.setCentralWidget(body)

    def options(self):
        return Options(
            destination=self.destination.text(),
            quality=self.quality.currentText(),
            container=self.container.currentText(),
            audio_only=self.audio.isChecked(),
            subtitles=self.subtitles.text(),
            automatic_subtitles=self.auto_subs.isChecked(),
            thumbnail=self.thumbnail.isChecked(),
            embed_metadata=self.metadata.isChecked(),
            editing_compatible=self.editing.isChecked(),
            segment_start=self.start_time.value() if self.segment.isChecked() else None,
            segment_end=self.end_time.value() if self.segment.isChecked() else None,
            max_pages=self.pages.value(),
            max_items=self.items.value(),
            max_bytes=int(self.size.value() * 1024**3),
            min_free_bytes=int(self.reserve.value() * 1024**3),
            retries=self.retries.value(),
            cooldown=self.delay.value(),
            cookie_file=self.cookie_file.text(),
            cookie_browser=self.cookie_browser.currentText(),
            rights_notes=self.rights.text(),
        ).validate()

    def _load_options(self, data):
        o = Options(**{k: v for k, v in data.items() if k in Options.__dataclass_fields__})
        self.destination.setText(o.destination)
        self.quality.setCurrentText(o.quality)
        self.container.setCurrentText(o.container)
        self.audio.setChecked(o.audio_only)
        self.subtitles.setText(o.subtitles)
        self.auto_subs.setChecked(o.automatic_subtitles)
        self.thumbnail.setChecked(o.thumbnail)
        self.metadata.setChecked(o.embed_metadata)
        self.editing.setChecked(o.editing_compatible)
        self.segment.setChecked(o.segment_start is not None)
        self.start_time.setValue(o.segment_start or 0)
        self.end_time.setValue(o.segment_end or 0)
        self.pages.setValue(o.max_pages)
        self.items.setValue(o.max_items)
        self.size.setValue(o.max_bytes / 1024**3)
        self.reserve.setValue(o.min_free_bytes / 1024**3)
        self.retries.setValue(o.retries)
        self.delay.setValue(o.cooldown)
        self.rights.setText(o.rights_notes)

    def _error(self, exc):
        self.log.appendPlainText(redact(exc))
        QMessageBox.warning(self, "VideoBot", redact(exc))

    def browse_destination(self):
        path = QFileDialog.getExistingDirectory(self, "Save media to", self.destination.text())
        if path:
            self.destination.setText(path)

    def browse_cookies(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose a Netscape-format cookie file")
        if path:
            self.cookie_file.setText(path)
            self.cookie_browser.setCurrentIndex(0)

    def import_urls(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import URLs", filter="Text files (*.txt);;All files (*)")
        if path:
            try:
                if Path(path).stat().st_size > 1024 * 1024:
                    raise ValueError("URL file is too large (maximum 1 MiB).")
                self.urls.setPlainText(Path(path).read_text(encoding="utf-8"))
            except Exception as exc:
                self._error(exc)

    def start_task(self, request):
        if self.worker and self.worker.isRunning():
            return
        self.progress.setRange(0, 0)
        self.stop_btn.setEnabled(True)
        self.run_btn.setEnabled(False)
        self.inspect_btn.setEnabled(False)
        self.worker = TaskWorker(request, self)
        self.worker.event.connect(self.on_event)
        self.worker.finished.connect(self.task_finished)
        self.worker.start()

    def inspect(self):
        try:
            urls = [line.strip() for line in self.urls.toPlainText().splitlines() if line.strip()]
            if not urls:
                raise ValueError("Paste at least one URL.")
            options = self.options()
            self.store.set_setting("options", options.public_dict())
            self.candidates = []
            self.preview.setRowCount(0)
            self.status.setText("Inspecting sources…")
            self.start_task({"action": "inspect", "urls": urls, "options": asdict(options)})
        except Exception as exc:
            self._error(exc)

    def add_candidate(self, data):
        candidate = Candidate(**data)
        self.candidates.append(candidate)
        row = self.preview.rowCount()
        self.preview.insertRow(row)
        check = QTableWidgetItem()
        check.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
        check.setCheckState(Qt.CheckState.Checked)
        self.preview.setItem(row, 0, check)
        formats = (
            ", ".join(sorted({f"{f.get('height') or 'audio'} {f.get('ext') or ''}" for f in candidate.formats}))
            or "Resolved at download"
        )
        values = [
            candidate.title or redact(candidate.url),
            f"{candidate.duration:.0f}s" if candidate.duration else "Unknown",
            formats,
            candidate.creator,
        ]
        for col, value in enumerate(values, 1):
            self.preview.setItem(row, col, QTableWidgetItem(value))

    def select_all(self, selected):
        for row in range(self.preview.rowCount()):
            self.preview.item(row, 0).setCheckState(Qt.CheckState.Checked if selected else Qt.CheckState.Unchecked)

    def preview_selected(self):
        row = self.preview.currentRow()
        if not 0 <= row < len(self.candidates):
            return
        candidate = self.candidates[row]
        self.details.setText(f"{candidate.title}\n{redact(candidate.url)}")
        self.thumb.clear()
        self.thumb.setText("No thumbnail")
        if self._thumbnail_reply:
            self._thumbnail_reply.abort()
        if not candidate.thumbnail.startswith(("https://", "http://")):
            return
        request = QNetworkRequest(QUrl(candidate.thumbnail))
        request.setTransferTimeout(8000)
        reply = self.network.get(request)
        self._thumbnail_reply = reply
        reply.downloadProgress.connect(
            lambda done, total: reply.abort() if done > 2 * 1024 * 1024 or total > 2 * 1024 * 1024 else None
        )

        def loaded():
            if self._thumbnail_reply is reply and self.preview.currentRow() == row:
                data = reply.readAll()
                pixmap = QPixmap()
                if len(data) <= 2 * 1024 * 1024 and pixmap.loadFromData(data):
                    self.thumb.setPixmap(
                        pixmap.scaled(
                            160, 90, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
                        )
                    )
                self._thumbnail_reply = None
            reply.deleteLater()

        reply.finished.connect(loaded)

    def queue_selected(self):
        try:
            options = self.options()
            added = 0
            duplicates = 0
            for row, candidate in enumerate(self.candidates):
                if self.preview.item(row, 0).checkState() == Qt.CheckState.Checked:
                    _, new = self.store.add(candidate, options)
                    added += new
                    duplicates += not new
            self.store.set_setting("options", options.public_dict())
            self.refresh_jobs()
            self.tabs.setCurrentIndex(1)
            self.status.setText(
                f"Queued {added}; already in queue/history: {duplicates}. Authentication selections apply when you run the queue."
            )
        except Exception as exc:
            self._error(exc)

    def run_queue(self):
        try:
            # Queued jobs already have validated output policies. Only current
            # session authentication applies when running them.
            options = Options(
                cookie_file=self.cookie_file.text(), cookie_browser=self.cookie_browser.currentText()
            ).validate()
            self.start_task(
                {
                    "action": "run",
                    "db": str(self.store.path),
                    "auth": {"cookie_file": options.cookie_file, "cookie_browser": options.cookie_browser},
                }
            )
        except Exception as exc:
            self._error(exc)

    def selected_ids(self):
        return [self.jobs.item(row, 4).text() for row in sorted({i.row() for i in self.jobs.selectedIndexes()})]

    def refresh_jobs(self):
        self.rows = self.store.rows()
        selected = set(self.selected_ids()) if self.jobs.rowCount() else set()
        self.jobs.setRowCount(len(self.rows))
        for row, job in enumerate(self.rows):
            values = [
                job["candidate"]["title"] or redact(job["candidate"]["url"]),
                job["status"],
                str(job["attempts"]),
                job["error"] or job["output"],
                job["id"],
            ]
            for col, value in enumerate(values):
                self.jobs.setItem(row, col, QTableWidgetItem(value))
            if job["id"] in selected:
                self.jobs.selectRow(row)

    def retry_selected(self):
        self.store.retry(self.selected_ids())
        self.refresh_jobs()

    def remove_selected(self):
        self.store.remove(self.selected_ids())
        self.refresh_jobs()

    def open_output(self):
        ids = set(self.selected_ids())
        for job in self.rows:
            if job["id"] in ids and job["output"] and Path(job["output"]).is_dir():
                QDesktopServices.openUrl(QUrl.fromLocalFile(job["output"]))
                return
        self.status.setText("Select a completed job with an existing output folder.")

    def export_manifest(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export library manifest", "videobot-library.json", "JSON (*.json)")
        if not path:
            return
        try:
            entries = []
            for row in self.store.rows():
                manifest = Path(row["output"]) / "manifest.json" if row["output"] else None
                if manifest and manifest.is_file():
                    entries.append(json.loads(manifest.read_text(encoding="utf-8")))
            Path(path).write_text(
                json.dumps({"schema": 1, "items": entries}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            self.status.setText(f"Exported {len(entries)} completed items.")
        except Exception as exc:
            self._error(exc)

    def on_event(self, event):
        kind = event["type"]
        if kind == "candidate":
            self.add_candidate(event["candidate"])
        elif kind == "log":
            self.log.appendPlainText(event.get("message", ""))
        elif kind == "progress":
            percent = event.get("percent")
            self.progress.setRange(0, 100 if percent is not None else 0)
            if percent is not None:
                self.progress.setValue(int(percent))
            speed = event.get("speed")
            eta = event.get("eta")
            self.status.setText(
                f"{event.get('phase', 'Downloading')} · {speed / 1024**2:.1f} MiB/s · ETA {eta:.0f}s"
                if speed and eta is not None
                else event.get("phase", "Downloading")
            )
        elif kind == "phase":
            self.status.setText(event.get("phase", "Working").capitalize())
        elif kind == "job":
            self.refresh_jobs()
        elif kind in ("result", "error"):
            status = event.get("status", "failed")
            self.progress.setRange(0, 100)
            self.progress.setValue(100 if status == "completed" else 0)
            summary = (
                f"{status.capitalize()}: {event.get('count', event.get('completed', 0))} item(s) completed/discovered"
            )
            if event.get("failed"):
                summary += f"; {event['failed']} failed"
            self.status.setText(event.get("message") or summary)
            self.log.appendPlainText(self.status.text())
            self.refresh_jobs()

    def stop(self):
        if self.worker:
            self.worker.stop()
        self.stop_btn.setEnabled(False)
        self.status.setText("Stopping safely… unfinished jobs can be retried.")

    def task_finished(self):
        finished = self.worker
        self.worker = None
        if finished:
            finished.deleteLater()
        self.run_btn.setEnabled(True)
        self.inspect_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.refresh_jobs()
        if self.closing:
            QTimer.singleShot(0, self.close)

    def show_diagnostics(self):
        try:
            report = diagnostics()
            self.log.appendPlainText(json.dumps(report, indent=2))
            missing = [name for name in ("ffmpeg", "ffprobe") if not report["tools"].get(name)]
            if missing:
                self.status.setText("Missing " + ", ".join(missing) + ". See Help → installation.")
            else:
                self.status.setText("Core media tools found. See log for browser/YouTube dependencies.")
        except Exception as exc:
            self._error(exc)

    def _refresh_profiles(self):
        self.profile.clear()
        self.profile.addItems(sorted(self.store.setting("profiles", {})))
        self.profile.setCurrentIndex(-1)

    def load_profile(self):
        data = self.store.setting("profiles", {}).get(self.profile.currentText())
        if data:
            self._load_options(data)

    def save_profile(self):
        try:
            options = self.options()
            name, ok = QInputDialog.getText(self, "Save profile", "Profile name")
            if ok and name.strip():
                profiles = self.store.setting("profiles", {})
                profiles[name.strip()] = options.public_dict()
                self.store.set_setting("profiles", profiles)
                self._refresh_profiles()
        except Exception as exc:
            self._error(exc)

    def closeEvent(self, event):
        if self._store_closed:
            event.accept()
            return
        if self.worker and self.worker.isRunning():
            self.closing = True
            self.stop()
            event.ignore()
            return
        if self._thumbnail_reply:
            self._thumbnail_reply.abort()
        try:
            self.store.set_setting("options", self.options().public_dict())
        except ValueError:
            pass
        self.store.close()
        self._store_closed = True
        event.accept()


def main():
    configure_tool_path()
    if len(sys.argv) > 2 and sys.argv[1] == "--worker-task":
        from .cli import main as cli_main

        return cli_main(["_task", sys.argv[2]])
    smoke_image = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--smoke-ui" else None
    app = QApplication(sys.argv[:1] if smoke_image else sys.argv)
    app.setApplicationName("VideoBot")
    app.setOrganizationName("ShadowfetchStudio")
    window = MainWindow()
    window.show()
    if smoke_image:

        def capture():
            window.grab().save(smoke_image)
            window.close()

        QTimer.singleShot(300, capture)
    result = app.exec()
    # Destroy widgets while QApplication and the Python bindings are still alive.
    # Frozen Linux/Windows builds otherwise crash in PySide atexit cleanup.
    delete(window)
    return result


if __name__ == "__main__":
    sys.exit(main())
