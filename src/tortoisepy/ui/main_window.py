"""Fenêtre principale — assemblage de §7.

Relie le dépôt, le graphe, la vue, le menu contextuel et la surveillance
de `.git`. Le chrome est natif : Qt s'en charge, conformément au choix de
reproduire le graphe mais pas l'habillage Windows.
"""

from __future__ import annotations

from pathlib import Path

import pygit2
import shiboken6
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QMenu,
    QProgressBar,
    QSplitter,
    QToolBar,
)

from tortoisepy.core.commits import commits_for_node
from tortoisepy.core.graph import build_graph
from tortoisepy.core.credentials import is_https, remember
from tortoisepy.core.pull import (
    PullKind,
    analyse_pull,
    pull_fast_forward,
    pull_merge,
    pull_rebase,
)
from tortoisepy.core.push_state import push_state, unpushed_oids
from tortoisepy.core.results import failed, succeeded
from tortoisepy.core.state import read_state
from tortoisepy.layout.engine import layout_graph
from tortoisepy.ui import actions
from tortoisepy.ui.actions import ActionContext
from tortoisepy.ui.commit_detail_window import CommitDetailWindow
from tortoisepy.ui.commit_panel import CommitPanel
from tortoisepy.ui.commit_window import CommitWindow
from tortoisepy.ui.conflict_window import ConflictWindow
from tortoisepy.ui.context_menu import MenuEntry, build_menu_model
from tortoisepy.ui.dialogs import (
    ConfirmationRequest,
    ask_credentials,
    ask_name,
    ask_pull_strategy,
    ask_reset_mode,
    confirm,
    show_error,
)
from tortoisepy.ui.graph_view import GraphView
from tortoisepy.ui.tasks import BackgroundTask, FetchWorker
from tortoisepy.ui.theme import QtMeasurer
from tortoisepy.ui.watcher import RepositoryWatcher


_NEEDS_STRATEGY = "diverged: ask how to combine"
"""Marqueur interne : le fil de fond rend la main pour poser la question.

Ce n'est pas une erreur — juste le seul moyen de faire ouvrir un dialogue
par le fil d'interface, Qt l'interdisant depuis un fil de travail.
"""


_AUTH_MARKERS = ("authentication", "credential", "401", "403")


def _needs_authentication(result) -> bool:
    """L'échec vient-il d'un défaut d'authentification ?

    Vérifié : sans rappel, libgit2 lève `AuthError` avec le message
    « remote authentication required but no callback set ». On teste des
    marqueurs plutôt que la chaîne exacte, qui dépend de la version de
    libgit2 et du serveur.
    """
    message = (result.git_error or "").lower()
    return any(marker in message for marker in _AUTH_MARKERS)


def _still_alive(widget) -> bool:
    """Le widget Qt existe-t-il encore côté C++ ?

    Un wrapper Python peut survivre à l'objet C++ que Qt a détruit
    (`WA_DeleteOnClose`) : y toucher lève alors un `RuntimeError` de
    shiboken. `isValid` est le seul test fiable.
    """
    return shiboken6.isValid(widget)


class MainWindow(QMainWindow):
    """Fenêtre du Revision Graph."""

    def __init__(self, repository: pygit2.Repository, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.measurer = QtMeasurer()
        self.graph = None
        self.state = None

        self.view = GraphView(self)
        self.view.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.view.customContextMenuRequested.connect(self._show_context_menu)
        # Simple clic : la sélection affiche les commits. C'est le même
        # geste que sélectionner, donc le plus direct. Le double-clic reste
        # branché — il ne coûte rien et fait la même chose.
        self.view.selection_changed.connect(self._on_selection_changed)
        self.view.node_double_clicked.connect(self._show_commits)

        # Le panneau révèle ce que la compression masque (§4.2.1). Un
        # splitter plutôt qu'une largeur fixe : la place à donner au graphe
        # dépend de la longueur des noms de branches.
        self.commit_panel = CommitPanel(self)
        self.commit_panel.commit_activated.connect(self.open_commit_detail)
        self._detail_windows: list[CommitDetailWindow] = []
        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.splitter.addWidget(self.view)
        self.splitter.addWidget(self.commit_panel)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self.setCentralWidget(self.splitter)

        self.toolbar = self._build_toolbar()
        self._build_actions()

        self.watcher = RepositoryWatcher(str(Path(repository.path)), parent=self)
        self.watcher.graph_changed.connect(self.refresh)
        self.watcher.state_changed.connect(self._refresh_state_only)
        self.watcher.start()

        # Barre de progression discrète : le fetch tourne en fond, la
        # navigation reste possible pendant ce temps.
        self.progress = QProgressBar(self)
        self.progress.setMaximumWidth(220)
        self.progress.setTextVisible(True)
        self.progress.hide()
        self.statusBar().addPermanentWidget(self.progress)

        # Permanent, à droite : les messages temporaires (commit, pull,
        # push…) écrasent le message ordinaire de la barre d'état, et la
        # branche courante disparaissait alors de l'écran. Un widget
        # permanent n'est jamais recouvert.
        self.branch_label = QLabel()
        self.branch_label.setContentsMargins(0, 0, 8, 0)
        self.statusBar().addPermanentWidget(self.branch_label)

        self._task: BackgroundTask | None = None
        self._fetch_summary: str | None = None
        self.commit_window: CommitWindow | None = None
        self.conflict_window: ConflictWindow | None = None

        self.setWindowTitle(self._title())
        self.resize(1400, 850)
        self.refresh()

    def refresh(self) -> None:
        """Reconstruit le graphe et relit l'état (§7.6, §7.9)."""
        self.graph = build_graph(self.repository)
        self.state = read_state(self.repository)
        unpushed = unpushed_oids(self.repository)
        self.view.show_graph(
            self.graph, layout_graph(self.graph, self.measurer), unpushed
        )
        self.commit_panel.clear()
        self._center_on_head()
        self._update_status()
        self._update_push_action()
        self._update_fetch_action()
        self._update_pull_action()

    def closeEvent(self, event) -> None:
        self.watcher.stop()
        super().closeEvent(event)

    def _center_on_head(self) -> None:
        """Place la vue sur la branche courante.

        Le nœud vert est le repère de l'utilisateur : sur un dépôt dont le
        graphe fait plusieurs milliers de pixels de haut, s'ouvrir ailleurs
        l'oblige à chercher où il se trouve.
        """
        if self.state is None or self.state.head_oid is None:
            return
        self.view.center_on_node(self.state.head_oid)

    def _on_selection_changed(self) -> None:
        """Un nœud sélectionné montre ses commits ; plusieurs, ou aucun, non.

        Avec deux nœuds sélectionnés, le menu contextuel bascule sur la
        comparaison (§7.4) : afficher les commits de l'un des deux serait
        arbitraire.
        """
        selected = self.view.selected_oids()
        if len(selected) == 1:
            self._show_commits(selected[0])
        else:
            self.commit_panel.clear()

    def _show_commits(self, oid: str) -> None:
        """Double-clic : liste les commits masqués par l'arête entrante."""
        if self.graph is None:
            return

        node = self.graph.node(oid)
        if node is None:
            return

        label = " | ".join(r.name for r in node.refs) or f"[{oid[:8]}]"
        self.commit_panel.show_commits(
            label,
            commits_for_node(self.repository, self.graph, oid),
            unpushed=unpushed_oids(self.repository),
        )

    def _refresh_state_only(self) -> None:
        """Relit l'état sans reconstruire le graphe — bien moins coûteux."""
        self.state = read_state(self.repository)
        self._update_status()

    def _title(self) -> str:
        """Nom du dépôt, branche courante, puis l'application.

        La branche figure dans le titre pour rester lisible depuis le
        sélecteur de fenêtres, même quand tortoisePy n'est pas au premier
        plan.
        """
        workdir = self.repository.workdir
        name = Path(workdir).name if workdir else Path(self.repository.path).name

        branch = getattr(self.state, "head_branch", None) if self.state else None
        if branch:
            return f"{name} [{branch}] — tortoisePy"
        return f"{name} — tortoisePy"

    def _build_toolbar(self) -> QToolBar:
        toolbar = QToolBar("Navigation", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        return toolbar

    def _build_actions(self) -> None:
        """Actions de navigation (§7.1). Qt traduit ⌘ depuis Ctrl sur macOS."""
        specs = [
            ("Zoom avant", QKeySequence.StandardKey.ZoomIn, self.view.zoom_in),
            ("Zoom arrière", QKeySequence.StandardKey.ZoomOut, self.view.zoom_out),
            ("Zoom 100 %", QKeySequence("Ctrl+0"), self.view.reset_zoom),
            ("Ajuster à la fenêtre", QKeySequence("Ctrl+9"), self.view.fit_to_window),
            ("Rafraîchir", QKeySequence.StandardKey.Refresh, self.refresh),
            ("Commit…", QKeySequence("Ctrl+K"), self.open_commit_window),
            ("Push", QKeySequence("Ctrl+P"), self._start_push),
            ("Pull", QKeySequence("Ctrl+L"), self._start_pull),
            # À côté de Pull : c'est la même famille de gestes, et Fetch
            # n'était atteignable que par le clic droit.
            ("Fetch", QKeySequence("Ctrl+Shift+F"), self._start_fetch),
        ]

        for label, shortcut, slot in specs:
            action = QAction(label, self)
            action.setShortcut(shortcut)
            action.triggered.connect(slot)
            self.addAction(action)
            self.toolbar.addAction(action)
            if label == "Push":
                self.push_action = action
            if label == "Pull":
                self.pull_action = action
            if label == "Fetch":
                self.fetch_action = action

    def _update_status(self) -> None:
        if self.state is None:
            return

        if self.state.head_branch:
            message = f"Sur {self.state.head_branch}"
        elif self.state.detached:
            message = f"HEAD détaché sur {(self.state.head_oid or '')[:8]}"
        else:
            message = "Dépôt sans commit"

        if self.state.operation_in_progress:
            message += f" — {self.state.operation_in_progress} en cours"
        if self.state.has_conflicts:
            message += f" — {len(self.state.conflicted_paths)} conflit(s)"

        self.statusBar().showMessage(message)
        self._update_branch_label()
        self.setWindowTitle(self._title())

    def _update_branch_label(self) -> None:
        """Affiche la branche courante en permanence, à droite."""
        if self.state is None:
            self.branch_label.setText("")
            return

        if self.state.head_branch:
            texte = f"⎇ {self.state.head_branch}"
        elif self.state.detached:
            texte = f"⎇ HEAD détaché ({(self.state.head_oid or '')[:8]})"
        else:
            texte = "⎇ sans commit"

        self.branch_label.setText(texte)
        self.branch_label.setToolTip(texte.removeprefix("⎇ "))

    def _show_context_menu(self, position) -> None:
        """Construit le QMenu à partir du modèle (§7.3)."""
        if self.graph is None or self.state is None:
            return

        selected = self.view.selected_oids()
        nodes = tuple(
            node for oid in selected
            if (node := self.graph.node(oid)) is not None
        )

        entries = build_menu_model(nodes, self.state)
        if not entries:
            return

        menu = QMenu(self)
        self._fill_menu(menu, entries)
        menu.exec(self.view.mapToGlobal(position))

    def _fill_menu(self, menu: QMenu, entries: tuple[MenuEntry, ...]) -> None:
        for entry in entries:
            # `is_separator` repose sur `action == "separator"`, jamais sur
            # le label : celui-ci porte un caractère de remplissage qui ne
            # doit pas s'afficher.
            if entry.is_separator:
                menu.addSeparator()
            elif entry.children:
                submenu = menu.addMenu(entry.label)
                self._fill_menu(submenu, entry.children)
            else:
                action = menu.addAction(entry.label)
                action.setEnabled(entry.enabled)
                action.triggered.connect(
                    lambda checked=False, name=entry.action: self._run_action(
                        name, self._selected_node()
                    )
                )

    def open_commit_window(self) -> None:
        """Ouvre la fenêtre de commit, ou ramène celle déjà ouverte.

        Une seule à la fois : deux fenêtres sur le même dépôt afficheraient
        des états divergents.
        """
        if self.commit_window is not None and self.commit_window.isVisible():
            self.commit_window.raise_()
            self.commit_window.activateWindow()
            return

        self.commit_window = CommitWindow(self.repository, self)
        self.commit_window.committed.connect(self._on_committed)
        self.commit_window.show()

    def open_conflict_window(self) -> None:
        """Ouvre la résolution de conflits, ou ramène celle déjà ouverte.

        Une seule à la fois : deux vues d'un même index se contrediraient.
        """
        if (
            self.conflict_window is not None
            and not self.conflict_window.isHidden()
        ):
            self.conflict_window.raise_()
            self.conflict_window.activateWindow()
            return

        self.conflict_window = ConflictWindow(self.repository, self)
        self.conflict_window.finished.connect(self._on_conflicts_finished)
        self.conflict_window.show()

    def _on_conflicts_finished(self, result) -> None:
        if result.repository_changed:
            self.refresh()
        self.statusBar().showMessage(
            result.summary or (result.git_error or ""), 15000
        )

    def _on_committed(self, result, pushed=None) -> None:
        """Un commit change l'historique : le graphe doit le refléter.

        Le résultat va dans la barre d'état, là où le fetch annonce déjà les
        siens : c'est le même genre d'information, au même endroit (§4).
        """
        if result.repository_changed:
            self.refresh()

        if not result.success:
            return  # la fenêtre de commit a déjà ouvert son dialogue

        message = result.summary
        if pushed is not None:
            message += (
                f", {pushed.summary.lower()}"
                if pushed.success
                else " (push failed)"
            )

        self.statusBar().showMessage(message, 15000)

    def open_commit_detail(self, oid: str) -> None:
        """Ouvre les changements d'un commit.

        Plusieurs fenêtres sont permises — contrairement à la fenêtre de
        commit : comparer deux commits côte à côte est légitime, et elles
        sont en lecture seule. La liste garde une référence, sans quoi le
        ramasse-miettes fermerait la fenêtre aussitôt (piège vérifié dans ce
        projet, cf. `BackgroundTask`).

        Mais la même liste ne doit garder QUE les fenêtres encore ouvertes :
        sans retrait, elle grossirait sans fin au fil d'une session où
        inspecter des commits est justement l'usage prévu — chaque fenêtre
        fermée resterait vivante en mémoire, avec son `Repository`, son
        arbre de fichiers et son `DiffView`. `WA_DeleteOnClose` fait que
        `close()` détruit réellement le widget Qt ; `destroyed` prévient
        alors pour qu'on l'enlève de la liste.
        """
        window = CommitDetailWindow(self.repository, oid, self)
        window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        # `destroyed` porte l'objet détruit : le prendre en argument plutôt
        # que de capturer `window` dans la fermeture évite de garder une
        # référence forte sur ce qu'on veut justement laisser mourir.
        window.destroyed.connect(self._forget_detail_window)
        self._detail_windows.append(window)
        window.show()

    def _forget_detail_window(self, window=None) -> None:
        """Retire de la liste les fenêtres de détail déjà détruites.

        Ne pas viser `window` directement : son wrapper Python peut survivre
        à l'objet C++, et le toucher lèverait alors un `RuntimeError` de
        shiboken. On filtre donc sur la validité, ce qui reste correct même
        si le signal arrive deux fois.
        """
        self._detail_windows = [
            candidate
            for candidate in self._detail_windows
            if candidate is not window and _still_alive(candidate)
        ]

    def _selected_node(self):
        """Le nœud sélectionné, ou None s'il n'y en a pas exactement un."""
        if self.graph is None:
            return None
        selected = self.view.selected_oids()
        if len(selected) != 1:
            return None
        return self.graph.node(selected[0])

    def _run_action(self, action: str | None, node) -> None:
        """Exécute une action du menu — le seul endroit qui écrit (§7.0).

        La surveillance est suspendue le temps de l'opération : le
        rafraîchissement est déjà assuré par `repository_changed`, et
        laisser le watcher réagir déclencherait une reconstruction de plus
        (§7.9).
        """
        if action is None or node is None or self.state is None:
            return

        context = ActionContext(
            repository=self.repository,
            node=node,
            state=self.state,
            parent=self,
            ask_name=ask_name,
            ask_mode=ask_reset_mode,
            confirm=confirm,
            copy=self._copy_to_clipboard,
        )

        if action == "fetch_remote":
            # Le fetch part dans un fil séparé : mesuré, il gelait
            # l'interface 1,6 s même sans rien ramener.
            self._start_fetch()
            return

        if action == "open_commit":
            self.open_commit_window()
            return

        if action == "push_branch":
            self._start_push()
            return

        if action == "pull_branch":
            self._start_pull()
            return

        with self.watcher.suspended():
            result = actions.execute_action(action, context)

        if result is None:
            return  # annulé par l'utilisateur, ou action sans effet

        if result.repository_changed:
            self.refresh()

        if not result.success:
            show_error(self, result)

    def _start_fetch(self) -> None:
        """Lance un fetch en arrière-plan, avec progression."""
        if self._task is not None and self._task.is_running():
            self.statusBar().showMessage("Fetch already running", 3000)
            return

        from tortoisepy.core import operations

        self.progress.setRange(0, 0)  # indéterminé tant que le total est inconnu
        self.progress.setFormat("Fetching…")
        self.progress.show()
        self.statusBar().showMessage("Fetching…")

        worker = FetchWorker(
            lambda on_progress: operations.fetch_remote(
                self.repository, on_progress=on_progress
            )
        )
        self._task = BackgroundTask(worker, self)
        self._task.progress.connect(self._on_fetch_progress)
        self._task.finished.connect(self._on_fetch_finished)

        # La surveillance reste suspendue jusqu'au retour : sans cela, les
        # refs écrites par le fetch déclencheraient un rafraîchissement en
        # plus de celui que nous faisons déjà (§7.9).
        self.watcher.stop()
        self._task.start()

    def _on_fetch_progress(self, received: int, total: int) -> None:
        if total > 0:
            self.progress.setRange(0, total)
            self.progress.setValue(received)
            self.progress.setFormat(f"%v / %m objects")
        else:
            self.progress.setRange(0, 0)

    def _on_fetch_finished(self, result) -> None:
        self.progress.hide()
        self.watcher.start()

        if not result.success:
            show_error(self, result)
            self._update_status()
            return

        # Le message AVANT le rafraîchissement : celui-ci appelle
        # `_update_status`, qui écraserait le résumé du fetch. Sur un gros
        # dépôt, la reconstruction prend plusieurs secondes — le message
        # disparaîtrait sans avoir été lu.
        self._fetch_summary = result.summary

        if result.repository_changed:
            self.refresh()

        # Réaffiché après le refresh, pour qu'il survive à `_update_status`.
        # Le résumé nomme les refs arrivées : « new: origin/feature, v2.0 ».
        self.statusBar().showMessage(result.summary, 15000)
        self._fetch_summary = None

    def _update_push_action(self) -> None:
        """Grise le bouton quand il n'y a rien à pousser.

        Un bouton actif qui ne fait rien apprend à ignorer l'interface ;
        l'infobulle dit pourquoi il est grisé (§6.2).
        """
        state = push_state(self.repository)
        self.push_action.setEnabled(state.can_push)
        if state.can_push:
            self.push_action.setToolTip(
                f"Push {state.unpushed_count} commit(s) to {state.remote_name}"
            )
        else:
            self.push_action.setToolTip(state.reason or "nothing to push")

    def _start_push(self, confirmed: bool = False) -> None:
        """Pousse en arrière-plan, comme le fetch (§6.3).

        `confirmed` sert au second essai après saisie des identifiants :
        l'utilisateur vient de confirmer puis de s'authentifier, lui
        redemander deux fois de suite serait pénible.
        """
        if self._task is not None and self._task.is_running():
            self.statusBar().showMessage("A background task is running", 3000)
            return

        state = push_state(self.repository)
        if not confirmed:
            request = ConfirmationRequest(
                title="Push",
                message=(
                    f"git push {state.remote_name} {state.branch}\n\n"
                    f"{state.unpushed_count} commit(s) will be sent to the "
                    "shared server. This cannot be undone on your own."
                ),
                destructive=False,
            )
            if not confirm(self, request):
                return

        from tortoisepy.core import operations

        self.progress.setRange(0, 0)
        self.progress.setFormat("Pushing…")
        self.progress.show()
        self.statusBar().showMessage("Pushing…")

        worker = FetchWorker(
            lambda on_progress: operations.push_branch(
                self.repository, on_progress=on_progress
            )
        )
        self._task = BackgroundTask(worker, self)
        self._task.progress.connect(self._on_fetch_progress)
        self._task.finished.connect(self._on_push_finished)
        self._task.start()

    def _on_push_finished(self, result) -> None:
        """Le graphe change : la branche de suivi a avancé."""
        self.progress.hide()
        self.refresh()          # d'abord : `refresh` réécrit la barre d'état
        self.statusBar().showMessage(result.summary, 15000)

        if result.success:
            return

        if _needs_authentication(result) and self._ask_and_store_credentials():
            # Git connaît désormais les identifiants : le rappel les
            # retrouvera tout seul au prochain essai.
            self._start_push(confirmed=True)
            return

        show_error(self, result)

    def _ask_and_store_credentials(self) -> bool:
        """Demande les identifiants et les confie à Git. Vrai si fournis.

        Uniquement en dernier recours : `git credential` est interrogé
        d'abord, donc le cas courant n'affiche aucune fenêtre.
        """
        remote = self._push_remote()
        if remote is None or not is_https(remote.url or ""):
            return False

        found, remember_it = ask_credentials(self, remote.url)
        if found is None:
            return False

        if remember_it and not remember(remote.url, found):
            # Échec du stockage : on le dit, mais on laisse l'essai suivant
            # se faire — la session en cours peut très bien aboutir.
            self.statusBar().showMessage(
                "Credentials could not be saved by Git", 8000
            )
        return True

    def _push_remote(self):
        """Le remote vers lequel le push partirait, ou `None`."""
        state = push_state(self.repository)
        if state.remote_name is None:
            return None
        try:
            return self.repository.remotes[state.remote_name]
        except (KeyError, pygit2.GitError):
            return None

    def _copy_to_clipboard(self, text: str) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)

    def _update_fetch_action(self) -> None:
        """Grise Fetch quand il n'y a pas de remote à interroger."""
        remotes = list(self.repository.remotes.names())
        self.fetch_action.setEnabled(bool(remotes))
        if remotes:
            self.fetch_action.setToolTip(
                "Fetch from " + ", ".join(remotes[:3])
            )
        else:
            self.fetch_action.setToolTip("no remote configured")

    def _update_pull_action(self) -> None:
        """Active le bouton dès qu'une récupération est possible.

        Contrairement à Push, on ne peut pas savoir **sans fetch** ce qui
        attend sur le serveur : `analyse_pull` compare à une référence
        distante qui peut dater. Griser sur cette base afficherait
        « Already up to date » alors qu'un pull ramènerait du travail —
        exactement le cas courant, signalé par l'utilisateur.

        Le bouton reste donc actif dès qu'il y a un remote et une branche :
        c'est le pull lui-même, qui fetch d'abord, qui tranche.
        """
        state = analyse_pull(self.repository)
        self.pull_action.setEnabled(state.kind is not PullKind.UNAVAILABLE)

        if state.kind is PullKind.UNAVAILABLE:
            self.pull_action.setToolTip(state.reason or "nothing to pull")
        elif state.incoming:
            self.pull_action.setToolTip(
                f"Pull {state.incoming} commit(s) from {state.remote_name}"
            )
        else:
            # « d'après ce qu'on sait » : le fetch peut révéler autre chose.
            self.pull_action.setToolTip(
                f"Fetch and pull from {state.remote_name}"
            )

    def _start_pull(self) -> None:
        """Récupère en arrière-plan.

        Un fetch d'abord, **toujours** : sans lui l'analyse porterait sur
        une ref distante périmée et conclurait « à jour » à tort (§3).
        Pull n'est pas confirmé : son effet reste annulable (§4).
        """
        if self._task is not None and self._task.is_running():
            self.statusBar().showMessage("A background task is running", 3000)
            return

        # La stratégie n'est PAS choisie ici : avant le fetch, l'analyse
        # porte sur une référence distante périmée et ne voit pas encore la
        # divergence. Le fil de fond s'arrêtera pour poser la question.
        self._pull_strategy = None

        self.progress.setRange(0, 0)
        self.progress.setFormat("Pulling…")
        self.progress.show()
        self.statusBar().showMessage("Pulling…")

        worker = FetchWorker(
            lambda on_progress: self._pull_after_fetch(on_progress)
        )
        self._task = BackgroundTask(worker, self)
        self._task.progress.connect(self._on_fetch_progress)
        self._task.finished.connect(self._on_pull_finished)
        self._task.start()

    def _pull_after_fetch(self, on_progress):
        """Fetch, puis applique la stratégie qui convient.

        Tourne dans le fil de fond. La stratégie a été choisie **avant**,
        dans le fil d'interface : Qt interdit d'ouvrir un dialogue ici.
        """
        from tortoisepy.core import operations

        fetched = operations.fetch_remote(
            self.repository, on_progress=on_progress
        )
        if not fetched.success:
            return fetched

        state = analyse_pull(self.repository)
        if state.kind is PullKind.UP_TO_DATE:
            return succeeded("Already up to date", repository_changed=False)
        if state.kind is PullKind.FAST_FORWARD:
            return pull_fast_forward(self.repository)
        if state.kind is PullKind.UNAVAILABLE:
            return failed("Pull", state.reason)

        # Divergence : on ne choisit pas à la place de l'utilisateur (D11).
        # Qt interdit d'ouvrir un dialogue depuis ce fil, donc on rend la
        # main ; `_on_pull_finished` posera la question et relancera.
        if self._pull_strategy is None:
            return failed(
                "Pull", _NEEDS_STRATEGY, repository_changed=False
            )

        if self._pull_strategy == "rebase":
            return pull_rebase(self.repository)
        return pull_merge(self.repository)

    def _resume_pull_with_strategy(self) -> None:
        """Pose la question merge/rebase, puis reprend le pull.

        Le fetch a déjà eu lieu, donc l'analyse est cette fois exacte.
        Annuler laisse simplement les nouvelles refs distantes en place,
        ce qui est sans danger (§5).
        """
        state = analyse_pull(self.repository)
        if state.kind is not PullKind.DIVERGED:
            return  # la situation a changé entre-temps

        chosen = ask_pull_strategy(self, state)
        if chosen is None:
            self.statusBar().showMessage("Pull cancelled", 8000)
            return

        self._pull_strategy = chosen
        if chosen == "rebase":
            result = pull_rebase(self.repository)
        else:
            result = pull_merge(self.repository)
        self._on_pull_finished(result)

    def _on_pull_finished(self, result) -> None:
        """Un conflit ouvre la fenêtre de résolution, jamais une impasse."""
        self.progress.hide()
        self.refresh()          # d'abord : `refresh` réécrit la barre d'état
        self.statusBar().showMessage(result.summary or "Pull finished", 15000)

        if result.success:
            return

        # Divergence : la question n'a pas pu être posée depuis le fil de
        # fond, on la pose maintenant et on reprend.
        if (result.git_error or "") == _NEEDS_STRATEGY:
            self._resume_pull_with_strategy()
            return

        # « rolled back » : le rebase a tout restauré, il n'y a plus rien à
        # résoudre. Ouvrir la fenêtre afficherait une liste vide et cacherait
        # le conseil (« try merge instead ») derrière une fausse piste.
        message = (result.git_error or "").lower()
        if "conflict" in message and "rolled back" not in message:
            self.open_conflict_window()
            return

        show_error(self, result)
