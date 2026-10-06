"""Résoudre les conflits d'une fusion — §6 de la spec phase 8.

Une liste de fichiers, un choix par fichier, et **toujours** un bouton
« Abort » : c'est lui qui rend le reste acceptable, puisqu'il garantit
qu'on ne peut pas rester coincé.
"""

from __future__ import annotations

import pathlib

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

        # Les éditeurs de fusion ouverts, retenus pour que le
        # ramasse-miettes ne les ferme pas aussitôt (piège vécu dans ce
        # projet avec les fenêtres de détail).
        self.merge_editors: list = []

        self._files = QTreeWidget()
        self._files.setColumnCount(2)
        self._files.setHeaderLabels(("Fichier", "État"))
        self._files.setRootIsDecorated(False)
        self._files.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._files.itemSelectionChanged.connect(self._on_file_selected)

        # Une liste vide et muette est indiscernable d'un défaut :
        # l'utilisateur avait résolu ses conflits, voyait zéro fichier et
        # un bouton « Continue » actif, sans rien pour relier les deux —
        # il a cru son rebase terminé alors qu'il attendait d'être conclu.
        self.hint_label = QLabel()
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet("padding: 8px; font-weight: bold;")
        self.hint_label.hide()

        self.diff_view = DiffView()

        self.mine_button = QPushButton("Keep mine")
        self.mine_button.clicked.connect(self.keep_mine)
        self.theirs_button = QPushButton("Take theirs")
        self.theirs_button.clicked.connect(self.take_theirs)
        # Troisième voie : composer au lieu de choisir. Demandé par
        # l'utilisateur pour les blocs que git marque en conflit alors
        # qu'ils sont seulement voisins — garder les DEUX.
        self.edit_button = QPushButton("Edit…")
        self.edit_button.setToolTip(
            "Ouvre les deux versions côte à côte et compose le résultat"
        )
        self.edit_button.clicked.connect(self.edit_conflict)

        self.resolve_button = QPushButton("Resolve")
        self.resolve_button.clicked.connect(self.resolve)
        self.abort_button = QPushButton("Abort")
        self.abort_button.clicked.connect(self.abort)

        buttons = QHBoxLayout()
        buttons.addWidget(self.mine_button)
        buttons.addWidget(self.theirs_button)
        buttons.addWidget(self.edit_button)
        buttons.addStretch(1)
        buttons.addWidget(self.abort_button)
        buttons.addWidget(self.resolve_button)

        bottom = QWidget()
        layout = QVBoxLayout(bottom)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(buttons)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.hint_label)
        splitter.addWidget(self._files)
        splitter.addWidget(self.diff_view)
        splitter.addWidget(bottom)
        splitter.setStretchFactor(1, 3)

        self.setCentralWidget(splitter)
        self.setWindowTitle("Resolve conflicts")
        self.resize(900, 700)

        from tortoisepy.core.rebase import rebase_state

        self.rebase = rebase_state(repository)
        self._apply_labels()

        self.refresh()

    def _apply_labels(self) -> None:
        """Nomme les deux camps selon l'opération en cours.

        En **rebase**, `ours` désigne la branche cible et `theirs` le
        commit rejoué — l'inverse du merge (vérifié). Garder « Keep
        mine » ferait perdre son travail à qui croit le garder.

        « Continue » plutôt que « Resolve » : résoudre un conflit de
        rebase ne termine pas l'opération, il reste des commits à rejouer.
        """
        if not self.rebase.in_progress:
            self.mine_button.setText("Keep mine")
            self.theirs_button.setText("Take theirs")
            self.resolve_button.setText("Resolve")
            self.setWindowTitle("Resolve conflicts")
            return

        # Sans nom de cible — métadonnées illisibles — mieux vaut décrire
        # le camp que le nommer à tort : « Keep target » ne dit rien du
        # choix qu'on demande, alors que « the branch I am rebasing onto »
        # reste vrai même quand le nom manque.
        cible = self.rebase.onto_label
        self.mine_button.setText(
            f"Keep {cible}" if cible else "Keep the branch I rebase onto"
        )
        self.theirs_button.setText("Keep my commit")
        self.resolve_button.setText("Continue")
        branche = self.rebase.branch
        if branche and cible:
            self.setWindowTitle(f"Rebase {branche} onto {cible}")
        else:
            self.setWindowTitle("Rebase in progress")

    def refresh(self) -> None:
        from tortoisepy.core.rebase import rebase_state

        self.rebase = rebase_state(self.repository)
        self._apply_labels()

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
        """Conclut la fusion, ou poursuit le rebase."""
        if self.rebase.in_progress:
            from tortoisepy.core.rebase import continue_rebase

            result = continue_rebase(self.repository)
        else:
            result = conclude_merge(self.repository)

        self.finished.emit(result)
        if not result.success:
            show_error(self, result)
            self.refresh()
            return
        self.close()

    def edit_conflict(self) -> None:
        """Ouvre l'éditeur à trois colonnes sur le fichier sélectionné.

        Demandé par l'utilisateur : « il faudrait qu'on puisse modifier
        le fichier avec une colonne yours, une autre theirs et au milieu
        le fichier final ». Choisir un camp ne suffit pas quand les deux
        blocs doivent être gardés.

        Les étiquettes viennent des boutons de CETTE fenêtre : en rebase,
        « ours » et « theirs » sont inversés par rapport au merge, et
        cette fenêtre le sait déjà (`_apply_labels`). Les recalculer
        ailleurs risquerait de dire le contraire à deux centimètres
        d'écart.
        """
        item = self._files.currentItem()
        if item is None:
            return

        from tortoisepy.ui.merge_editor import MergeEditor

        editeur = MergeEditor(
            self.repository,
            item.data(0, PATH_ROLE),
            ours_label=self.mine_button.text(),
            theirs_label=self.theirs_button.text(),
            parent=self,
        )
        editeur.resolved.connect(lambda _chemin: self.refresh())
        self.merge_editors.append(editeur)
        editeur.show()

    def abort(self) -> None:
        """Rend la main : restaure l'état d'avant l'opération.

        Pour un rebase, **`abort_rebase` et non `abort_operation`** :
        celui-ci fait `state_cleanup()` + `reset(HARD)`, ce qui sur la
        HEAD détachée d'un rebase la remet sur elle-même sans rattacher
        la branche (défaut trouvé en phase 8).
        """
        if self.rebase.in_progress:
            from tortoisepy.core.rebase import abort_rebase

            result = abort_rebase(self.repository)
        else:
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
        self._update_hint(remaining)
        # Conclure avec un conflit restant produirait un commit contenant
        # des marqueurs `<<<<<<<` (règle de la phase 6).
        self.resolve_button.setEnabled(remaining == 0)
        self.mine_button.setEnabled(remaining > 0)
        self.theirs_button.setEnabled(remaining > 0)
        self.edit_button.setEnabled(remaining > 0)

    def _update_hint(self, remaining: int) -> None:
        """Explique une liste vide, et seulement dans ce cas.

        Tant qu'il reste des conflits, ce message serait un contresens :
        il dit justement qu'il n'y a plus rien à faire ici.
        """
        if remaining > 0:
            self.hint_label.hide()
            return

        geste = self.resolve_button.text()
        if self.rebase.in_progress:
            self.hint_label.setText(
                "Tous les conflits sont résolus. Cliquez "
                f"« {geste} » pour terminer le rebase — "
                "tant qu'il n'est pas conclu, votre branche reste où "
                "elle était."
            )
        else:
            self.hint_label.setText(
                f"Tous les conflits sont résolus. Cliquez « {geste} » "
                "pour conclure la fusion."
            )
        self.hint_label.show()


def _nom_des_cotes(repo: pygit2.Repository) -> tuple[str, str]:
    """Noms des deux branches en conflit : (la nôtre, la leur).

    `HEAD` et `4424f94…` ne disent rien à l'utilisateur. Git connaît
    pourtant les noms — vérifié : la branche courante pour la nôtre,
    `MERGE_MSG` (« Merge branch 'TEST' ») pour la leur.
    """
    import re

    try:
        notre = repo.head.shorthand if not repo.head_is_unborn else "HEAD"
    except (pygit2.GitError, KeyError, ValueError):
        notre = "HEAD"

    leur = "incoming"

    # En rebase, « ours » désigne la CIBLE et « theirs » le commit rejoué
    # — l'inverse du merge (§9). Le champ est `onto_label`, pas `onto` :
    # une première version visait le mauvais nom, et un `except` trop
    # large le masquait (les noms restaient « HEAD » / « incoming »).
    from tortoisepy.core.rebase import rebase_state

    etat = rebase_state(repo)
    if etat.in_progress:
        # `onto_label` et `branch` peuvent être vides selon le backend de
        # rebase employé (vérifié : git 2.26+ utilise le backend « merge »,
        # où `rebase_state` ne les renseigne pas toujours). On reste alors
        # explicite sur les RÔLES, qui eux ne changent pas.
        cible = etat.onto_label or "the branch you rebase onto"
        rejouee = etat.branch or "the commit being replayed"
        return cible, rejouee

    chemin = pathlib.Path(repo.path) / "MERGE_MSG"
    try:
        premiere = chemin.read_text(encoding="utf-8").splitlines()[0]
        trouve = re.search(r"'([^']+)'", premiere)
        if trouve:
            leur = trouve.group(1)
    except (OSError, IndexError):
        pass

    return notre, leur


def _conflict_preview(repo: pygit2.Repository, path: str):
    """Le fichier en conflit, ses marqueurs remplacés par des en-têtes.

    Les marqueurs bruts de git (`<<<<<<< HEAD`, `=======`) n'apprennent
    rien à qui ne les connaît pas, et le code couleur les contredisait :
    vert pour notre version, rouge pour la leur, alors que vert et rouge
    veulent dire « ajouté » et « supprimé » partout ailleurs (signalé par
    l'utilisateur).

    On nomme donc chaque côté, en reprenant les mots des boutons —
    « yours » pour « Keep mine », « theirs » pour « Take theirs ».
    """
    import os

    from tortoisepy.core.changes import DiffHunk, FileDiff

    full = os.path.join(repo.workdir or "", path)
    try:
        with open(full, encoding="utf-8", errors="replace") as handle:
            contenu = handle.read().splitlines()
    except OSError:
        return FileDiff(path=path)

    notre, leur = _nom_des_cotes(repo)
    return FileDiff(
        path=path,
        hunks=(
            DiffHunk(
                header=f"@@ {path} @@",
                lines=_colour(contenu, notre, leur),
            ),
        ),
    )


def _colour(lines: list[str], notre: str = "HEAD", leur: str = "incoming"):
    """Remplace les marqueurs par des en-têtes nommés, et colore chaque côté.

    Les en-têtes portent le nom de la branche ET le mot du bouton qui la
    garde : devant deux versions concurrentes, l'utilisateur sait laquelle
    est la sienne et sur quoi cliquer.
    """
    from tortoisepy.core.changes import DiffLine

    coloured = []
    side = " "
    for line in lines:
        if line.startswith("<<<<<<<"):
            side = "+"          # début de NOTRE version
            coloured.append(DiffLine(
                origin=" ", content=f"▼ yours — {notre}"
            ))
            continue
        if line.startswith("======="):
            side = "-"          # bascule vers LEUR version
            coloured.append(DiffLine(
                origin=" ", content=f"▼ theirs — {leur}"
            ))
            continue
        if line.startswith(">>>>>>>"):
            side = " "
            coloured.append(DiffLine(origin=" ", content="▲ end of conflict"))
            continue
        coloured.append(DiffLine(origin=side, content=line))
    return tuple(coloured)
