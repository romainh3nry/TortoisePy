"""Fenêtre principale — assemblage de §7.

Relie le dépôt, le graphe, la vue, le menu contextuel et la surveillance
de `.git`. Le chrome est natif : Qt s'en charge, conformément au choix de
reproduire le graphe mais pas l'habillage Windows.
"""

from __future__ import annotations

from pathlib import Path

import pygit2
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow,
    QMenu,
    QSplitter,
    QToolBar,
)

from tortoisepy.core.commits import commits_for_node
from tortoisepy.core.graph import build_graph
from tortoisepy.core.state import read_state
from tortoisepy.layout.engine import layout_graph
from tortoisepy.ui import actions
from tortoisepy.ui.actions import ActionContext
from tortoisepy.ui.commit_panel import CommitPanel
from tortoisepy.ui.context_menu import MenuEntry, build_menu_model
from tortoisepy.ui.dialogs import (
    ask_name,
    ask_reset_mode,
    confirm,
    show_error,
)
from tortoisepy.ui.graph_view import GraphView
from tortoisepy.ui.theme import QtMeasurer
from tortoisepy.ui.watcher import RepositoryWatcher


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

        self.setWindowTitle(self._title())
        self.resize(1400, 850)
        self.refresh()

    def refresh(self) -> None:
        """Reconstruit le graphe et relit l'état (§7.6, §7.9)."""
        self.graph = build_graph(self.repository)
        self.state = read_state(self.repository)
        self.view.show_graph(self.graph, layout_graph(self.graph, self.measurer))
        self.commit_panel.clear()
        self._center_on_head()
        self._update_status()

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
            label, commits_for_node(self.repository, self.graph, oid)
        )

    def _refresh_state_only(self) -> None:
        """Relit l'état sans reconstruire le graphe — bien moins coûteux."""
        self.state = read_state(self.repository)
        self._update_status()

    def _title(self) -> str:
        workdir = self.repository.workdir
        name = Path(workdir).name if workdir else Path(self.repository.path).name
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
        ]

        for label, shortcut, slot in specs:
            action = QAction(label, self)
            action.setShortcut(shortcut)
            action.triggered.connect(slot)
            self.addAction(action)
            self.toolbar.addAction(action)

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

        with self.watcher.suspended():
            result = actions.execute_action(action, context)

        if result is None:
            return  # annulé par l'utilisateur, ou action sans effet

        if result.repository_changed:
            self.refresh()

        if not result.success:
            show_error(self, result)

    def _copy_to_clipboard(self, text: str) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)
