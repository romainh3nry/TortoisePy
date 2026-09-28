"""Changements apportés par un commit déjà fait.

Ouverte au double-clic dans le panneau des commits. Strictement en
lecture seule : ce commit existe, il n'y a rien à stager ni à valider.
"""

from __future__ import annotations

import pygit2
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QLabel,
    QMainWindow,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tortoisepy.core.changes import FileDiff, changes_in_commit, diff_in_commit
from tortoisepy.core.commits import read_commit
from tortoisepy.ui.diff_view import DiffView

PATH_ROLE = Qt.ItemDataRole.UserRole


class CommitDetailWindow(QMainWindow):
    """Fichiers et lignes modifiés par un commit."""

    def __init__(self, repository: pygit2.Repository, oid: str, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.oid = oid

        self._header = QLabel()
        self._header.setWordWrap(True)
        self._header.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        self._files = QTreeWidget()
        self._files.setColumnCount(1)
        self._files.setHeaderLabels(("Fichier",))
        self._files.setRootIsDecorated(False)
        self._files.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._files.itemSelectionChanged.connect(self._on_file_selected)

        self.diff_view = DiffView()

        top = QWidget()
        layout = QVBoxLayout(top)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self._header)
        layout.addWidget(self._files)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(top)
        splitter.addWidget(self.diff_view)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        self.setCentralWidget(splitter)
        self.resize(900, 700)

        self._load()

    def _load(self) -> None:
        info = read_commit(self.repository, self.oid)

        if info is None:
            self._header.setText(f"Commit inconnu — {self.oid[:8]}")
            self.setWindowTitle("Commit inconnu")
            return

        self.setWindowTitle(f"{info.short_oid} — {info.summary}")
        self._header.setText(
            f"{info.short_oid}  ·  {info.author_name}  ·  "
            f"{info.when:%d/%m/%Y %H:%M}\n\n{info.message.strip()}"
        )

        for change in changes_in_commit(self.repository, self.oid):
            item = QTreeWidgetItem([f"{change.kind.value}  {change.path}"])
            item.setData(0, PATH_ROLE, change.path)
            # Pas de case à cocher : ce commit est déjà fait. `QTreeWidgetItem`
            # porte `ItemIsUserCheckable` par défaut ; il faut l'ôter
            # explicitement, sans quoi Qt réserverait la place d'une case
            # (vérifié).
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            self._files.addTopLevelItem(item)

        # Ouvrir sur un volet vide donnerait l'impression d'un bug.
        if self._files.topLevelItemCount():
            self._files.setCurrentItem(self._files.topLevelItem(0))
        else:
            # Un commit peut légitimement ne toucher aucun fichier
            # (`--allow-empty`, certains merges) : `_on_file_selected` ne se
            # déclenche alors jamais, faute de sélection. Un `FileDiff` sans
            # hunk réutilise le message que `DiffView` affiche déjà pour
            # « aucune modification » plutôt que de laisser le volet muet,
            # ce qui donnerait l'impression d'un bug — ce n'est pas une
            # erreur, donc pas question d'un message alarmant.
            self.diff_view.show_diff(FileDiff(path=""))

    def file_count(self) -> int:
        return self._files.topLevelItemCount()

    def header_text(self) -> str:
        return self._header.text()

    def item_for(self, path: str) -> QTreeWidgetItem | None:
        for index in range(self._files.topLevelItemCount()):
            item = self._files.topLevelItem(index)
            if item.data(0, PATH_ROLE) == path:
                return item
        return None

    def select_file(self, path: str) -> None:
        item = self.item_for(path)
        if item is not None:
            self._files.setCurrentItem(item)

    def _on_file_selected(self) -> None:
        item = self._files.currentItem()
        if item is None:
            self.diff_view.clear()
            return
        self.diff_view.show_diff(
            diff_in_commit(self.repository, self.oid, item.data(0, PATH_ROLE))
        )
