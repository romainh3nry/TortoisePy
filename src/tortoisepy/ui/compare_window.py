"""Comparer deux révisions — `git diff A B`.

L'entrée « Compare revisions » figurait au menu contextuel depuis le
début, active à la sélection de deux nœuds, et son gestionnaire était
`_not_available` : elle ne faisait **rien**. C'est le même défaut que
`show_log`, câblé quelques jours plus tôt.

Distincte de `CommitDetailWindow`, qui montre ce qu'un commit a changé
par rapport à SON PARENT : ici les deux points sont quelconques et
peuvent être éloignés de centaines de commits.

Fenêtre de **consultation** : elle ne modifie rien (§7.0).
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

from tortoisepy.core.changes import FileDiff, changes_between, diff_between
from tortoisepy.ui.diff_view import DiffView

PATH_ROLE = Qt.ItemDataRole.UserRole


class CompareWindow(QMainWindow):
    """Les fichiers qui diffèrent entre deux révisions, et leur diff."""

    def __init__(
        self,
        repository: pygit2.Repository,
        base: str,
        target: str,
        parent=None,
    ):
        super().__init__(parent)
        self.repository = repository
        self.base = base
        self.target = target

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

        haut = QWidget()
        layout = QVBoxLayout(haut)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self._header)
        layout.addWidget(self._files)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(haut)
        splitter.addWidget(self.diff_view)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        self.setCentralWidget(splitter)
        # Les deux abrégés au titre : sans eux, on ne sait plus ce qu'on
        # compare dès qu'une seconde fenêtre est ouverte.
        self.setWindowTitle(f"Compare — {base[:8]} … {target[:8]}")
        self.resize(900, 700)

        self._remplir()

    def file_count(self) -> int:
        return self._files.topLevelItemCount()

    def header_text(self) -> str:
        return self._header.text()

    def _remplir(self) -> None:
        changes = changes_between(self.repository, self.base, self.target)

        pluriel = "" if len(changes) == 1 else "s"
        self._header.setText(
            f"{self.base[:8]} → {self.target[:8]} — "
            f"{len(changes)} fichier{pluriel}"
        )

        for change in changes:
            item = QTreeWidgetItem([f"{change.kind.value}  {change.path}"])
            item.setData(0, PATH_ROLE, change.path)
            # Pas de case à cocher : rien n'est à sélectionner ici.
            # `QTreeWidgetItem` porte `ItemIsUserCheckable` par défaut, et
            # Qt réserverait la place d'une case sans ce retrait.
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            self._files.addTopLevelItem(item)

        if self._files.topLevelItemCount():
            self._files.setCurrentItem(self._files.topLevelItem(0))
        else:
            # Deux révisions identiques ne diffèrent en rien : un volet
            # muet donnerait l'impression d'un défaut, alors que c'est
            # une réponse légitime.
            self.diff_view.show_diff(FileDiff(path=""))

    def _on_file_selected(self) -> None:
        item = self._files.currentItem()
        if item is None:
            self.diff_view.clear()
            return
        self.diff_view.show_diff(
            diff_between(
                self.repository, self.base, self.target,
                item.data(0, PATH_ROLE),
            )
        )
