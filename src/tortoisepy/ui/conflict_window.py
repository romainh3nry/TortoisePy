"""Résoudre les conflits d'une fusion — §6 de la spec phase 8.

Une liste de fichiers, un choix par fichier, et **toujours** un bouton
« Abort » : c'est lui qui rend le reste acceptable, puisqu'il garantit
qu'on ne peut pas rester coincé.
"""

from __future__ import annotations

import pygit2
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tortoisepy.core import operations
from tortoisepy.core.conflicts import (
    Side,
    conclude_merge,
    list_conflicts,
    resolve_with,
)
from tortoisepy.ui.diff_view import DiffView
from tortoisepy.ui.dialogs import show_error

PATH_ROLE = Qt.ItemDataRole.UserRole


class ConflictWindow(QMainWindow):
    """Choisir un camp, fichier par fichier."""

    finished = Signal(object)
    """`OperationResult` — la fenêtre principale rafraîchit le graphe."""

    def __init__(self, repository: pygit2.Repository, parent=None):
        super().__init__(parent)
        self.repository = repository

        self._files = QTreeWidget()
        self._files.setColumnCount(2)
        self._files.setHeaderLabels(("Fichier", "État"))
        self._files.setRootIsDecorated(False)
        self._files.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._files.itemSelectionChanged.connect(self._on_file_selected)

        self.diff_view = DiffView()

        self.mine_button = QPushButton("Keep mine")
        self.mine_button.clicked.connect(self.keep_mine)
        self.theirs_button = QPushButton("Take theirs")
        self.theirs_button.clicked.connect(self.take_theirs)
        self.resolve_button = QPushButton("Resolve")
        self.resolve_button.clicked.connect(self.resolve)
        self.abort_button = QPushButton("Abort")
        self.abort_button.clicked.connect(self.abort)

        buttons = QHBoxLayout()
        buttons.addWidget(self.mine_button)
        buttons.addWidget(self.theirs_button)
        buttons.addStretch(1)
        buttons.addWidget(self.abort_button)
        buttons.addWidget(self.resolve_button)

        bottom = QWidget()
        layout = QVBoxLayout(bottom)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(buttons)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self._files)
        splitter.addWidget(self.diff_view)
        splitter.addWidget(bottom)
        splitter.setStretchFactor(1, 3)

        self.setCentralWidget(splitter)
        self.setWindowTitle("Resolve conflicts")
        self.resize(900, 700)

        self.refresh()

    def refresh(self) -> None:
        self._files.clear()
        self.diff_view.clear()

        for conflict in list_conflicts(self.repository):
            if conflict.is_delete_modify:
                etat = "supprimé d'un côté"
            elif conflict.is_binary:
                etat = "binaire"
            else:
                etat = "modifié des deux côtés"

            item = QTreeWidgetItem([conflict.path, etat])
            item.setData(0, PATH_ROLE, conflict.path)
            self._files.addTopLevelItem(item)

        if self._files.topLevelItemCount():
            self._files.setCurrentItem(self._files.topLevelItem(0))

        self._update_buttons()

    def file_count(self) -> int:
        return self._files.topLevelItemCount()

    def select_file(self, path: str) -> None:
        for index in range(self._files.topLevelItemCount()):
            item = self._files.topLevelItem(index)
            if item.data(0, PATH_ROLE) == path:
                self._files.setCurrentItem(item)
                return

    def keep_mine(self) -> None:
        self._resolve_current(Side.OURS)

    def take_theirs(self) -> None:
        self._resolve_current(Side.THEIRS)

    def resolve(self) -> None:
        """Conclut la fusion une fois tout résolu."""
        result = conclude_merge(self.repository)
        self.finished.emit(result)
        if not result.success:
            show_error(self, result)
            self.refresh()
            return
        self.close()

    def abort(self) -> None:
        """Rend la main : restaure l'état d'avant la fusion.

        La sortie de secours, toujours disponible — c'est elle qui garantit
        qu'un conflit n'est jamais une impasse.
        """
        result = operations.abort_operation(self.repository)
        self.finished.emit(result)
        if not result.success:
            show_error(self, result)
            return
        self.close()

    def _resolve_current(self, side: Side) -> None:
        item = self._files.currentItem()
        if item is None:
            return
        result = resolve_with(self.repository, item.data(0, PATH_ROLE), side)
        if not result.success:
            show_error(self, result)
        self.refresh()

    def _on_file_selected(self) -> None:
        item = self._files.currentItem()
        if item is None:
            self.diff_view.clear()
            return
        self.diff_view.show_diff(
            _conflict_preview(self.repository, item.data(0, PATH_ROLE))
        )

    def _update_buttons(self) -> None:
        remaining = self.file_count()
        # Conclure avec un conflit restant produirait un commit contenant
        # des marqueurs `<<<<<<<` (règle de la phase 6).
        self.resolve_button.setEnabled(remaining == 0)
        self.mine_button.setEnabled(remaining > 0)
        self.theirs_button.setEnabled(remaining > 0)


def _conflict_preview(repo: pygit2.Repository, path: str):
    """Le fichier tel qu'il est, marqueurs compris.

    Montrer le fichier de travail plutôt qu'un diff reconstruit : c'est ce
    que l'utilisateur verra dans son éditeur, donc ce qu'il reconnaît.
    """
    import os

    from tortoisepy.core.changes import DiffHunk, DiffLine, FileDiff

    full = os.path.join(repo.workdir or "", path)
    try:
        with open(full, encoding="utf-8", errors="replace") as handle:
            contenu = handle.read().splitlines()
    except OSError:
        return FileDiff(path=path)

    return FileDiff(
        path=path,
        hunks=(DiffHunk(header=f"@@ {path} @@", lines=_colour(contenu)),),
    )


def _colour(lines: list[str]) -> tuple:
    """Marque le bloc local comme un ajout et le bloc distant comme un retrait.

    `DiffView` colore déjà `+` en vert et `-` en rouge : en réutilisant ces
    origines, l'utilisateur voit d'un coup d'œil quelle moitié vient de chez
    lui. Les lignes de marqueur elles-mêmes restent neutres.
    """
    from tortoisepy.core.changes import DiffLine

    coloured = []
    side = " "
    for line in lines:
        if line.startswith("<<<<<<<"):
            side = "+"          # début de NOTRE version
            coloured.append(DiffLine(origin=" ", content=line))
            continue
        if line.startswith("======="):
            side = "-"          # bascule vers LEUR version
            coloured.append(DiffLine(origin=" ", content=line))
            continue
        if line.startswith(">>>>>>>"):
            side = " "
            coloured.append(DiffLine(origin=" ", content=line))
            continue
        coloured.append(DiffLine(origin=side, content=line))
    return tuple(coloured)
