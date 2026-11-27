"""VideoBot desktop: inspect, select, queue, recover."""

import json
import os
import time
import sys
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, QDateTime, QItemSelectionModel
from shiboken6 import delete
from PySide6.QtGui import QDesktopServices, QImageReader, QPixmap, QShortcut, QKeySequence
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QSystemTrayIcon,
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
from .runtime import configure_tool_path, public_data, redact
from .library import export_library
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
QPushButton#primary:disabled { background:#2a243d; color:#8992a5; border-color:#3c3751; }
QLineEdit,QPlainTextEdit,QSpinBox,QDoubleSpinBox,QComboBox,QTableWidget { background:#181e2d; border:1px solid #35405a; border-radius:4px; padding:5px; selection-background-color:#504277; }
QHeaderView::section { background:#242c40; padding:7px; border:0; }
QProgressBar { border:1px solid #35405a; border-radius:4px; text-align:center; }
QProgressBar::chunk { background:#7657d9; }
QTabBar::tab { padding:10px 18px; background:#1b2334; }
QTabBar::tab:selected { background:#3a3157; }
QCheckBox::indicator { width:16px; height:16px; border:1px solid #8d9ab0; border-radius:3px; background:#181e2d; }
QCheckBox::indicator:checked { background:#987cf0; border:2px solid #d8cdfc; }
QLabel#muted { color:#a9b5ca; }
"""


class MainWindow(QMainWindow):
    def __init__(self, db_path=None):
        super().__init__()
        self.setWindowTitle(f"VideoBot {__version__}")
        self.resize(1240, 860)
        self.setMinimumSize(840, 620)
        self._store_closed = False
        self.store = Store(db_path)
        self.store.recover()
        self.worker = None
        self.action_buttons = {}
        self.candidates = []
        self.closing = False
        self._thumbnail_reply = None
        self.editing_job = None
        self.last_removed = []
        self.last_report = None
        self.failed_urls = []
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
        self.theme.setCurrentText(self.store.setting("theme", "Dark"))
        self.apply_theme()
        self.tool_path.setText(self.store.setting("tool_path", ""))
        self.set_tool_path()
        self.scheduler = QTimer(self)
        self.scheduler.setInterval(5000)
        self.scheduler.timeout.connect(self.scheduler_tick)
        self.scheduler.start()
        self.tray = QSystemTrayIcon(self.style().standardIcon(self.style().StandardPixmap.SP_MediaPlay), self)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        for sequence, callback in (
            ("Ctrl+L", self.focus_urls),
            ("Ctrl+Return", self.inspect),
            ("Ctrl+F", self.focus_search),
            ("Escape", self.stop),
        ):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(callback)
        self.setAcceptDrops(True)

    def button(self, text, action, primary=False):
        button = QPushButton(text)
        button.clicked.connect(action)
        self.action_buttons.setdefault(getattr(action, "__name__", text), []).append(button)
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
        header.addWidget(self.button("Setup && settings", lambda: self.tabs.setCurrentIndex(3)))
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
        intro = QLabel("Add sources → inspect → choose items → queue. Nothing downloads until you run the queue.")
        intro.setWordWrap(True)
        d.addWidget(intro)
        d.addWidget(self.urls)
        toolbar = QHBoxLayout()
        self.inspect_btn = self.button("Inspect URLs", self.inspect, True)
        toolbar.addWidget(self.inspect_btn)
        toolbar.addWidget(self.button("Import URL file", self.import_urls))
        toolbar.addWidget(self.button("Retry failed URLs", self.retry_inspection))
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
        self.preview.itemChanged.connect(self.update_actions)
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
        self.tabs.addTab(discover, "1  Add sources")
        queue = QWidget()
        q = QVBoxLayout(queue)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search title, source, project, tags or error…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh_jobs)
        self.status_filter = QComboBox()
        self.status_filter.addItems(["All active", "queued", "running", "failed", "cancelled", "completed", "Removed"])
        self.status_filter.currentTextChanged.connect(self.refresh_jobs)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.status_filter)
        q.addLayout(filters)
        self.queue_summary = QLabel()
        self.queue_summary.setWordWrap(True)
        q.addWidget(self.queue_summary)
        self.jobs = QTableWidget(0, 7)
        self.jobs.setHorizontalHeaderLabels(
            ["Title", "Status", "Tries", "Output / error", "ID", "Priority", "Scheduled"]
        )
        self.jobs.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.jobs.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.jobs.setColumnHidden(4, True)
        self.jobs.setColumnWidth(1, 85)
        self.jobs.setColumnWidth(2, 50)
        self.jobs.setColumnWidth(5, 60)
        self.jobs.setColumnWidth(6, 140)
        self.jobs.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.jobs.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.jobs.itemSelectionChanged.connect(self.update_actions)
        q.addWidget(self.jobs)
        controls = QHBoxLayout()
        self.run_btn = self.button("Run queue", self.run_queue, True)
        controls.addWidget(self.run_btn)
        controls.addWidget(self.button("Retry selected", self.retry_selected))
        controls.addWidget(self.button("Run selected", self.run_selected))
        controls.addWidget(self.button("Edit settings", self.edit_selected))
        controls.addWidget(self.button("Remove records", self.remove_selected))
        controls.addWidget(self.button("Undo remove", self.undo_remove))
        q.addLayout(controls)
        more = QHBoxLayout()
        more.addWidget(self.button("Priority / schedule", self.organize_selected))
        more.addWidget(self.button("Restore selected", self.restore_selected))
        self.auto_run = QCheckBox("Auto-run due jobs (app must stay open)")
        more.addWidget(self.auto_run)
        more.addWidget(self.button("Clean partials", self.clean_partials))
        more.addStretch()
        q.addLayout(more)
        self.tabs.addTab(queue, "2  Queue")
        library = QWidget()
        lib = QVBoxLayout(library)
        self.library_search = QLineEdit()
        self.library_search.setPlaceholderText("Find saved media by title, project or tags…")
        self.library_search.setClearButtonEnabled(True)
        self.library_search.textChanged.connect(self.refresh_jobs)
        lib.addWidget(self.library_search)
        self.library_summary = QLabel()
        self.library_summary.setWordWrap(True)
        lib.addWidget(self.library_summary)
        self.library = QTableWidget(0, 5)
        self.library.setHorizontalHeaderLabels(["Title", "Project", "Tags", "Folder", "ID"])
        self.library.setColumnHidden(4, True)
        self.library.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.library.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.library.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.library.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.library.cellDoubleClicked.connect(lambda *_: self.play_selected())
        self.library.itemSelectionChanged.connect(self.update_actions)
        lib.addWidget(self.library)
        actions = QHBoxLayout()
        actions.addWidget(self.button("Preview / clip / transcribe", self.play_selected, True))
        actions.addWidget(self.button("Open folder", self.open_output))
        actions.addWidget(self.button("Verify files", self.verify_selected))
        actions.addWidget(self.button("Export JSON / CSV", self.export_manifest))
        lib.addLayout(actions)
        more_library = QHBoxLayout()
        more_library.addWidget(self.button("Relink moved media…", self.relink_selected))
        more_library.addWidget(self.button("Search all transcripts…", self.search_transcripts))
        lib.addLayout(more_library)
        self.tabs.addTab(library, "3  Library")
        left_layout.addWidget(self.tabs)
        self.status = QLabel("Ready")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.status.setMaximumHeight(60)
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
        self.log.setMaximumHeight(110)
        self.log.setVisible(False)
        log_toggle = QCheckBox("Show activity log")
        log_toggle.toggled.connect(self.log.setVisible)
        left_layout.addWidget(log_toggle)
        self.log_toggle = log_toggle
        left_layout.addWidget(self.log)
        splitter.addWidget(left)
        options_area = QScrollArea()
        options_area.setWidgetResizable(True)
        options_area.setMinimumWidth(400)
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
        profiles.addWidget(self.button("Delete", self.delete_profile))
        r.addLayout(profiles)
        group = QGroupBox("Output")
        form = QFormLayout(group)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.destination = QLineEdit()
        browse = QHBoxLayout()
        browse.addWidget(self.destination)
        browse.addWidget(self.button("…", self.browse_destination))
        form.addRow(QLabel("Destination folder"))
        form.addRow(browse)
        self.quality = QComboBox()
        self.quality.addItems(["best", "2160", "1440", "1080", "720", "480", "360", "worst"])
        form.addRow("Max resolution", self.quality)
        self.container = QComboBox()
        self.container.addItems(["native", "mp4", "webm"])
        form.addRow("Container", self.container)
        self.audio = QCheckBox("Audio only")
        form.addRow(self.audio)
        self.audio_format = QComboBox()
        self.audio_format.addItems(["mp3", "m4a", "flac", "wav", "opus"])
        form.addRow("Audio format", self.audio_format)
        self.audio_bitrate = QComboBox()
        self.audio_bitrate.addItems(["64", "96", "128", "192", "256", "320"])
        form.addRow("Lossy bitrate (kbps)", self.audio_bitrate)
        self.project = QLineEdit()
        self.project.setMaxLength(120)
        form.addRow("Project", self.project)
        self.tags = QLineEdit()
        self.tags.setMaxLength(500)
        self.tags.setPlaceholderText("research, interview, reference")
        form.addRow("Tags", self.tags)
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
        self.accurate = QCheckBox("Accurate range (re-encode; full source transfer)")
        form.addRow(self.accurate)
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
        self.bandwidth = QSpinBox()
        self.bandwidth.setRange(0, 1000000)
        self.bandwidth.setSuffix(" KiB/s")
        self.bandwidth.setSpecialValueText("Unlimited")
        f.addRow("Bandwidth limit", self.bandwidth)
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
        self.apply_edit_btn = self.button("Apply changes to selected job", self.apply_job_edit, True)
        self.apply_edit_btn.setVisible(False)
        r.addStretch()
        options_area.setWidget(right)
        settings_page = QWidget()
        settings_layout = QHBoxLayout(settings_page)
        settings_layout.addWidget(options_area, 2)
        setup = QVBoxLayout()
        setup_note = QLabel(
            "Output settings apply to newly queued items. Use Queue → Edit settings to change an existing idle job."
        )
        setup_note.setWordWrap(True)
        setup.addWidget(setup_note)
        setup.addWidget(self.apply_edit_btn)
        self.cancel_edit_btn = self.button("Cancel job edit", self.cancel_job_edit)
        self.cancel_edit_btn.setVisible(False)
        setup.addWidget(self.cancel_edit_btn)
        setup.addWidget(self.button("Check dependencies", self.show_diagnostics, True))
        setup.addWidget(self.button("Export support report", self.export_support))
        setup.addWidget(self.button("Back up queue && profiles", self.backup_queue))
        self.tool_path = QLineEdit()
        self.tool_path.setPlaceholderText("Optional folder containing ffmpeg / ffprobe")
        setup.addWidget(QLabel("Media tools folder"))
        setup.addWidget(self.tool_path)
        setup.addWidget(self.button("Choose tools folder", self.choose_tools))
        self.theme = QComboBox()
        self.theme.addItems(["Dark", "Light", "System"])
        self.theme.currentTextChanged.connect(self.apply_theme)
        setup.addWidget(QLabel("Appearance"))
        setup.addWidget(self.theme)
        self.notifications = QCheckBox("Notify when a queue run finishes")
        self.notifications.setChecked(self.store.setting("notifications", True))
        setup.addWidget(self.notifications)
        setup.addWidget(
            self.button(
                "Check releases",
                lambda: QDesktopServices.openUrl(QUrl("https://github.com/ShadowfetchStudio/videobot/releases/latest")),
            )
        )
        setup.addStretch()
        setup.setContentsMargins(12, 12, 12, 12)
        settings_layout.addLayout(setup, 1)
        self.tabs.addTab(settings_page, "4  Settings")
        self.tabs.currentChanged.connect(self.update_context)
        self.output_summary = QLabel()
        self.output_summary.setWordWrap(True)
        d.insertWidget(1, self.output_summary)
        d.insertWidget(2, self.button("Choose output settings", lambda: self.tabs.setCurrentIndex(3)))
        layout.addWidget(splitter)
        self.setCentralWidget(body)

    def options(self):
        return Options(
            destination=self.destination.text(),
            quality=self.quality.currentText(),
            container=self.container.currentText(),
            audio_only=self.audio.isChecked(),
            audio_format=self.audio_format.currentText(),
            audio_bitrate=int(self.audio_bitrate.currentText()),
            accurate_range=self.accurate.isChecked(),
            rate_limit=self.bandwidth.value() * 1024,
            project=self.project.text(),
            tags=self.tags.text(),
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
        self.audio_format.setCurrentText(o.audio_format)
        self.audio_bitrate.setCurrentText(str(o.audio_bitrate))
        self.accurate.setChecked(o.accurate_range)
        self.bandwidth.setValue(o.rate_limit // 1024)
        self.project.setText(o.project)
        self.tags.setText(o.tags)
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
        self.update_context()

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
        self.update_actions()

    def inspect(self):
        if self.worker and self.worker.isRunning():
            return
        try:
            urls = [line.strip() for line in self.urls.toPlainText().splitlines() if line.strip()]
            if not urls:
                raise ValueError("Paste at least one URL.")
            options = self.options()
            self.store.set_setting("options", options.public_dict())
            self.failed_urls = []
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
        previous = self._thumbnail_reply
        self._thumbnail_reply = None
        if previous:
            previous.abort()
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
            active = self._thumbnail_reply is reply
            if active:
                self._thumbnail_reply = None
            if active and self.preview.currentRow() == row:
                data = reply.readAll()
                pixmap = QPixmap()
                if len(data) <= 2 * 1024 * 1024 and pixmap.loadFromData(data):
                    self.thumb.setPixmap(
                        pixmap.scaled(
                            160, 90, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
                        )
                    )
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

    def run_queue(self, ids=None):
        try:
            # Queued jobs already have validated output policies. Only current
            # session authentication applies when running them.
            options = Options(
                cookie_file=self.cookie_file.text(), cookie_browser=self.cookie_browser.currentText()
            ).validate()
            self.start_task(
                {
                    "action": "run",
                    "ids": ids if isinstance(ids, list) else None,
                    "db": str(self.store.path),
                    "auth": {"cookie_file": options.cookie_file, "cookie_browser": options.cookie_browser},
                }
            )
        except Exception as exc:
            self._error(exc)

    def selected_ids(self):
        table = self.library if self.tabs.currentIndex() == 2 else self.jobs
        return [
            table.item(row, 4).text()
            for row in sorted({i.row() for i in table.selectedIndexes()})
            if table.item(row, 4)
        ]

    def refresh_jobs(self):
        if not hasattr(self, "library"):
            return
        self.rows = self.store.rows()
        signature = (self.rows, self.status_filter.currentText(), self.search.text(), self.library_search.text())
        if signature == getattr(self, "_view_signature", None) and self.status_filter.currentText() != "Removed":
            self.update_actions()
            return
        self._view_signature = signature
        selected = set(self.selected_ids())
        choice = self.status_filter.currentText()
        query = self.search.text().casefold()

        def matches(job, text):
            return (
                text
                in " ".join(
                    str(v)
                    for v in (
                        job["candidate"]["title"],
                        job["candidate"]["url"],
                        job["options"].get("project", ""),
                        job["options"].get("tags", ""),
                        job["error"],
                    )
                ).casefold()
            )

        source = self.store.rows(include_removed=True) if choice == "Removed" else self.rows
        visible = [
            job
            for job in source
            if matches(job, query)
            and (
                job["removed"]
                if choice == "Removed"
                else job["status"] == choice
                if choice != "All active"
                else job["status"] != "completed"
            )
        ]
        self.jobs.setRowCount(len(visible))
        for row, job in enumerate(visible):
            scheduled = time.strftime("%b %d %H:%M", time.localtime(job["not_before"])) if job["not_before"] else "Now"
            values = [
                job["candidate"]["title"] or redact(job["candidate"]["url"]),
                job["status"],
                str(job["attempts"]),
                job["error"] or job["output"],
                job["id"],
                str(job["priority"]),
                scheduled,
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.jobs.setItem(row, col, item)
            if job["id"] in selected:
                self.jobs.selectionModel().select(
                    self.jobs.model().index(row, 0),
                    QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
                )
        counts = {
            state: sum(r["status"] == state for r in self.rows)
            for state in ("queued", "running", "failed", "cancelled", "completed")
        }
        self.queue_summary.setText(
            " · ".join(f"{n} {state}" for state, n in counts.items())
            if self.rows
            else "Your queue is empty. Add sources, inspect them, then queue the items you want."
        )
        saved = [
            j for j in self.rows if j["status"] == "completed" and matches(j, self.library_search.text().casefold())
        ]
        self.library.setRowCount(len(saved))
        for row, job in enumerate(saved):
            values = [
                job["candidate"]["title"] or "Untitled",
                job["options"].get("project", ""),
                job["options"].get("tags", ""),
                job["output"],
                job["id"],
            ]
            for col, value in enumerate(values):
                self.library.setItem(row, col, QTableWidgetItem(value))
            if job["id"] in selected:
                self.library.selectionModel().select(
                    self.library.model().index(row, 0),
                    QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
                )
        self.update_actions()
        self.library_summary.setText(
            f"{len(saved)} saved item(s). Double-click to preview, mark a clip or transcribe."
            if saved
            else "Your saved media will appear here after a download completes. Sources and checksums travel with every bundle."
        )

    def retry_selected(self):
        self.store.retry(self.selected_ids())
        self.refresh_jobs()

    def remove_selected(self):
        self.last_removed = self.selected_ids()
        self.store.remove(self.last_removed)
        self.refresh_jobs()

    def open_output(self):
        ids = set(self.selected_ids())
        for job in self.rows:
            if job["id"] in ids and job["output"] and Path(job["output"]).is_dir():
                QDesktopServices.openUrl(QUrl.fromLocalFile(job["output"]))
                return
        self.status.setText("Select a completed job with an existing output folder.")

    def export_manifest(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export library manifest", "videobot-library.json", "JSON (*.json);;CSV (*.csv)"
        )
        if not path:
            return
        try:
            count = export_library(self.store.rows(), path)
            self.status.setText(f"Exported {count} completed items.")
        except Exception as exc:
            self._error(exc)

    def on_event(self, event):
        kind = event["type"]
        if kind == "candidate":
            self.add_candidate(event["candidate"])
        elif kind == "discovery_error":
            self.failed_urls.append(event["url"])
            self.log.appendPlainText(f"Skipped {event['url']}: {event['message']}")
        elif kind == "diagnostics":
            self.last_report = event["report"]
            self.log.appendPlainText(json.dumps(self.last_report, indent=2))
            self.log_toggle.setChecked(True)
        elif kind == "verification":
            self.log.appendPlainText(f"{event['job_id']}: {'Verified' if event['ok'] else '; '.join(event['errors'])}")
            self.log_toggle.setChecked(True)
        elif kind == "relink":
            self.log.appendPlainText(
                f"{event['job_id']}: " + ("Relinked to " + event["output"] if event["ok"] else event["error"])
            )
            self.log_toggle.setChecked(True)
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
            if self.worker and self.worker.request.get("action") == "doctor" and self.last_report:
                missing = [k for k in ("ffmpeg", "ffprobe") if not self.last_report["tools"].get(k)]
                summary = (
                    "Missing: " + ", ".join(missing) + ". Choose a tools folder in Settings."
                    if missing
                    else "Media tools found. Browser "
                    + ("ready." if self.last_report.get("chromium") else "unavailable; see Help for installation.")
                )
            self.status.setText(event.get("message") or summary)
            self.log.appendPlainText(self.status.text())
            self.refresh_jobs()

    def task_finished(self):
        finished = self.worker
        self.worker = None
        if finished:
            if finished.request.get("action") == "run" and self.notifications.isChecked() and self.tray.isVisible():
                self.tray.showMessage("VideoBot", self.status.text(), QSystemTrayIcon.MessageIcon.Information, 5000)
            finished.deleteLater()
        self.run_btn.setEnabled(True)
        self.inspect_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.refresh_jobs()
        if self.closing:
            QTimer.singleShot(0, self.close)

    def show_diagnostics(self):
        self.status.setText("Checking tools and browser in the background…")
        self.start_task({"action": "doctor"})

    def focus_urls(self):
        self.tabs.setCurrentIndex(0)
        self.urls.setFocus()

    def focus_search(self):
        self.tabs.setCurrentIndex(1)
        self.search.setFocus()

    def update_context(self, *_):
        if not hasattr(self, "output_summary"):
            return
        self.update_actions()
        self.output_summary.setText(
            f"Save to: {self.destination.text()}  ·  {self.audio_format.currentText().upper() if self.audio.isChecked() else self.quality.currentText() + ' / ' + self.container.currentText()}"
        )

    def update_actions(self, *_):
        if not hasattr(self, "library") or not hasattr(self, "rows"):
            return
        busy = bool(self.worker and self.worker.isRunning())
        ids = set(self.selected_ids())
        selected = [r for r in self.rows if r["id"] in ids]
        policies = {
            "run_queue": not busy and any(r["status"] == "queued" for r in self.rows),
            "run_selected": not busy and any(r["status"] == "queued" for r in selected),
            "retry_selected": any(r["status"] in ("failed", "cancelled") for r in selected),
            "edit_selected": len(selected) == 1 and selected[0]["status"] in ("queued", "failed", "cancelled"),
            "remove_selected": any(r["status"] != "running" for r in selected),
            "restore_selected": bool(ids) and self.status_filter.currentText() == "Removed",
            "undo_remove": bool(self.last_removed),
            "play_selected": any(r["status"] == "completed" for r in selected),
            "open_output": any(r["output"] for r in selected),
            "verify_selected": not busy and any(r["status"] == "completed" for r in selected),
            "show_diagnostics": not busy,
            "relink_selected": not busy and any(r["status"] == "completed" for r in selected),
            "queue_selected": any(
                self.preview.item(i, 0) and self.preview.item(i, 0).checkState() == Qt.CheckState.Checked
                for i in range(self.preview.rowCount())
            ),
            "inspect": not busy,
            "organize_selected": any(r["status"] != "running" for r in selected),
        }
        for action, enabled in policies.items():
            for button in self.action_buttons.get(action, []):
                button.setEnabled(enabled)

    def apply_theme(self, *_):
        theme = self.theme.currentText()
        self.setStyleSheet(
            STYLE
            if theme == "Dark"
            else "QPushButton {padding:7px;} QLineEdit {padding:4px;}"
            if theme == "Light"
            else ""
        )
        if theme == "Light":
            from PySide6.QtGui import QPalette, QColor

            palette = self.style().standardPalette()
            palette.setColor(QPalette.ColorRole.Window, QColor("#f5f6fa"))
            palette.setColor(QPalette.ColorRole.WindowText, QColor("#172033"))
            palette.setColor(QPalette.ColorRole.Base, QColor("white"))
            palette.setColor(QPalette.ColorRole.Text, QColor("#172033"))
            palette.setColor(QPalette.ColorRole.ButtonText, QColor("#172033"))
            self.setPalette(palette)
        else:
            self.setPalette(QApplication.palette())
        self.store.set_setting("theme", theme)

    def choose_tools(self):
        path = QFileDialog.getExistingDirectory(self, "Folder containing FFmpeg and ffprobe")
        if path:
            self.tool_path.setText(path)
            self.set_tool_path()
            self.show_diagnostics()

    def set_tool_path(self):
        original = getattr(self, "original_path", os.environ.get("PATH", ""))
        self.original_path = original
        folder = self.tool_path.text().strip()
        os.environ["PATH"] = folder + os.pathsep + original if folder and Path(folder).is_dir() else original
        self.store.set_setting("tool_path", folder)

    def run_selected(self):
        ids = self.selected_ids()
        if ids:
            self.run_queue(ids)
        else:
            self.status.setText("Select one or more queued items first.")

    def scheduler_tick(self):
        if self._store_closed or self.closing or (self.worker and self.worker.isRunning()):
            return
        self.refresh_jobs()
        if self.auto_run.isChecked() and any(
            j["status"] == "queued" and j["not_before"] <= time.time() for j in self.store.rows()
        ):
            self.run_queue()

    def stop(self):
        self.auto_run.setChecked(False)
        if self.worker:
            self.worker.stop()
            self.stop_btn.setEnabled(False)
            self.status.setText("Stopping safely… unfinished jobs can be retried.")

    def edit_selected(self):
        ids = self.selected_ids()
        job = next((r for r in self.rows if r["id"] in ids), None)
        if len(ids) != 1 or not job or job["status"] not in ("queued", "failed", "cancelled"):
            self.status.setText("Select one queued, failed or cancelled job to edit.")
            return
        try:
            self.before_edit = self.options().public_dict()
        except ValueError:
            self.before_edit = self.store.setting("options", Options().public_dict())
        self.editing_job = job["id"]
        self._load_options(job["options"])
        self.apply_edit_btn.setVisible(True)
        self.cancel_edit_btn.setVisible(True)
        self.tabs.setCurrentIndex(3)
        self.status.setText("Editing " + (job["candidate"]["title"] or job["id"]) + ". Apply changes when ready.")

    def cancel_job_edit(self):
        self.editing_job = None
        self._load_options(self.before_edit)
        self.apply_edit_btn.setVisible(False)
        self.cancel_edit_btn.setVisible(False)
        self.tabs.setCurrentIndex(1)
        self.status.setText("Job edit cancelled; queued settings were preserved.")

    def apply_job_edit(self):
        try:
            self.store.edit(self.editing_job, self.options())
            self.editing_job = None
            self.apply_edit_btn.setVisible(False)
            self.cancel_edit_btn.setVisible(False)
            self.refresh_jobs()
            self.tabs.setCurrentIndex(1)
            self.status.setText("Job settings updated. Retry failed/cancelled items when ready.")
        except Exception as exc:
            self._error(exc)

    def organize_selected(self):
        ids = self.selected_ids()
        if not ids:
            self.status.setText("Select jobs to prioritize or schedule.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Priority and schedule")
        form = QFormLayout(dialog)
        priority = QSpinBox()
        priority.setRange(-100, 100)
        form.addRow("Priority (higher runs first)", priority)
        date = QDateTimeEdit(QDateTime.currentDateTime())
        date.setCalendarPopup(True)
        date.setDisplayFormat("yyyy-MM-dd HH:mm")
        form.addRow("Earliest start (local time)", date)
        form.addRow(QLabel("Enable automatic run in Queue to start due jobs while VideoBot is open."))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec():
            self.store.organize(ids, priority.value(), date.dateTime().toSecsSinceEpoch())
            self.refresh_jobs()

    def undo_remove(self):
        self.store.restore(self.last_removed)
        self.last_removed = []
        self.refresh_jobs()

    def restore_selected(self):
        self.store.restore(self.selected_ids())
        self.refresh_jobs()

    def play_selected(self):
        try:
            job = next((r for r in self.rows if r["id"] in self.selected_ids() and r["status"] == "completed"), None)
            if job:
                from .player import MediaDialog

                dialog = MediaDialog(self, job)
                dialog.exec()
                dialog.deleteLater()
            else:
                self.status.setText("Select a completed item with an existing media file.")
        except Exception as exc:
            self._error(exc)

    def relink_selected(self):
        ids = [j["id"] for j in self.rows if j["id"] in self.selected_ids() and j["status"] == "completed"]
        if not ids:
            return
        folder = QFileDialog.getExistingDirectory(self, "Choose moved bundle or its new parent folder")
        if folder:
            self.start_task({"action": "relink", "db": str(self.store.path), "ids": ids, "root": folder})

    def search_transcripts(self):
        from .player import TranscriptSearch

        dialog = TranscriptSearch(self)
        dialog.exec()
        dialog.deleteLater()

    def verify_selected(self):
        jobs = [r for r in self.rows if r["id"] in self.selected_ids() and r["status"] == "completed"]
        if jobs:
            self.start_task({"action": "verify", "jobs": jobs})
        else:
            self.status.setText("Select completed items to verify.")

    def clean_partials(self):
        from .maintenance import staging

        try:
            ids = self.selected_ids()
            inventory = staging(self.store, ids)
            if not inventory:
                self.status.setText("No retained partial files for the selected jobs.")
                return
            details = "\n".join(f"{r['path']} ({r['bytes'] / 1024**2:.1f} MiB)" for r in inventory)
            if (
                QMessageBox.question(
                    self,
                    "Remove selected partial downloads?",
                    details + "\n\nCompleted media is retained. These jobs will download again from the beginning.",
                )
                == QMessageBox.StandardButton.Yes
            ):
                staging(self.store, ids, delete=True)
                self.status.setText("Removed selected idle jobs' partial downloads.")
        except Exception as exc:
            self._error(exc)

    def backup_queue(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Back up queue (contains private source links)", "videobot-backup.sqlite3", "Database (*.sqlite3)"
        )
        if path:
            try:
                self.store.backup(path)
                self.status.setText("Backed up queue and profiles. Media files are separate.")
            except Exception as exc:
                self._error(exc)

    def export_support(self):
        if not self.last_report:
            self.status.setText("Run Check dependencies first, then export the report.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export redacted diagnostics", "videobot-support.json", "JSON (*.json)"
        )
        if path:
            try:
                Path(path).write_text(
                    json.dumps(
                        public_data({"diagnostics": self.last_report, "activity": self.log.toPlainText()}), indent=2
                    ),
                    encoding="utf-8",
                )
            except Exception as exc:
                self._error(exc)

    def retry_inspection(self):
        if not self.failed_urls:
            self.status.setText("No failed URLs from the last inspection.")
            return
        self.urls.setPlainText("\n".join(self.failed_urls))
        self.status.setText("Failed links copied. Re-enter any signed query credentials before inspecting again.")

    def delete_profile(self):
        profiles = self.store.setting("profiles", {})
        profiles.pop(self.profile.currentText(), None)
        self.store.set_setting("profiles", profiles)
        self._refresh_profiles()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event):
        data = event.mimeData()
        text = (
            "\n".join(u.toString() for u in data.urls() if u.scheme() in ("http", "https"))
            if data.hasUrls()
            else data.text()
        )
        if text.strip():
            self.urls.appendPlainText(text[: 1024 * 1024])
            self.focus_urls()
            event.acceptProposedAction()

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
        previous = self._thumbnail_reply
        self._thumbnail_reply = None
        if previous:
            previous.abort()
        try:
            self.store.set_setting("options", self.options().public_dict())
        except ValueError:
            pass
        self.store.set_setting("notifications", self.notifications.isChecked())
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
        smoke_job = os.environ.get("VIDEOBOT_SMOKE_JOB")
        if smoke_job:
            from .player import MediaDialog

            job = next(j for j in window.store.rows() if j["id"] == smoke_job)
            preview = MediaDialog(window, job)
            preview.show()
            preview.player.play()

            def capture():
                ok = preview.player.duration() > 0 and preview.player.position() > 0
                preview.grab().save(smoke_image)
                preview.close()
                window.close()
                app.exit(0 if ok else 1)

            QTimer.singleShot(2000, capture)
        else:

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
