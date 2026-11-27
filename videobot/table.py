"""Value-based table model: no deleted QTableWidgetItems exposed to accessibility."""

from types import SimpleNamespace
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QItemSelectionModel
from PySide6.QtGui import QAccessible, QAccessibleEvent
from PySide6.QtWidgets import QTreeView, QAbstractItemView


class RowsModel(QAbstractTableModel):
    def __init__(self, columns, parent=None):
        super().__init__(parent)
        self.columns, self.values, self.headers = columns, [], []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.values)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else self.columns - 1

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if (
            index.isValid()
            and 0 <= index.row() < len(self.values)
            and role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole)
        ):
            return self.values[index.row()][index.column() if index.column() < 4 else index.column() + 1]

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            return (
                self.headers[section]
                if orientation == Qt.Orientation.Horizontal and section < len(self.headers)
                else str(section + 1)
            )


class StableTable(QTreeView):
    def __init__(self, columns):
        super().__init__()
        self.setModel(RowsModel(columns, self))
        self.setRootIsDecorated(False)
        self.setItemsExpandable(False)
        self.setUniformRowHeights(True)
        self.setAllColumnsShowFocus(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._items = {}

    def horizontalHeader(self):
        return self.header()

    def selectRow(self, row):
        visible = [r for r in range(self.model().rowCount()) if not self.isRowHidden(r, QModelIndex())]
        row = visible[row]
        self.selectionModel().select(
            self.model().index(row, 0),
            QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows,
        )

    def setHorizontalHeaderLabels(self, labels):
        self.model().headers = labels[:4] + labels[5:]

    def rowCount(self):
        return sum(not self.isRowHidden(r, QModelIndex()) for r in range(self.model().rowCount()))

    def item(self, row, column):
        if not 0 <= row < self.model().rowCount():
            return None
        key = (row, column)
        if key not in self._items:
            value = self.model().values[row][column]
            self._items[key] = SimpleNamespace(text=lambda: value)
        return self._items[key]

    def replace_rows(self, values):
        model = self.model()
        selected = {model.values[i.row()][4] for i in self.selectionModel().selectedRows()}
        scroll = self.verticalScrollBar().value()
        positions = {value[4]: row for row, value in enumerate(model.values)}
        incoming = {value[4]: value for value in values}
        additions = [value for value in values if value[4] not in positions]
        if additions:
            first = len(model.values)
            model.beginInsertRows(QModelIndex(), first, first + len(additions) - 1)
            model.values.extend(additions)
            model.endInsertRows()
        # Keep stable row identities for the lifetime of the view. Filtering hides
        # rows instead of deleting native accessible cell interfaces under Cocoa.
        self.clearSelection()
        for row, old in enumerate(model.values):
            value = incoming.get(old[4])
            self.setRowHidden(row, QModelIndex(), value is None)
            if value is not None and value != old:
                model.values[row] = value
                self._items = {k: v for k, v in self._items.items() if k[0] != row}
                model.dataChanged.emit(model.index(row, 0), model.index(row, model.columnCount() - 1))
            if value is not None and value[4] in selected:
                self.selectionModel().select(
                    model.index(row, 0),
                    QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
                )
        self.verticalScrollBar().setValue(scroll)
        QAccessible.updateAccessibility(QAccessibleEvent(self, QAccessible.Event.ObjectReorder))
