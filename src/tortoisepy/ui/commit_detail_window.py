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
    QMenu,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tortoisepy.core.changes import FileDiff, changes_in_commit, diff_in_commit
from tortoisepy.core.commits import read_commit
from tortoisepy.ui.blame_window import BlameWindow
from tortoisepy.ui.log_window import LogWindow
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
        self._files.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._files.customContextMenuRequested.connect(self._show_context_menu)

        self.diff_view = DiffView()

        # Fenêtres ouvertes depuis ce détail — un blâme, ou le détail d'un
        # commit atteint depuis un blâme (D28). Une liste, sinon le
        # ramasse-miettes détruirait la fenêtre aussitôt ouverte, faute de
        # toute autre référence (piège vécu en phase 6 avec
        # `main_window._detail_windows`).
        self.blame_windows: list[BlameWindow | "CommitDetailWindow"] = []

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

    def context_actions_for_row(self, index: int) -> tuple[str, ...]:
        """Entrées du menu contextuel pour la ligne `index` de `self._files`.

        Séparé du `QMenu` lui-même, pour qu'un test lise les entrées sans
        ouvrir un vrai menu (même principe que `build_menu_model` pour le
        graphe).
        """
        item = self._files.topLevelItem(index)
        if item is None:
            return ()
        return ("Blame", "File history")

    def _show_context_menu(self, position) -> None:
        item = self._files.itemAt(position)
        if item is None:
            return
        index = self._files.indexOfTopLevelItem(item)
        entries = self.context_actions_for_row(index)
        if not entries:
            return

        menu = QMenu(self)
        for entry in entries:
            action = menu.addAction(entry)
            if entry == "Blame":
                action.triggered.connect(
                    lambda checked=False, i=index: self.blame_row(i)
                )
            elif entry == "File history":
                action.triggered.connect(
                    lambda checked=False, i=index: self.log_row(i)
                )
        menu.exec(self._files.viewport().mapToGlobal(position))

    def blame_row(self, index: int) -> None:
        """Ouvre le blâme du fichier de la ligne `index`.

        Plusieurs fenêtres sont permises, comme pour `CommitDetailWindow`
        elle-même : elles sont en lecture seule, et comparer deux blâmes
        côte à côte est légitime. `self.blame_windows` retient chacune,
        sans quoi le ramasse-miettes la détruirait aussitôt ouverte.
        """
        item = self._files.topLevelItem(index)
        if item is None:
            return

        path = item.data(0, PATH_ROLE)
        window = BlameWindow(self.repository, path, self.oid, self)
        window.commit_activated.connect(self._open_commit_from_blame)
        self.blame_windows.append(window)
        window.show()

    def log_row(self, index: int) -> None:
        """Ouvre l'historique du fichier de la ligne `index`.

        « Quand ce fichier a-t-il changé, et pourquoi ? » — la question
        qu'on se pose juste avant un blâme, et qu'aucun écran ne savait
        traiter jusqu'ici.

        Pas de `ref` : on veut l'histoire du fichier telle qu'elle mène à
        CE commit, pas telle que la voit une branche qui l'a peut-être
        dépassé. Elle est retenue dans `self.blame_windows`, comme le
        blâme — même raison, même ramasse-miettes.
        """
        item = self._files.topLevelItem(index)
        if item is None:
            return

        path = item.data(0, PATH_ROLE)
        window = LogWindow(self.repository, ref=self.oid, path=path, parent=self)
        window.commit_activated.connect(self._open_commit_from_blame)
        self.blame_windows.append(window)
        window.show()

    def closeEvent(self, event) -> None:
        """Ferme d'abord les fenêtres filles, tâches de fond comprises.

        Reproduit (abort du processus, pas une simple erreur) : fermer ce
        détail détruit ses filles par le lien parent Qt **sans appeler
        leur `closeEvent`**. Une `LogWindow` dont la lecture tournait
        encore voyait alors son `QThread` mourir en pleine exécution —
        « QThread: Destroyed while thread is still running » — et Qt
        abandonnait le processus.

        En usage réel : ouvrir l'historique d'un fichier puis refermer
        aussitôt le détail, d'autant plus probable que la lecture est
        longue, donc sur un gros dépôt.

        On ferme explicitement chaque fille : son propre `closeEvent`
        attend sa tâche, ce que la destruction en cascade ne fait pas.
        """
        for fille in list(self.blame_windows):
            fermer = getattr(fille, "close", None)
            if callable(fermer):
                try:
                    fermer()
                except RuntimeError:
                    # L'objet C++ peut déjà être parti : son wrapper
                    # Python lui survit (shiboken).
                    pass
        super().closeEvent(event)

    def _open_commit_from_blame(self, oid: str) -> None:
        """Un clic dans le blâme mène au commit qui a écrit la ligne (D28)."""
        window = CommitDetailWindow(self.repository, oid, self)
        self.blame_windows.append(window)
        window.show()
