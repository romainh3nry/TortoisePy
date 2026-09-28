"""Fenêtre de commit — §4.

Trois zones : les fichiers modifiés, le diff du fichier sélectionné, le
message et les boutons. Voir le diff en écrivant le message est ce qui rend
le message juste (D6).
"""

from __future__ import annotations

import pygit2
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tortoisepy.core import operations
from tortoisepy.core.changes import diff_for, list_changes
from tortoisepy.ui.diff_view import DiffView
from tortoisepy.ui.dialogs import confirm, show_error, show_message
from tortoisepy.ui.dialogs import ConfirmationRequest

PATH_ROLE = Qt.ItemDataRole.UserRole
SELECTABLE_ROLE = Qt.ItemDataRole.UserRole + 1
"""Mémorise `FileChange.selectable` à côté du chemin (Finding 1, tour 1).

Le flag Qt `ItemIsUserCheckable` protège la souris (la case n'est pas
cliquable), mais rien n'empêche d'appeler `item.setCheckState()` en direct
depuis le code — ce que fait `set_checked`. Sans une source de vérité
indépendante du flag, un appel programmatique pouvait forcer la coche d'un
fichier en conflit et le faire passer dans `checked_paths()`, donc dans le
commit, avec ses marqueurs `<<<<<<<`. Stocker `selectable` dans un rôle
Qt permet à `set_checked` et `checked_paths()` de le revérifier chacun de
leur côté : double garde, comme demandé en revue.
"""


class CommitWindow(QMainWindow):
    """Voir, stager, commiter, pousser."""

    committed = Signal(object, object)
    """(`OperationResult` du commit, `OperationResult` du push ou `None`).

    Deux arguments plutôt qu'un : la fenêtre principale doit distinguer
    « commité » de « commité et poussé », et annoncer un push échoué sans
    laisser croire que le commit l'a été aussi (§4 de la spec).
    """

    def __init__(self, repository: pygit2.Repository, parent=None):
        super().__init__(parent)
        self.repository = repository

        self._files = QTreeWidget()
        self._files.setColumnCount(2)
        self._files.setHeaderLabels(("", "Fichier"))
        self._files.setRootIsDecorated(False)
        self._files.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._files.itemSelectionChanged.connect(self._on_file_selected)
        self._files.itemChanged.connect(lambda *_: self._update_buttons())

        self.diff_view = DiffView()

        self._message = QPlainTextEdit()
        self._message.setPlaceholderText("Message du commit…")
        self._message.setMaximumHeight(120)
        self._message.textChanged.connect(self._update_buttons)

        self.commit_button = QPushButton("Commit")
        self.commit_button.clicked.connect(self.commit)
        self.push_button = QPushButton("Commit && Push")
        self.push_button.clicked.connect(self.commit_and_push)
        cancel = QPushButton("Annuler")
        cancel.clicked.connect(self.close)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(self.commit_button)
        buttons.addWidget(self.push_button)

        bottom = QWidget()
        layout = QVBoxLayout(bottom)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Message :"))
        layout.addWidget(self._message)
        layout.addLayout(buttons)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self._files)
        splitter.addWidget(self.diff_view)
        splitter.addWidget(bottom)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)

        self.setCentralWidget(splitter)
        self.setWindowTitle(self._title())
        self.resize(900, 700)

        self.refresh()

    # --- état ----------------------------------------------------------

    def refresh(self) -> None:
        """Relit les changements. Le message saisi est conservé."""
        self._files.clear()
        self.diff_view.clear()

        for change in list_changes(self.repository):
            item = QTreeWidgetItem(["", f"{change.kind.value}  {change.path}"])
            item.setData(0, PATH_ROLE, change.path)
            item.setData(0, SELECTABLE_ROLE, change.selectable)

            if change.selectable:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    0,
                    Qt.CheckState.Checked
                    if change.selected_by_default
                    else Qt.CheckState.Unchecked,
                )
            else:
                # Un conflit non résolu produirait un commit contenant des
                # marqueurs `<<<<<<<` (§4.1).
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                item.setToolTip(
                    1, "Conflit non résolu — à régler hors de l'application"
                )

            self._files.addTopLevelItem(item)

        self._update_buttons()

    def file_count(self) -> int:
        return self._files.topLevelItemCount()

    def checked_paths(self) -> tuple[str, ...]:
        # Deuxième garde (Finding 1) : même si une case a été cochée par un
        # appel direct à `item.setCheckState()` en contournant `set_checked`,
        # un fichier non sélectionnable (conflit) ne doit jamais atteindre
        # `commit_selection`. Ne pas se fier uniquement au flag Qt : il ne
        # protège que le clic souris, pas un appel programmatique.
        return tuple(
            item.data(0, PATH_ROLE)
            for item in self._items()
            if item.checkState(0) == Qt.CheckState.Checked
            and item.data(0, SELECTABLE_ROLE)
        )

    def is_checked(self, path: str) -> bool:
        item = self._item_for(path)
        return bool(item and item.checkState(0) == Qt.CheckState.Checked)

    def is_checkable(self, path: str) -> bool:
        item = self._item_for(path)
        return bool(item and item.flags() & Qt.ItemFlag.ItemIsUserCheckable)

    def set_checked(self, path: str, checked: bool) -> None:
        """Coche ou décoche. Refuse silencieusement de cocher un conflit.

        Première garde (Finding 1) : `item.setCheckState()` n'a aucune idée
        du flag `ItemIsUserCheckable` — l'appeler directement sur un fichier
        en conflit fonctionnerait sans lever d'erreur. Décocher reste
        toujours permis (retirer un fichier d'un commit n'est jamais
        dangereux), seul le fait de cocher un fichier non sélectionnable est
        refusé.
        """
        item = self._item_for(path)
        if item is None:
            return
        if checked and not item.data(0, SELECTABLE_ROLE):
            return
        item.setCheckState(
            0, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        )

    def select_file(self, path: str) -> None:
        item = self._item_for(path)
        if item is not None:
            self._files.setCurrentItem(item)

    def set_message(self, text: str) -> None:
        self._message.setPlainText(text)

    def message(self) -> str:
        return self._message.toPlainText()

    # --- actions -------------------------------------------------------

    def commit(self) -> None:
        paths = self.checked_paths()
        result = operations.commit_selection(
            self.repository, paths, self.message()
        )
        if result.success:
            self._try_sync_index_after_commit(paths)
        self._after_commit(result, None)

    def commit_and_push(self) -> None:
        """§6.2 : pousser sort de la machine, donc on confirme."""
        branch = (
            self.repository.head.shorthand
            if not self.repository.head_is_unborn
            else "?"
        )
        request = ConfirmationRequest(
            title="Commit & Push",
            message=(
                f"git push origin {branch}\n\n"
                "The commit will be sent to the shared server. This cannot "
                "be undone on your own."
            ),
            destructive=False,
        )
        if not confirm(self, request):
            return

        paths = self.checked_paths()
        result = operations.commit_selection(
            self.repository, paths, self.message()
        )
        if not result.success:
            self._after_commit(result, None)
            return
        self._try_sync_index_after_commit(paths)

        pushed = operations.push_branch(self.repository)
        if not pushed.success:
            # Le commit est fait : le dire explicitement, sinon on croit
            # avoir tout perdu (§8 phase 6).
            show_error(self, pushed)

        self._after_commit(result, pushed)

    # --- interne -------------------------------------------------------

    def _try_sync_index_after_commit(self, paths: tuple[str, ...]) -> None:
        """Appelle `_sync_index_after_commit` sans jamais faire échouer le commit.

        Finding 2 (revue, tour 1) : le commit est déjà fait et durable en
        base d'objets quand cette méthode s'exécute — un `.git/index.lock`
        laissé par un git concurrent ou planté ferait lever `GitError` ici,
        et l'exception s'échapperait du slot Qt : `_after_commit` ne
        s'exécuterait jamais, pas de signal `committed`, pas de rafraîchissement,
        et l'utilisateur croirait avoir tout perdu alors que le commit existe
        (exactement le risque que §8 vise pour le push, réintroduit par un autre
        chemin). La synchronisation est un confort d'affichage, jamais une
        condition du succès : on l'isole ici pour que son échec ne remonte
        jamais plus haut que ce message d'avertissement.
        """
        try:
            self._sync_index_after_commit(paths)
        except (pygit2.GitError, OSError) as error:
            show_message(
                self,
                "Commit effectué",
                "Le commit a bien été créé, mais l'index sur disque n'a "
                "pas pu être resynchronisé "
                f"({error}).\n\n"
                "Rouvrez cette fenêtre si l'affichage semble en retard.",
            )

    def _sync_index_after_commit(self, paths: tuple[str, ...]) -> None:
        """Aligne l'index sur disque avec HEAD, mais seulement pour `paths`.

        `commit_selection` construit son arbre en mémoire et ne touche jamais
        `.git/index` (§5) — un vrai `git commit`, lui, met à jour l'index pour
        les fichiers commités. Sans ce geste, `list_changes` (qui lit
        `repo.status()`, donc HEAD ↔ index ↔ arbre de travail) continuerait
        de signaler ces fichiers comme modifiés après leur propre commit.
        Ne toucher que les chemins cochés préserve ce que l'utilisateur a
        préparé au terminal pour le reste (`test_the_user_index_is_left_alone`
        côté opérations) : décocher n'écrit rien, cocher+commiter ne synchronise
        que ce qui vient d'être commité.
        """
        tree = self.repository.get(self.repository.head.target).tree
        index = self.repository.index
        index.read()
        for path in paths:
            try:
                entry = tree[path]
            except KeyError:
                # Fichier supprimé par ce commit : il doit disparaître de
                # l'index comme il a disparu de l'arbre.
                if path in index:
                    index.remove(path)
                continue
            index.add(pygit2.IndexEntry(path, entry.id, entry.filemode))
        index.write()

    def _after_commit(self, result, pushed) -> None:
        """Annonce le résultat, puis rend la main au graphe si c'est fait.

        Sur un échec de commit la fenêtre reste ouverte **avec son message**
        : le refermer ferait perdre la rédaction alors qu'il y a justement
        une correction à faire (§3 de la spec).
        """
        self.committed.emit(result, pushed)

        if not result.success:
            show_error(self, result)
            return

        # Le commit est acquis — même si le push a échoué, il n'y a plus
        # rien à faire dans cette fenêtre.
        self.set_message("")
        self.refresh()
        self.close()

    def _on_file_selected(self) -> None:
        item = self._files.currentItem()
        if item is None:
            self.diff_view.clear()
            return
        self.diff_view.show_diff(
            diff_for(self.repository, item.data(0, PATH_ROLE))
        )

    def _update_buttons(self) -> None:
        ready = bool(self.message().strip()) and bool(self.checked_paths())
        self.commit_button.setEnabled(ready)
        self.push_button.setEnabled(ready)

    def _items(self) -> list[QTreeWidgetItem]:
        return [
            self._files.topLevelItem(i)
            for i in range(self._files.topLevelItemCount())
        ]

    def _item_for(self, path: str) -> QTreeWidgetItem | None:
        for item in self._items():
            if item.data(0, PATH_ROLE) == path:
                return item
        return None

    def _title(self) -> str:
        if self.repository.head_is_unborn:
            return "Commit — dépôt vide"
        return f"Commit — {self.repository.head.shorthand}"
