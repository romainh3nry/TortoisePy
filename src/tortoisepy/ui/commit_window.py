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
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tortoisepy.core import operations
from tortoisepy.core.amend import amend_commit, can_amend, last_commit_message
from tortoisepy.core.changes import diff_for, list_changes
from tortoisepy.core.push_state import unpushed_oids
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

        self._emprunte = ""
        """Message tapé avant de cocher « Amender », rendu si on décoche."""
        self.amend_box = QCheckBox("Amender le dernier commit")
        raison = can_amend(repository)
        self.amend_box.setEnabled(raison is None)
        if raison is not None:
            # Grisé sans explication n'apprend rien : dire pourquoi.
            self.amend_box.setToolTip(raison)
        self.amend_box.toggled.connect(self._on_amend_toggled)

        # §3.4 : amender un commit déjà publié fait diverger la branche.
        # Le dire ici, et nommer la suite, évite le « non-fastforwardable »
        # de git, que l'utilisateur ne sait pas interpréter.
        self.amend_warning = QLabel(
            "⚠ Ce commit est déjà sur le serveur : après l'avoir amendé, "
            "il faudra « Push (force with lease) »."
        )
        self.amend_warning.setWordWrap(True)
        self.amend_warning.setVisible(False)

        # Message emprunté au dernier commit, et sa valeur au moment où on
        # l'a posé : sans ce repère, décocher écraserait ce que
        # l'utilisateur vient d'écrire par-dessus.
        self._emprunte = ""
        self._emprunt_pose = ""

        self.commit_button = QPushButton("Commit")
        self.commit_button.clicked.connect(self.commit)
        self.push_button = QPushButton("Commit && Push")
        self.push_button.clicked.connect(self.commit_and_push)
        cancel = QPushButton("Annuler")
        cancel.clicked.connect(self.close)

        # À GAUCHE, séparé des boutons d'action : il agit sur la liste,
        # pas sur le dépôt. Le mettre à côté de « Commit » inviterait au
        # clic de trop.
        self.check_all_button = QPushButton("Tout cocher")
        self.check_all_button.setToolTip(
            "Coche tous les fichiers, y compris les non suivis"
        )
        self.check_all_button.clicked.connect(self.check_all)

        # Le push traverse le réseau — plusieurs secondes — et le commit
        # écrit l'index et l'arbre. Sans retour visuel, la fenêtre paraît
        # figée (signalé par l'utilisateur).
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)      # indéterminé : durée inconnue
        self.progress.setMaximumWidth(180)
        self.progress.setTextVisible(True)
        self.progress.hide()

        buttons = QHBoxLayout()
        buttons.addWidget(self.check_all_button)
        buttons.addWidget(self.progress)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(self.commit_button)
        buttons.addWidget(self.push_button)

        bottom = QWidget()
        layout = QVBoxLayout(bottom)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.amend_box)
        layout.addWidget(self.amend_warning)
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

    def _travail_en_cours(self, libelle: str) -> None:
        """Affiche le loader et gèle les boutons.

        Un second clic lancerait un commit concurrent sur le même index.
        """
        self.progress.setFormat(libelle)
        self.progress.show()
        self.commit_button.setEnabled(False)
        self.push_button.setEnabled(False)

    def _travail_fini(self) -> None:
        """Rend la main. Appelé MÊME en cas d'échec, sinon la fenêtre
        resterait inutilisable."""
        self.progress.hide()
        self.commit_button.setEnabled(True)
        self.push_button.setEnabled(True)

    def check_all(self) -> None:
        """Coche tous les fichiers cochables.

        Demandé par l'utilisateur : les fichiers non suivis arrivent
        décochés (D8), et les cocher un par un est fastidieux quand ils
        sont légitimes.

        Passe par `set_checked`, qui **refuse les conflits** : un
        fichier non résolu coché produirait un commit contenant des
        marqueurs `<<<<<<<` (§4.1). Un bouton « tout cocher » est
        précisément le chemin par lequel cette garantie pourrait tomber.
        """
        for item in self._items():
            self.set_checked(item.data(0, PATH_ROLE), True)

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

    def _write_commit(self, paths: tuple[str, ...]):
        """Écrit le commit : amend ou création, selon la case.

        Le seul endroit qui tranche. « Commit » le faisait, pas
        « Commit && Push » : avec la case cochée, ce dernier créait un
        **second** commit puis le poussait — l'intention de l'utilisateur
        silencieusement inversée, et un mauvais commit sur le serveur
        (trouvé en revue finale).
        """
        if self.amend_box.isChecked():
            return amend_commit(self.repository, paths, self.message())
        return operations.commit_selection(
            self.repository, paths, self.message()
        )

    def commit(self) -> None:
        paths = self.checked_paths()
        self._travail_en_cours("Commit…")
        try:
            result = self._write_commit(paths)
            if result.success:
                self._try_sync_index_after_commit(paths)
        finally:
            # `finally` : une exception ne doit pas laisser la fenêtre
            # gelée avec son loader tournant indéfiniment.
            self._travail_fini()
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
        self._travail_en_cours("Commit & Push…")
        try:
            result = self._write_commit(paths)
            if not result.success:
                self._travail_fini()
                self._after_commit(result, None)
                return
            self._try_sync_index_after_commit(paths)
        except Exception:
            self._travail_fini()
            raise

        # Le loader couvre AUSSI le push : c'est la partie la plus longue,
        # puisqu'elle traverse le réseau.
        try:
            pushed = operations.push_branch(self.repository)
        finally:
            self._travail_fini()

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

    def _on_amend_toggled(self, coche: bool) -> None:
        """Emprunte le message du dernier commit, ou le rend.

        Corriger une faute suppose de voir ce qu'on corrige. Et décocher
        doit rendre le message emprunté : le laisser le ferait passer
        pour le message d'un commit neuf.
        """
        if coche:
            self._emprunte = self._message.toPlainText()
            self._message.setPlainText(last_commit_message(self.repository))
        else:
            # Ne rendre le message emprunté que si l'utilisateur ne l'a
            # pas remplacé : sinon décocher effacerait ce qu'il vient
            # d'écrire, sans rien demander (trouvé en revue finale).
            if self._message.toPlainText() == self._emprunt_pose:
                self._message.setPlainText(self._emprunte)
        self.commit_button.setText("Amender" if coche else "Commit")
        self._emprunt_pose = self._message.toPlainText() if coche else ""
        self._update_amend_warning(coche)
        self._update_buttons()

    def _update_amend_warning(self, coche: bool) -> None:
        """Prévient si l'on réécrit un commit déjà publié (§3.4).

        Amender change l'identifiant du commit : si l'ancien est sur le
        serveur, la branche diverge et le push normal sera rejeté par un
        « non-fastforwardable » que l'utilisateur ne sait pas
        interpréter. Mieux vaut le dire avant, et nommer la suite.
        """
        self.amend_warning.setVisible(coche and self._last_commit_is_pushed())

    def _last_commit_is_pushed(self) -> bool:
        """Le dernier commit est-il déjà sur un serveur ?

        Exiger qu'un remote existe : sur un dépôt purement local,
        `unpushed_oids` rend un ensemble vide et tout commit y paraîtrait
        « déjà poussé » (vérifié) — l'avertissement s'afficherait à tort.
        """
        try:
            if not list(self.repository.remotes.names()):
                return False
            if self.repository.head_is_unborn:
                return False
            return self.repository.head.target not in unpushed_oids(
                self.repository
            )
        except (pygit2.GitError, KeyError, ValueError):
            return False

    def _update_buttons(self) -> None:
        # En amend, le message seul suffit : corriger une faute ne touche
        # aucun fichier. Exiger un fichier coché laisserait le bouton
        # inactif dans le cas le plus courant.
        ready = bool(self.message().strip()) and (
            self.amend_box.isChecked() or bool(self.checked_paths())
        )
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
