"""Embedded preview, persistent clip markers, and timed transcript navigation."""

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, QTimer
from PySide6.QtGui import QColor, QPainter, QDesktopServices
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QDoubleSpinBox,
    QFileDialog,
    QComboBox,
    QCheckBox,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QWidget,
)

from .library import playable
from .media_tools import timestamp, MODELS
from .runtime import configure_audio_backend


class Timeline(QSlider):
    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.markers = (0, 0)
        self.setAccessibleName("Playback timeline with In and Out markers")
        self.setMinimumHeight(26)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.maximum() <= 0:
            return
        painter = QPainter(self)
        painter.setPen(QColor("#bfabff"))
        for label, position in zip(("I", "O"), self.markers):
            x = 10 + int((self.width() - 20) * position / max(1, self.maximum()))
            painter.drawLine(x, 0, x, self.height())
            painter.drawText(max(0, min(x + 2, self.width() - 12)), 11, label)
        painter.end()


class MediaDialog(QDialog):
    def __init__(self, window, job, position=0):
        super().__init__(window)
        self.window, self.job = window, job
        self.setWindowTitle("VideoBot — Preview, clip and transcribe")
        self.resize(1000, 760)
        self.setMinimumSize(680, 560)
        self.pending_seek = int(position * 1000)
        self.loaded = False
        layout = QVBoxLayout(self)
        title = QLabel(job["candidate"]["title"])
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setWordWrap(True)
        layout.addWidget(title)
        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        self.video = QVideoWidget()
        self.video.setMinimumSize(240, 170)
        left_layout.addWidget(self.video, 1)
        configure_audio_backend()
        self.audio = QAudioOutput(self)
        self.audio.setVolume(0.8)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        self.timeline = Timeline()
        self.timeline.sliderMoved.connect(self.player.setPosition)
        left_layout.addWidget(self.timeline)
        controls = QHBoxLayout()
        self.play_button = QPushButton("Play")
        self.play_button.clicked.connect(self.toggle_play)
        controls.addWidget(self.play_button)
        self.clock = QLabel("00:00:00.000")
        controls.addWidget(self.clock)
        controls.addWidget(QLabel("Volume"))
        volume = QSlider(Qt.Orientation.Horizontal)
        volume.setRange(0, 100)
        volume.setValue(80)
        volume.setMaximumWidth(100)
        volume.valueChanged.connect(lambda value: self.audio.setVolume(value / 100))
        controls.addWidget(volume)
        left_layout.addLayout(controls)
        markers = QHBoxLayout()
        self.mark_in, self.mark_out = QDoubleSpinBox(), QDoubleSpinBox()
        saved = window.store.setting("markers:" + job["id"], [0, 0])
        for label, spin, value in zip(("In", "Out"), (self.mark_in, self.mark_out), saved):
            spin.setDecimals(3)
            spin.setRange(0, 8640000)
            spin.setSuffix(" s")
            spin.setValue(value)
            button = QPushButton("Mark " + label)
            button.clicked.connect(lambda checked=False, control=spin: control.setValue(self.player.position() / 1000))
            markers.addWidget(button)
            markers.addWidget(spin)
            spin.valueChanged.connect(self.markers_changed)
        left_layout.addLayout(markers)
        self.clip_button = QPushButton("Export marked clip…")
        self.clip_button.clicked.connect(self.export_clip)
        left_layout.addWidget(self.clip_button)
        split.addWidget(left)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(QLabel("Local transcript · click a line to seek"))
        self.model = QComboBox()
        self.model.addItems(MODELS)
        self.model.setToolTip("Tiny: fastest. Base: balanced. Small: more accurate, slower. CPU only.")
        right_layout.addWidget(self.model)
        self.allow_download = QCheckBox("Allow model download on first use")
        self.allow_download.setToolTip(
            "Downloads open Whisper weights from Hugging Face. Audio stays on this computer. Tiny ~75 MB; base ~145 MB; small ~485 MB."
        )
        right_layout.addWidget(self.allow_download)
        self.transcribe_button = QPushButton("Transcribe locally")
        self.transcribe_button.clicked.connect(self.transcribe)
        right_layout.addWidget(self.transcribe_button)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Find words in this transcript…")
        self.filter.textChanged.connect(self.load_transcript)
        right_layout.addWidget(self.filter)
        self.lines = QListWidget()
        self.lines.setWordWrap(True)
        self.lines.setSpacing(6)
        self.lines.itemClicked.connect(
            lambda item: self.player.setPosition(int(item.data(Qt.ItemDataRole.UserRole) * 1000))
        )
        right_layout.addWidget(self.lines, 1)
        self.open_transcript = QPushButton("Open TXT / VTT / JSON folder")
        self.open_transcript.clicked.connect(self.open_sidecars)
        right_layout.addWidget(self.open_transcript)
        note = QLabel("Automatic transcripts can contain errors. Review them before publishing.")
        note.setWordWrap(True)
        right_layout.addWidget(note)
        split.addWidget(right)
        split.setSizes([610, 330])
        layout.addWidget(split, 1)
        self.message = QLabel("Loading media…")
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        footer = QHBoxLayout()
        self.stop_button = QPushButton("Stop background task")
        self.stop_button.clicked.connect(window.stop)
        footer.addWidget(self.stop_button)
        close = QPushButton("Close preview")
        close.clicked.connect(self.close)
        footer.addWidget(close)
        layout.addLayout(footer)
        self.player.durationChanged.connect(self.duration_changed)
        self.player.positionChanged.connect(self.position_changed)
        self.player.playbackStateChanged.connect(
            lambda state: self.play_button.setText(
                "Pause" if state == QMediaPlayer.PlaybackState.PlayingState else "Play"
            )
        )
        self.player.errorOccurred.connect(
            lambda error, message: self.message.setText("Playback unavailable: " + message)
        )
        self.player.mediaStatusChanged.connect(self.media_status)
        path = playable(job)
        if not path:
            raise ValueError("Media is missing; relink the bundle first.")
        self.player.setSource(QUrl.fromLocalFile(str(path.resolve())))
        self.load_transcript()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.sync_task)
        self.timer.start(300)
        self.markers_changed()
        self.sync_task()

    def media_status(self, status):
        if status == QMediaPlayer.MediaStatus.LoadedMedia and not self.loaded:
            self.loaded = True
            self.player.setPosition(self.pending_seek)
            self.message.setText("Ready. Mark a range to export a new clip; the original is preserved.")

    def duration_changed(self, duration):
        if duration <= 0:
            return
        self.timeline.setRange(0, duration)
        for spin in (self.mark_in, self.mark_out):
            spin.setMaximum(duration / 1000)
        if not self.mark_out.value():
            self.mark_out.setValue(duration / 1000)
        self.markers_changed()

    def position_changed(self, position):
        if not self.timeline.isSliderDown():
            self.timeline.setValue(position)
        self.clock.setText(timestamp(position / 1000))

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def markers_changed(self, *_):
        values = [self.mark_in.value(), self.mark_out.value()]
        self.timeline.markers = tuple(int(v * 1000) for v in values)
        self.timeline.update()
        self.window.store.set_setting("markers:" + self.job["id"], values)

    def sync_task(self):
        busy = bool(self.window.worker and self.window.worker.isRunning())
        self.clip_button.setEnabled(not busy and self.loaded and self.mark_out.value() > self.mark_in.value())
        self.transcribe_button.setEnabled(not busy and self.loaded)
        self.stop_button.setEnabled(busy)
        if busy:
            self.message.setText(self.window.status.text())
        elif getattr(self, "was_busy", False):
            self.message.setText(self.window.status.text())
            self.load_transcript()
        self.was_busy = busy

    def export_clip(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Choose destination for a new clip bundle", str(Path(self.job["output"]).parent)
        )
        if folder:
            self.player.pause()
            self.window.start_task(
                {
                    "action": "clip",
                    "db": str(self.window.store.path),
                    "job_id": self.job["id"],
                    "start": self.mark_in.value(),
                    "end": self.mark_out.value(),
                    "destination": folder,
                }
            )

    def transcribe(self):
        self.player.pause()
        self.window.start_task(
            {
                "action": "transcribe",
                "db": str(self.window.store.path),
                "job_id": self.job["id"],
                "model": self.model.currentText(),
                "allow_download": self.allow_download.isChecked(),
            }
        )

    def load_transcript(self, *_):
        self.lines.clear()
        transcript = self.window.store.transcript(self.job["id"])
        self.open_transcript.setEnabled(bool(transcript))
        if not transcript:
            return
        query = self.filter.text().strip().casefold()
        for segment in transcript["segments"]:
            if query in segment["text"].casefold():
                item = QListWidgetItem(timestamp(segment["start"]) + "  " + segment["text"])
                item.setData(Qt.ItemDataRole.UserRole, segment["start"])
                self.lines.addItem(item)

    def open_sidecars(self):
        transcript = self.window.store.transcript(self.job["id"])
        if transcript:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.job["output"]) / transcript["folder"])))

    def done(self, result):
        self.timer.stop()
        self.player.stop()
        self.player.setSource(QUrl())
        super().done(result)


class TranscriptSearch(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.setWindowTitle("Search all library transcripts")
        self.resize(780, 500)
        layout = QVBoxLayout(self)
        query = QLineEdit()
        query.setPlaceholderText("Search spoken words across completed library items…")
        layout.addWidget(query)
        self.results = QListWidget()
        self.results.setWordWrap(True)
        self.results.setSpacing(6)
        layout.addWidget(self.results)
        note = QLabel("Up to 200 matches. Double-click a result to open its media at that timestamp.")
        note.setWordWrap(True)
        layout.addWidget(note)
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(250)
        query.textChanged.connect(lambda: timer.start())

        def search():
            self.results.clear()
            for row in window.store.search_transcripts(query.text()):
                item = QListWidgetItem(f"{row['title']} · {timestamp(row['start'])}\n{row['text']}")
                item.setData(Qt.ItemDataRole.UserRole, (row["job_id"], row["start"]))
                self.results.addItem(item)

        timer.timeout.connect(search)

        def open_result(item):
            job_id, position = item.data(Qt.ItemDataRole.UserRole)
            job = next((j for j in window.store.rows() if j["id"] == job_id), None)
            if job:
                try:
                    dialog = MediaDialog(window, job, position)
                    dialog.exec()
                    dialog.deleteLater()
                except Exception as exc:
                    window._error(exc)

        self.results.itemDoubleClicked.connect(open_result)
