"""Panneau des commits — révèle ce que la compression masque (§4.2.1).

Double-cliquer un nœud affiche les commits que son arête entrante compresse :
exactement ce qu'annonce son étiquette (« 40 commits »), plus le commit du
nœud lui-même.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tortoisepy.core.commits import CommitInfo
from tortoisepy.ui import theme

COLUMNS = ("Commit", "Message", "Auteur", "Date")
"""Le message d'abord : c'est la colonne qu'on lit. Reléguée en dernier,
elle sortait du champ dès que le panneau était un peu étroit."""

MERGE_COLOR = QColor(110, 110, 150)
"""Les commits de merge sont teintés : ils structurent l'historique."""


class CommitPanel(QWidget):
    """Liste les commits d'un nœud, dans un volet latéral."""

    commit_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._title = QLabel("Double-cliquez un nœud pour voir ses commits")
        self._title.setWordWrap(True)
        font = self._title.font()
        font.setBold(True)
        self._title.setFont(font)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(len(COLUMNS))
        self._tree.setHeaderLabels(COLUMNS)
        self._tree.setRootIsDecorated(False)
        self._tree.setAlternatingRowColors(True)
        self._tree.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._tree.setFont(QFont(theme.NODE_FONT_FAMILY, 11))
        self._tree.itemSelectionChanged.connect(self._on_selection)

        header = self._tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)

        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self._title)
        layout.addWidget(self._tree)

    def show_commits(self, label: str, commits: tuple[CommitInfo, ...]) -> None:
        """Remplit le panneau pour un nœud donné."""
        self._tree.clear()

        count = len(commits)
        plural = "" if count == 1 else "s"
        self._title.setText(f"{label} — {count} commit{plural}")

        for commit in commits:
            item = QTreeWidgetItem(
                [
                    commit.short_oid,
                    commit.summary,
                    commit.author_name,
                    f"{commit.when:%d/%m/%y}",
                ]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, commit.oid)
            item.setToolTip(1, commit.message)

            if commit.is_merge:
                for column in range(len(COLUMNS)):
                    item.setForeground(column, MERGE_COLOR)

            self._tree.addTopLevelItem(item)

        if commits:
            self._tree.setCurrentItem(self._tree.topLevelItem(0))

    def clear(self) -> None:
        self._tree.clear()
        self._title.setText("Double-cliquez un nœud pour voir ses commits")

    def count(self) -> int:
        return self._tree.topLevelItemCount()

    def selected_oid(self) -> str | None:
        item = self._tree.currentItem()
        if item is None:
            return None
        return item.data(0, Qt.ItemDataRole.UserRole)

    def _on_selection(self) -> None:
        oid = self.selected_oid()
        if oid is not None:
            self.commit_selected.emit(oid)
