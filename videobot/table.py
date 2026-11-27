"""Paged native controls with job-ID selection, avoiding Qt's virtual AX cell cache."""

from types import SimpleNamespace
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QItemSelectionModel, QSignalBlocker, Signal, QEvent
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QCheckBox, QLabel, QPushButton


class RowsModel(QAbstractTableModel):
    def __init__(self, columns, parent=None):
        super().__init__(parent)
        self.columns, self.values = columns, []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.values)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else self.columns

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if index.isValid() and role == Qt.ItemDataRole.DisplayRole:
            return self.values[index.row()][index.column()]


class StableTable(QWidget):
    """Reuse at most 100 ordinary checkbox rows; no native virtual table cells."""

    doubleClicked = Signal(QModelIndex)
    PAGE_SIZE = 100

    def __init__(self, columns):
        super().__init__()
        self._model = RowsModel(columns, self)
        self._selection = QItemSelectionModel(self._model, self)
        self._selection.selectionChanged.connect(self._sync_checks)
        self._items, self._slots, self._labels = {}, [], []
        self._page = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        content = QWidget()
        self._list = QVBoxLayout(content)
        self._list.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._list.setSpacing(4)
        self.scroll.setWidget(content)
        layout.addWidget(self.scroll, 1)
        footer = QHBoxLayout()
        self.previous = QPushButton("Previous 100")
        self.previous.clicked.connect(lambda: self._change_page(-1))
        self.next = QPushButton("Next 100")
        self.next.clicked.connect(lambda: self._change_page(1))
        self.page_label = QLabel()
        footer.addWidget(self.previous)
        footer.addWidget(self.page_label, 1)
        footer.addWidget(self.next)
        layout.addLayout(footer)
        self._render()

    def model(self):
        return self._model

    def selectionModel(self):
        return self._selection

    def selectedIndexes(self):
        return self._selection.selectedIndexes()

    def setHorizontalHeaderLabels(self, labels):
        self._labels = labels

    def rowCount(self):
        return len(self._model.values)

    def item(self, row, column):
        if not 0 <= row < self.rowCount():
            return None
        value = self._model.values[row][column]
        key = (self._model.values[row][4], column, value)
        if key not in self._items:
            self._items[key] = SimpleNamespace(text=lambda: value)
        return self._items[key]

    def selectRow(self, row):
        self._selection.select(
            self._model.index(row, 0),
            QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows,
        )

    def replace_rows(self, values):
        selected = {self._model.values[i.row()][4] for i in self._selection.selectedRows()}
        old_ids = [v[4] for v in self._model.values]
        new_ids = [v[4] for v in values]
        # This model stores selection only. Native accessibility sees ordinary
        # checkbox/label widgets, never virtual cells tied to model row indexes.
        with QSignalBlocker(self._selection):
            self._model.beginResetModel()
            self._model.values = values
            self._model.endResetModel()
            for row, value in enumerate(values):
                if value[4] in selected:
                    self._selection.select(
                        self._model.index(row, 0),
                        QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
                    )
        if old_ids != new_ids:
            self._page = 0
        incoming = {value[4]: value for value in values}
        self._items = {k: v for k, v in self._items.items() if k[0] in incoming and incoming[k[0]][k[1]] == k[2]}
        self._render()

    def _change_page(self, delta):
        self._page = max(0, min(self._page + delta, max(0, (self.rowCount() - 1) // self.PAGE_SIZE)))
        self._render()
        self.scroll.verticalScrollBar().setValue(0)

    def _toggle(self, slot, checked):
        row = self._page * self.PAGE_SIZE + slot
        if row >= self.rowCount():
            return
        flag = QItemSelectionModel.SelectionFlag.Select if checked else QItemSelectionModel.SelectionFlag.Deselect
        self._selection.select(self._model.index(row, 0), flag | QItemSelectionModel.SelectionFlag.Rows)

    def _sync_checks(self, *_):
        selected = {i.row() for i in self._selection.selectedRows()}
        for slot, (widget, check, title, details) in enumerate(self._slots):
            with QSignalBlocker(check):
                check.setChecked(self._page * self.PAGE_SIZE + slot in selected)
        count = len(selected)
        start = self._page * self.PAGE_SIZE
        self.page_label.setText(
            f"{start + 1 if self.rowCount() else 0}–{min(start + self.PAGE_SIZE, self.rowCount())} of {self.rowCount()} · {count} selected"
        )

    def _render(self):
        start = self._page * self.PAGE_SIZE
        values = self._model.values[start : start + self.PAGE_SIZE]
        while len(self._slots) < len(values):
            slot = len(self._slots)
            widget = QWidget()
            row = QHBoxLayout(widget)
            row.setContentsMargins(8, 6, 8, 6)
            check = QCheckBox()
            check.setFixedWidth(24)
            check.toggled.connect(lambda checked, n=slot: self._toggle(n, checked))
            text = QVBoxLayout()
            title, details = QLabel(), QLabel()
            for label in (title, details):
                label.setTextFormat(Qt.TextFormat.PlainText)
                label.setWordWrap(True)
                label.setProperty("slot", slot)
                label.installEventFilter(self)
                text.addWidget(label)
            title.setStyleSheet("font-weight:600;")
            row.addWidget(check)
            row.addLayout(text, 1)
            widget.setProperty("slot", slot)
            widget.installEventFilter(self)
            self._list.addWidget(widget)
            self._slots.append((widget, check, title, details))
        for slot, (widget, check, title, details) in enumerate(self._slots):
            widget.setVisible(slot < len(values))
            if slot >= len(values):
                continue
            value = values[slot]
            title.setText(value[0])
            check.setAccessibleName("Select " + value[0])
            detail = " · ".join(f"{self._labels[c]}: {value[c]}" for c in range(1, len(value)) if c != 4 and value[c])
            details.setText(detail[:400] + ("…" if len(detail) > 400 else ""))
            details.setToolTip(detail)
        self.previous.setEnabled(self._page > 0)
        self.next.setEnabled(start + self.PAGE_SIZE < self.rowCount())
        self._sync_checks()

    def eventFilter(self, target, event):
        row = self._page * self.PAGE_SIZE + int(target.property("slot") or 0)
        if row < self.rowCount() and event.type() == QEvent.Type.MouseButtonRelease:
            if event.button() == Qt.MouseButton.LeftButton:
                if event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier):
                    selected = self._selection.isRowSelected(row)
                    self._toggle(row - self._page * self.PAGE_SIZE, not selected)
                else:
                    self.selectRow(row)
                return True
        if row < self.rowCount() and event.type() == QEvent.Type.MouseButtonDblClick:
            self.selectRow(row)
            self.doubleClicked.emit(self._model.index(row, 0))
            return True
        return super().eventFilter(target, event)
