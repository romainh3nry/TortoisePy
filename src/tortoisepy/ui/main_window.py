"""Fenêtre principale — assemblage de §7.

Relie le dépôt, le graphe, la vue, le menu contextuel et la surveillance
de `.git`. Le chrome est natif : Qt s'en charge, conformément au choix de
reproduire le graphe mais pas l'habillage Windows.
"""

from __future__ import annotations

from pathlib import Path

import pygit2
import shiboken6
from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QProgressBar,
    QSizePolicy,
    QSplitter,
    QToolBar,
    QToolButton,
    QWidget,
)

from tortoisepy.cli import find_repository
from tortoisepy.core import operations
from tortoisepy.core.commits import commits_for_node
from tortoisepy.core.graph import build_graph
from tortoisepy.core.graph_cache import GraphCache, repo_fingerprint
from tortoisepy.core.credentials import is_https, remember
from tortoisepy.core.options import GraphOptions
from tortoisepy.core.pull import (
    PullKind,
    analyse_pull,
    pull_fast_forward,
    pull_merge,
    pull_rebase,
)
from tortoisepy.core.push_state import divergence, push_state, unpushed_oids
from tortoisepy.core.rebase import rebase_targets, start_rebase
from tortoisepy.core.results import failed, succeeded
from tortoisepy.core.search import search_commits
from tortoisepy.core.shortcuts import CATALOGUE
from tortoisepy.core.state import read_state
from tortoisepy.layout.engine import layout_graph
from tortoisepy.ui import actions
from tortoisepy.ui.actions import ActionContext
from tortoisepy.ui.settings_store import SettingsStore
from tortoisepy.ui.commit_detail_window import CommitDetailWindow
from tortoisepy.ui.commit_panel import CommitPanel
from tortoisepy.ui.commit_window import CommitWindow
from tortoisepy.ui.conflict_window import ConflictWindow
from tortoisepy.ui.context_menu import MenuEntry, build_menu_model
from tortoisepy.ui.dialogs import (
    ConfirmationRequest,
    RebaseDialog,
    ask_branch,
    ask_credentials,
    ask_name,
    ask_pull_strategy,
    ask_reset_mode,
    confirm,
    confirmation_for,
    show_error,
)
from tortoisepy.ui.graph_view import GraphView
from tortoisepy.ui.tasks import BackgroundTask, CallableWorker, FetchWorker
from tortoisepy.ui.theme import QtMeasurer
from tortoisepy.ui.watcher import RepositoryWatcher


_NEEDS_STRATEGY = "diverged: ask how to combine"
"""Marqueur interne : le fil de fond rend la main pour poser la question.

Ce n'est pas une erreur — juste le seul moyen de faire ouvrir un dialogue
par le fil d'interface, Qt l'interdisant depuis un fil de travail.
"""


_AUTH_MARKERS = (
    "authentication",
    "credential",
    "401",
    "403",
    # Le push forcé passe par le `git` du système, qui ne parle pas comme
    # libgit2. Sans identifiant en cache, et avec `GIT_TERMINAL_PROMPT=0`
    # (indispensable pour ne pas suspendre l'application), il répond
    # « could not read Username for 'https://…': terminal prompts
    # disabled » — vérifié. Aucun des marqueurs de libgit2 n'y figure :
    # sans ces trois-là, la fenêtre d'identifiants ne s'ouvrait pas et
    # l'utilisateur restait devant une erreur sans issue.
    "could not read username",
    "could not read password",
    "terminal prompts disabled",
)


def _needs_authentication(result) -> bool:
    """L'échec vient-il d'un défaut d'authentification ?

    Vérifié : sans rappel, libgit2 lève `AuthError` avec le message
    « remote authentication required but no callback set ». On teste des
    marqueurs plutôt que la chaîne exacte, qui dépend de la version de
    libgit2, du serveur, et — depuis le push forcé — du `git` installé.
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

    def __init__(self, repository: pygit2.Repository, parent=None,
                 settings: SettingsStore | None = None):
        super().__init__(parent)
        self.repository = repository
        self.settings = settings or SettingsStore()
        self.measurer = QtMeasurer()
        self.graph = None
        self.state = None
        # Évite de reconstruire un graphe inchangé : mesuré, 792 ms le
        # premier appel contre 2 ms au second sur le même dépôt (phase 13).
        self._graph_cache = GraphCache()
        # Historique par nœud. `commits_for_node` coûte **292 ms** sur
        # 3 000 commits (mesuré), et il rechargeait le même nœud à chaque
        # rafraîchissement : 4 appels pour un seul OID distinct.
        #
        # La clé d'invalidation est l'empreinte du dépôt — celle qui sert
        # déjà au graphe. Elle couvre les deux dépendances : l'historique
        # (le dépôt) et le marquage `own` (le graphe), puisqu'à empreinte
        # égale `build_graph` rend le même graphe.
        self._panel_cache: dict[str, tuple] = {}
        self._panel_cache_key: tuple | None = None
        self._selection_avant_refresh: str | None = None
        self._head_avant_refresh: str | None = None
        # Largeur de panneau mémorisée, appliquée au premier `showEvent`
        # (voir `restore_settings`/`showEvent` : le splitter n'a pas de
        # vraie taille avant le premier affichage).
        self._largeur_panneau_en_attente: int | None = None

        self.view = GraphView(self)
        self.view.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.view.customContextMenuRequested.connect(self._show_context_menu)
        # Simple clic : la sélection affiche les commits. C'est le même
        # geste que sélectionner, donc le plus direct. Le double-clic reste
        # branché — il ne coûte rien et fait la même chose.
        self.view.selection_changed.connect(self._on_selection_changed)
        self.view.node_double_clicked.connect(self._on_node_double_clicked)

        # Le panneau révèle ce que la compression masque (§4.2.1). Un
        # splitter plutôt qu'une largeur fixe : la place à donner au graphe
        # dépend de la longueur des noms de branches.
        self.commit_panel = CommitPanel(self)
        self.commit_panel.commit_activated.connect(self.open_commit_detail)
        self.commit_panel.context_menu_requested.connect(
            self._show_panel_menu
        )
        # Le champ appartient au panneau (il en épouse la largeur) ; la
        # fenêtre s'y branche sans le posséder.
        self.search_field = self.commit_panel.search_field
        # Sur validation, pas à la frappe : chercher coûte ~325 ms sur
        # 3 000 commits (mesuré), ce qui rendrait la saisie inutilisable.
        self.search_field.returnPressed.connect(self.run_search)
        self._detail_windows: list[CommitDetailWindow] = []
        # Chaque dépôt récent ouvert crée une nouvelle fenêtre : sans
        # garder une référence, le ramasse-miettes la détruirait aussitôt
        # (même piège que `_detail_windows`).
        self._recent_windows: list[MainWindow] = []
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
        # Centré une seule fois, à l'ouverture : sur un graphe de
        # plusieurs milliers de pixels de haut, s'ouvrir ailleurs
        # obligerait à chercher où l'on se trouve. Les rafraîchissements
        # suivants respectent le déplacement de l'utilisateur.
        self._center_on_head()
        self.restore_settings()
        self.settings.remember_repository(
            str(Path(repository.path).parent)
        )

    def geometry_is_visible(self, geometry) -> bool:
        """La géométrie recoupe-t-elle un écran réellement présent ?

        Sans ce contrôle, une fenêtre mémorisée sur un moniteur débranché
        rouvrirait hors de tout écran : invisible, et impossible à
        rattraper autrement qu'en supprimant les préférences (§D51).
        """
        for ecran in QGuiApplication.screens():
            if ecran.availableGeometry().intersects(geometry):
                return True
        return False

    def restore_settings(self) -> None:
        """Réapplique les réglages mémorisés, en se méfiant de chacun.

        La largeur du panneau n'est PAS appliquée ici : à cet instant
        (appelé depuis `__init__`), la fenêtre n'a jamais été affichée et
        le splitter n'a donc pas encore été mis en page — `sizes()` y
        rend `[0, 0]` et toute largeur posée maintenant serait de toute
        façon écrasée par la mise en page que Qt effectue au premier
        `show()` (mesuré : une largeur de 300 enregistrée revenait à 524
        après `show()`). Elle est donc mémorisée et appliquée une seule
        fois depuis `showEvent`, quand le splitter a une vraie largeur.
        """
        brut = self.settings.value("window/geometry")
        if isinstance(brut, (bytes, QByteArray)):
            sauvegarde = self.saveGeometry()
            if self.restoreGeometry(QByteArray(brut)):
                if not self.geometry_is_visible(self.geometry()):
                    self.restoreGeometry(sauvegarde)

        zoom = self.settings.value("view/zoom")
        if isinstance(zoom, (int, float)) and zoom > 0:
            self.view.set_zoom(float(zoom))

        largeur = self.settings.value("view/panel_width")
        if isinstance(largeur, int) and largeur > 0:
            self._largeur_panneau_en_attente = largeur

    def showEvent(self, event) -> None:
        """Applique la largeur de panneau différée, une seule fois.

        Le premier `show()` remet en page le splitter (Qt lui donne alors
        sa vraie taille) : c'est le premier moment où `setSizes` a un
        total fiable sur lequel s'appuyer. `_largeur_panneau_en_attente`
        est remis à `None` juste après pour ne jamais écraser un
        redimensionnement fait ensuite par l'utilisateur, y compris lors
        d'un `show()` ultérieur (ex. après une minimisation).
        """
        super().showEvent(event)
        largeur = self._largeur_panneau_en_attente
        if largeur is not None:
            self._largeur_panneau_en_attente = None
            total = sum(self.splitter.sizes())
            if total > largeur:
                self.splitter.setSizes([total - largeur, largeur])

    def save_settings(self) -> None:
        """Mémorise l'état courant. Appelé à la fermeture."""
        self.settings.set_value(
            "window/geometry", bytes(self.saveGeometry())
        )
        self.settings.set_value("view/zoom", self.view.current_zoom())
        tailles = self.splitter.sizes()
        if len(tailles) > 1:
            self.settings.set_value("view/panel_width", tailles[1])

    def closeEvent(self, event) -> None:
        self.save_settings()
        super().closeEvent(event)

    def graph_options(self) -> GraphOptions:
        """Options d'affichage courantes.

        Seul `show_tags` est réglable (§5.3) : les quatre autres gardent
        les défauts que `options.py` justifie par des mesures.
        """
        return GraphOptions(show_tags=self.show_tags_action.isChecked())

    def _on_tags_toggled(self, checked: bool) -> None:
        self.settings.set_value("view/show_tags", checked)
        self.refresh()

    def refresh(self) -> None:
        """Reconstruit le graphe et relit l'état (§7.6, §7.9)."""
        # Mémorisée AVANT la reconstruction : `show_graph` remplace la
        # scène, et la sélection part avec les anciens items.
        selection = self.view.selected_oids()
        self._selection_avant_refresh = selection[0] if selection else None
        # HEAD d'AVANT : s'il change, c'est un checkout, et la sélection
        # doit suivre la nouvelle branche plutôt que rester sur l'ancienne
        # (sinon le panneau latéral montrerait la branche qu'on vient de
        # quitter).
        self._head_avant_refresh = (
            self.state.head_oid if self.state else None
        )
        # `show_graph` remplace la scène, ce qui remet les barres à zéro.
        # On les restaure après, pour que la vue ne saute pas.
        defilement = (
            self.view.horizontalScrollBar().value(),
            self.view.verticalScrollBar().value(),
        )

        options = self.graph_options()
        self.graph = self._graph_cache.get(
            self.repository,
            lambda repo: build_graph(repo, options),
            options_key=(options.show_tags,),
        )
        self.state = read_state(self.repository)

        # Le nœud de travail est greffé APRÈS le cache : il dépend de
        # l'arbre de travail, qui change bien plus souvent que la
        # topologie. L'inclure dans le graphe mis en cache obligerait à
        # tout reconstruire à chaque frappe dans un éditeur.
        self.graph = _avec_noeud_de_travail(self.graph, self.state)
        unpushed = unpushed_oids(self.repository)
        # Le mesureur est refait à chaque rafraîchissement : la branche
        # courante change au gré des checkouts, et elle décide si la
        # ligne `HEAD` occupe de la place (sinon le nœud courant réserve
        # une ligne qu'il ne dessine pas).
        courante = self.state.head_branch if self.state else None
        self.measurer = QtMeasurer(current_branch=courante)

        self.view.show_graph(
            self.graph,
            layout_graph(self.graph, self.measurer),
            unpushed,
            # `None` si HEAD est détachée : la ligne HEAD devient alors le
            # seul repère du nœud courant (§4.2 de la spec).
            current_branch=courante,
        )
        self.commit_panel.clear()

        # PAS de recentrage ici : `refresh()` est appelé après CHAQUE
        # action, et ramener la vue de force sur la branche courante
        # défaisait le déplacement de l'utilisateur (signalé). Le
        # centrage n'a lieu qu'à l'ouverture et sur « Recenter ».
        #
        # La SÉLECTION, elle, est conservée : elle remplit le panneau
        # latéral, et la perdre à chaque rafraîchissement le viderait
        # sans raison.
        self._reselect_current_node()
        self.view.horizontalScrollBar().setValue(defilement[0])
        self.view.verticalScrollBar().setValue(defilement[1])
        self._update_status()
        self._update_push_action()
        self._update_fetch_action()
        self._update_pull_action()

    def closeEvent(self, event) -> None:
        """Attend la tâche de fond avant de rendre la fenêtre.

        Sans cette attente, fermer pendant un fetch ou un push détruisait
        le `QThread` en pleine exécution — reproduit : « QThread:
        Destroyed while thread is still running ». Le défaut préexistait,
        mais un push forcé peut durer jusqu'à cinq minutes (il passe par
        `git`), là où un fetch se comptait en secondes : la fenêtre pour
        tomber dessus est devenue large.

L'attente passe par `stop()`, qui **demande** l'arrêt avant
        d'attendre : `wait()` seul bloquerait jusqu'au délai maximum,
        puisque `quit()` n'est appelé que depuis le fil principal. Une
        première version bouclait en pompant les événements et tournait
        dix secondes pour rien face à un double de test dont
        `is_running()` rend toujours vrai (vérifié — quatre tests en
        démontage cassé). `getattr` parce que ces doubles n'ont pas
        forcément la méthode.
        """
        self.watcher.stop()
        tache = self._task
        if tache is not None:
            arreter = getattr(tache, "stop", None)
            if callable(arreter):
                arreter(10_000)
        super().closeEvent(event)

    def _reselect_current_node(self) -> None:
        """Rend sa sélection au nœud qui l'avait, après reconstruction.

        `show_graph` remplace la scène : les items sont neufs, et la
        sélection précédente disparaît avec les anciens. Sans cette
        restauration, le panneau latéral se viderait à chaque action.
        """
        courant = self.state.head_oid if self.state else None

        # Un checkout déplace HEAD : la sélection le suit, car c'est la
        # branche que l'utilisateur vient de choisir.
        if courant is not None and courant != self._head_avant_refresh:
            self.view.select_node(courant)
            return

        if self._selection_avant_refresh:
            self.view.select_node(self._selection_avant_refresh)
        elif courant is not None:
            self.view.select_node(courant)

    def _center_on_head(self) -> None:
        """Place la vue sur la branche courante **et la sélectionne**.

        Le nœud vert est le repère de l'utilisateur : sur un dépôt dont le
        graphe fait plusieurs milliers de pixels de haut, s'ouvrir ailleurs
        l'oblige à chercher où il se trouve.

        La sélection suit le centrage : après un checkout, la vue se
        déplaçait bien sur la branche, mais le panneau latéral restait vide
        faute de sélection — comme si l'utilisateur n'avait rien cliqué,
        alors qu'il venait justement de choisir cette branche.
        """
        if self.state is None or self.state.head_oid is None:
            return
        self.view.center_on_node(self.state.head_oid)
        self.view.select_node(self.state.head_oid)

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

    def _on_node_double_clicked(self, oid: str) -> None:
        """Double-clic : le geste explicite.

        Signalé par l'utilisateur : l'application gelait au simple CLIC
        sur le nœud de travail. Le clic passe par `_on_selection_changed`,
        qui appelait `_show_commits` — lequel ouvrait la fenêtre de commit.
        Sur un gros dépôt, sa construction scanne tout l'arbre de travail.

        Ouvrir une fenêtre doit rester un geste délibéré.
        """
        from tortoisepy.core.model import WORKING_OID

        if oid == WORKING_OID:
            self.open_commit_window()
            return

        self._show_commits(oid)

    def _show_commits(self, oid: str) -> None:
        """Liste les commits masqués par l'arête entrante.

        Le nœud « Uncommitted changes » n'en a aucun : on vide le panneau
        plutôt que d'y laisser l'historique du nœud précédent. Son OID est
        par ailleurs une sentinelle que pygit2 REFUSE (`InvalidError`,
        vérifié) — la lui passer planterait.
        """
        from tortoisepy.core.model import WORKING_OID

        if oid == WORKING_OID:
            self.commit_panel.clear()
            return

        if self.graph is None:
            return

        node = self.graph.node(oid)
        if node is None:
            return

        label = " | ".join(r.name for r in node.refs) or f"[{oid[:8]}]"
        self.commit_panel.show_commits(
            label,
            self._commits_for(oid),
            # **Hors du cache, à dessein** : les marqueurs de non-poussé
            # changent après un push alors qu'aucun commit n'a bougé. Les
            # figer afficherait des flèches fantômes. On met en cache
            # l'historique, pas sa décoration.
            unpushed=unpushed_oids(self.repository),
        )

    def _commits_for(self, oid: str) -> tuple:
        """Historique d'un nœud, relu seulement si le dépôt a changé."""
        empreinte = repo_fingerprint(self.repository)
        if empreinte != self._panel_cache_key:
            self._panel_cache.clear()
            self._panel_cache_key = empreinte

        if oid not in self._panel_cache:
            self._panel_cache[oid] = commits_for_node(
                self.repository, self.graph, oid
            )
        return self._panel_cache[oid]

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

        # Accès à la fenêtre des raccourcis. Volontairement sans raccourci
        # clavier : elle ne fait pas partie des dix actions du catalogue,
        # et lui en donner un serait incohérent (un raccourci non
        # modifiable dans la fenêtre qui sert justement à les modifier).
        self.shortcuts_action = QAction("Keyboard Shortcuts…", self)
        self.shortcuts_action.triggered.connect(self.open_shortcuts_window)
        toolbar.addAction(self.shortcuts_action)

        # Seul filtre exposé (§5.3, D52) : les quatre autres gardent leurs
        # défauts mesurés (voir `core/options.py`).
        # Demandé par l'utilisateur : revenir sur la branche courante après
        # s'être déplacé dans le graphe. Pas de raccourci clavier — elle
        # n'est pas dans le catalogue des dix actions raccourcissables.
        self.recenter_action = QAction("Recenter", self)
        self.recenter_action.setToolTip(
            "Bring the current branch back into view"
        )
        self.recenter_action.triggered.connect(self._center_on_head)
        toolbar.addAction(self.recenter_action)

        self.show_tags_action = QAction("Show tags", self)
        self.show_tags_action.setCheckable(True)
        self.show_tags_action.setChecked(
            bool(self.settings.value("view/show_tags"))
        )
        self.show_tags_action.toggled.connect(self._on_tags_toggled)
        toolbar.addAction(self.show_tags_action)

        # Bouton à menu déroulant plutôt qu'une barre de menus : ce projet
        # n'a pas de `QMenuBar`, tout vit dans la barre d'outils.
        self.recent_button = QToolButton(self)
        self.recent_button.setText("Open Recent")
        self.recent_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )
        recent_menu = QMenu(self.recent_button)
        # Peuplé à l'ouverture, pas à la construction : la liste change
        # quand d'autres fenêtres s'ouvrent, et `recent_repositories()`
        # purge les dépôts disparus à la lecture — un menu construit une
        # fois pourrait montrer un dépôt qui n'existe déjà plus.
        recent_menu.aboutToShow.connect(self._populate_recent_menu)
        self.recent_button.setMenu(recent_menu)
        toolbar.addWidget(self.recent_button)

        return toolbar

    def _populate_recent_menu(self) -> None:
        """Reconstruit le menu des dépôts récents à chaque ouverture."""
        menu = self.recent_button.menu()
        menu.clear()

        recents = self.settings.recent_repositories()
        if not recents:
            vide = menu.addAction("No recent repositories")
            vide.setEnabled(False)
            return

        for path in recents:
            action = menu.addAction(path)
            # `path=path` fige la valeur : sans ça, toutes les actions
            # partageraient la dernière valeur de la boucle (piège
            # classique des fermetures dans une boucle Python/Qt).
            action.triggered.connect(
                lambda checked=False, path=path: self.open_recent_repository(
                    path
                )
            )

    def open_recent_repository(self, path: str) -> None:
        """Ouvre `path` dans une NOUVELLE fenêtre, sans toucher la courante.

        La référence est gardée dans `_recent_windows` : sans elle, le
        ramasse-miettes détruirait la fenêtre aussitôt (même piège que
        `_detail_windows`, cf. `open_commit_detail`).
        """
        repository = find_repository(path)
        if repository is None:
            self.statusBar().showMessage(
                f"Could not open {path}", 15000
            )
            return

        window = MainWindow(repository, settings=self.settings)
        window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        window.destroyed.connect(self._forget_recent_window)
        self._recent_windows.append(window)
        window.show()

    def _forget_recent_window(self, window=None) -> None:
        """Retire de la liste les fenêtres de dépôts récents déjà détruites.

        Même précaution que `_forget_detail_window` : on filtre sur la
        validité plutôt que de comparer `window` directement, car son
        wrapper Python peut survivre à l'objet C++ détruit.
        """
        self._recent_windows = [
            candidate
            for candidate in self._recent_windows
            if candidate is not window and _still_alive(candidate)
        ]

    def focus_search(self) -> None:
        """Place le curseur dans le champ de recherche.

        Le contenu est sélectionné : une nouvelle recherche remplace
        alors la précédente sans avoir à l'effacer d'abord.
        """
        self.search_field.setFocus()
        self.search_field.selectAll()

    def run_search(self) -> None:
        """Surligne les commits correspondants, et dit combien."""
        motif = self.search_field.text()
        if not motif.strip():
            # Motif vide : on lève le filtre et le surlignage plutôt que
            # de chercher — c'est le geste « annuler la recherche ».
            self.view.highlight(())
            self.commit_panel.filter_to(None)
            self.statusBar().showMessage("", 1)
            return

        trouves = search_commits(self.repository, motif)
        self.view.highlight(trouves)
        # Le graphe montre 10 nœuds pour 3 000 commits : sans filtrer la
        # liste, l'utilisateur voit *quels nœuds* contiennent un résultat
        # mais pas *quels commits* (demandé par l'utilisateur).
        visibles = self.commit_panel.filter_to(trouves)

        if not trouves:
            self.statusBar().showMessage("no commit found", 15000)
            return

        if visibles:
            self.statusBar().showMessage(
                f"{len(trouves)} commit(s) found — {visibles} in this list",
                15000,
            )
        elif self.view.highlighted_count():
            # Trouvés, hors de cette liste, mais sur un nœud visible :
            # l'utilisateur a où aller.
            self.statusBar().showMessage(
                f"{len(trouves)} commit(s) found, none in this list — "
                "select a highlighted node to see them",
                15000,
            )
        else:
            # Trouvés, mais ni dans la liste ni sur un nœud : le graphe
            # compresse les chaînes (3 000 commits -> 10 nœuds) et le
            # panneau est borné aux plus récents. Promettre un nœud
            # surligné serait faux — il n'y en a aucun.
            self.statusBar().showMessage(
                f"{len(trouves)} commit(s) found, but too deep in history "
                "to be shown",
                15000,
            )

    def _build_actions(self) -> None:
        """Actions de navigation (§7.1), raccourcis lus du catalogue.

        Les séquences vivaient ici dans un littéral ; elles sont désormais
        dans `core/shortcuts.py`, ce qui permet de les surcharger depuis
        les préférences. Qt traduit « Ctrl » en ⌘ sur macOS.
        """
        slots = {
            "zoom_in": self.view.zoom_in,
            "zoom_out": self.view.zoom_out,
            "zoom_reset": self.view.reset_zoom,
            "fit_to_window": self.view.fit_to_window,
            "refresh": self.refresh,
            "commit": self.open_commit_window,
            "search": self.focus_search,
            "push": self._start_push,
            "pull": self._start_pull,
            "fetch": self._start_fetch,
        }

        self.actions_by_id: dict[str, QAction] = {}
        for spec in CATALOGUE:
            action = QAction(spec.label, self)
            action.triggered.connect(slots[spec.action_id])
            self.addAction(action)
            self.toolbar.addAction(action)
            self.actions_by_id[spec.action_id] = action

        # Ces trois-là sont manipulées ailleurs (activation/désactivation
        # pendant une opération réseau) : on garde les attributs nommés.
        self.push_action = self.actions_by_id["push"]
        self.pull_action = self.actions_by_id["pull"]
        self.fetch_action = self.actions_by_id["fetch"]

        self.apply_shortcuts(self.settings.resolved_shortcuts())

    def apply_shortcuts(self, resolved: dict[str, str]) -> None:
        """Applique les séquences aux actions, sans relancer l'app."""
        for action_id, sequence in resolved.items():
            action = self.actions_by_id.get(action_id)
            if action is not None:
                action.setShortcut(QKeySequence(sequence))

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

        ecart = divergence(self.repository)
        if ecart is not None and any(ecart):
            avance, retard = ecart
            morceaux = []
            if avance:
                morceaux.append(f"↑{avance}")
            if retard:
                morceaux.append(f"↓{retard}")
            texte += "  " + " ".join(morceaux)
            self.branch_label.setToolTip(
                f"{avance} ahead, {retard} behind — as of your last fetch"
            )
            self.branch_label.setText(texte)
            return

        self.branch_label.setText(texte)
        self.branch_label.setToolTip(texte.removeprefix("⎇ "))

    def _show_panel_menu(self, oid: str, position) -> None:
        """Menu contextuel du panneau latéral (§phase 23).

        Le graphe ne permettait d'agir que sur la POINTE d'une branche :
        `ctx.node.oid` désigne le nœud, et les commits plus anciens que le
        panneau affiche étaient hors de portée (signalé par l'utilisateur).
        """
        entrees = self.commit_panel.menu_for(oid)
        if not entrees:
            return

        menu = QMenu(self)
        for entree in entrees:
            action = menu.addAction(entree.label)
            action.triggered.connect(
                lambda checked=False, nom=entree.action, cible=entree.oid:
                self.run_panel_action(nom, cible)
            )
        menu.exec(position)

    def run_panel_action(self, action: str, oid: str) -> None:
        """Exécute une action du panneau sur UN commit précis.

        Le cherry-pick s'applique sur la branche courante, comme git et
        TortoiseGit : appliquer ailleurs imposerait un checkout, donc de
        quitter sa branche — bien plus que ce qu'on attend d'un clic sur
        « Cherry-pick ».
        """
        if action == "copy_commit_hash":
            self._copy_to_clipboard(oid)
            self.statusBar().showMessage(f"{oid[:8]} copié", 5000)
            return

        if action == "show_commit_detail":
            self.open_commit_detail(oid)
            return

        if self.state is None:
            return

        demande = confirmation_for(action, oid[:8], self.state)
        if demande is not None and not confirm(self, demande):
            return

        if action not in ("cherry_pick_commit", "revert_commit_oid"):
            return

        # Même traitement que les actions du graphe (D61, révisée) : un
        # cherry-pick écrit dans le dépôt et peut durer. La suspension du
        # surveillant reste dans le FIL PRINCIPAL — ses minuteurs Qt ne
        # peuvent pas être démarrés ailleurs (vérifié).
        suspension = self.watcher.suspended()
        suspension.__enter__()

        def ecrire():
            if action == "cherry_pick_commit":
                return operations.cherry_pick(self.repository, oid)
            return operations.revert_commit(self.repository, oid)

        def termine(resultat):
            suspension.__exit__(None, None, None)
            self._set_actions_enabled(True)
            if isinstance(resultat, Exception):
                show_error(self, failed("Action", str(resultat)))
                return
            self._apres_action_panneau(resultat)

        self._set_actions_enabled(False)
        if not self.run_in_background(ecrire, termine, "Opération en cours…"):
            suspension.__exit__(None, None, None)
            self._set_actions_enabled(True)

    def _apres_action_panneau(self, resultat) -> None:
        """Suite d'une action du panneau, une fois l'écriture terminée."""
        if resultat.needs_refresh:
            self._graph_cache.invalidate()
            self.refresh()
        self.statusBar().showMessage(resultat.summary, 15000)

        if resultat.success:
            return

        # Un conflit n'est pas une erreur à lire : c'est un travail à
        # faire. Signalé par l'utilisateur — le message annonçait des
        # conflits sans offrir aucun moyen de les voir ni de les résoudre.
        #
        # Deux formes à reconnaître : « conflits sur : … » que compose
        # `operations`, et le « conflict » que rend libgit2. Ne tester que
        # l'anglais laissait passer le cas le plus courant (vérifié).
        message = (resultat.git_error or "").lower()
        if "conflit" in message or "conflict" in message:
            self.open_conflict_window()
            return

        show_error(self, resultat)

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
                    lambda checked=False, name=entry.action,
                    branch=entry.branch: self._run_action(
                        name, self._selected_node(), branch
                    )
                )

    def _set_actions_enabled(self, actif: bool) -> None:
        """Active ou désactive ce qui pourrait déclencher une écriture.

        Pendant une écriture, le graphe et la barre d'outils sont gelés :
        le verrou de `run_in_background` refuserait de toute façon une
        seconde opération, mais sans retour visuel l'utilisateur
        cliquerait dans le vide.
        """
        self.view.setEnabled(actif)
        self.toolbar.setEnabled(actif)

    def run_in_background(self, appelable, suite, libelle: str) -> bool:
        """Exécute `appelable` hors du fil principal, puis appelle `suite`.

        Demandé par l'utilisateur : « à chaque fois qu'une action est
        susceptible de faire freezer l'app, on la fait en arrière-plan
        avec un loader ». Mesuré sur son dépôt, `build_graph` coûte
        2185 ms et `list_changes` 760 ms — autant de gels.

        Rend `False` si une opération tourne déjà : une seule à la fois,
        et la seconde demande est ignorée plutôt qu'annulée (choix de
        l'utilisateur). Sans ce verrou, deux fils liraient le dépôt en
        même temps et les résultats arriveraient dans le désordre.

        `suite` est appelée **dans le fil principal** : elle peut toucher
        l'interface sans risque. Elle reçoit le résultat, ou l'exception
        si l'opération a échoué.
        """
        if self._task is not None and self._task.is_running():
            return False

        self.progress.setRange(0, 0)     # indéterminé : durée inconnue
        self.progress.show()
        self.statusBar().showMessage(libelle)

        def termine(resultat):
            # La barre disparaît MÊME en cas d'échec : la laisser
            # tourner ferait croire à un travail toujours en cours.
            self.progress.hide()
            self.statusBar().clearMessage()
            suite(resultat)

        self._task = BackgroundTask(CallableWorker(appelable), self)
        self._task.finished.connect(termine)
        self._task.start()
        return True

    def open_commit_window(self) -> None:
        """Ouvre la fenêtre de commit, ou ramène celle déjà ouverte.

        Une seule à la fois : deux fenêtres sur le même dépôt afficheraient
        des états divergents.
        """
        if self.commit_window is not None and self.commit_window.isVisible():
            self.commit_window.raise_()
            self.commit_window.activateWindow()
            return

        # Le coût est dans `list_changes`, que la construction déclenche :
        # 760 ms sur le dépôt de l'utilisateur. On le paie en arrière-plan,
        # avec le loader, puis la fenêtre se construit sur un cache chaud.
        from tortoisepy.core.changes import list_changes

        def construire(_resultat=None):
            self.commit_window = CommitWindow(self.repository, self)
            self.commit_window.committed.connect(self._on_committed)
            self.commit_window.show()

        lance = self.run_in_background(
            lambda: list_changes(self.repository),
            construire,
            "Lecture des modifications…",
        )
        if not lance:
            # Une opération tourne déjà : on construit tout de suite
            # plutôt que d'ignorer la demande de l'utilisateur.
            construire()

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

    def open_shortcuts_window(self) -> None:
        """Fenêtre « Keyboard Shortcuts » (§6.2)."""
        from tortoisepy.ui.shortcuts_window import ShortcutsWindow

        fenetre = ShortcutsWindow(self.settings, self)
        fenetre.shortcuts_changed.connect(self.apply_shortcuts)
        fenetre.exec()

    def start_rebase_onto(self) -> None:
        """Demande la cible, puis rebase la branche courante dessus.

        Le rebase reste au premier plan : il ne passe pas par le réseau,
        et laisser l'utilisateur agir pendant qu'on réécrit ses commits
        inviterait les ennuis.
        """
        cibles = rebase_targets(self.repository)
        if not cibles:
            self.statusBar().showMessage("No branch to rebase onto", 8000)
            return

        courante = self.state.head_branch if self.state else None

        # Deux champs plutôt qu'un : cliquer droit sur une branche puis
        # « Rebase… » rejouait la **courante**, pas celle qu'on avait
        # cliquée, et rien ne le laissait deviner (signalé par
        # l'utilisateur).
        dialogue = RebaseDialog(
            self,
            current_branch=courante,
            local_branches=sorted(self.repository.branches.local),
            targets=cibles,
        )
        if dialogue.exec() != RebaseDialog.DialogCode.Accepted:
            return

        rejouee, cible = dialogue.replayed(), dialogue.target()
        if rejouee is None or cible is None:
            return

        result = start_rebase(
            self.repository,
            cible,
            # `None` quand c'est déjà la courante : on garde alors le
            # chemin éprouvé depuis la phase 9.
            branch=rejouee if rejouee != courante else None,
        )
        self.refresh()
        # En échec, `summary` vaut « Rebase » tout court — le décorateur
        # `guarded` y met l'étiquette de l'opération et réserve le détail
        # à `git_error`. Afficher `summary` seul donnerait un statut muet
        # au moment précis où l'utilisateur a besoin de savoir pourquoi.
        self.statusBar().showMessage(
            result.summary if result.success
            else (result.git_error or result.summary),
            15000,
        )

        if result.success:
            return

        if "conflict" in (result.git_error or "").lower():
            self.open_conflict_window()
            return

        show_error(self, result)

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

    def _run_action(
        self, action: str | None, node, branch: str | None = None
    ) -> None:
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
            chosen_branch=branch,
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

        if action == "force_push_branch":
            self._start_push(force=True)
            return

        if action == "pull_branch":
            self._start_pull()
            return

        if action == "rebase_branch":
            self.start_rebase_onto()
            return

        if action == "open_conflicts":
            self.open_conflict_window()
            return

        # Les écritures aussi passent en arrière-plan (D61, révisée) :
        # sur un gros dépôt, un checkout réécrit des milliers de fichiers
        # et gèle l'interface plusieurs secondes (signalé).
        #
        # Deux précautions que les lectures n'exigent pas : les actions
        # sont DÉSACTIVÉES le temps de l'écriture — lancer un commit
        # pendant qu'un checkout change de branche produirait un résultat
        # imprévisible — et le graphe n'est rafraîchi qu'À LA FIN, sous
        # peine de montrer un état transitoire.
        # La suspension du surveillant reste dans le FIL PRINCIPAL : il
        # manipule des minuteurs Qt, et les démarrer depuis un autre fil
        # provoque « QObject::startTimer: Timers cannot be started from
        # another thread » (vérifié).
        suspension = self.watcher.suspended()
        suspension.__enter__()

        def ecrire():
            return actions.execute_action(action, context)

        def termine(result):
            suspension.__exit__(None, None, None)
            self._set_actions_enabled(True)

            if isinstance(result, Exception):
                show_error(self, failed("Action", str(result)))
                return
            if result is None:
                return  # annulé par l'utilisateur, ou action sans effet

            if result.repository_changed:
                self.refresh()
            if not result.success:
                show_error(self, result)

        self._set_actions_enabled(False)
        if not self.run_in_background(ecrire, termine, "Opération en cours…"):
            # Une opération tourne déjà : on ne lance pas la seconde.
            suspension.__exit__(None, None, None)
            self._set_actions_enabled(True)

    def _start_fetch(self) -> None:
        """Lance un fetch en arrière-plan, avec progression."""
        if self._task is not None and self._task.is_running():
            self.statusBar().showMessage("Fetch already running", 3000)
            return

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

    def _start_push(self, confirmed: bool = False, force: bool = False) -> None:
        """Pousse en arrière-plan, comme le fetch (§6.3).

        `confirmed` sert au second essai après saisie des identifiants :
        l'utilisateur vient de confirmer puis de s'authentifier, lui
        redemander deux fois de suite serait pénible.

        `force` sélectionne `--force-with-lease` : le bail est arbitré par
        le **serveur**, pas vérifié côté client puis poussé sans condition
        (D15 — voir `_push_with_lease` dans core/operations.py pour la
        course qu'un simple `+` laissait ouverte).
        """
        if self._task is not None and self._task.is_running():
            self.statusBar().showMessage("A background task is running", 3000)
            return

        state = push_state(self.repository)
        if not confirmed:
            if force:
                request = ConfirmationRequest(
                    title="Push (force with lease)",
                    message=(
                        f"git push --force-with-lease {state.remote_name} "
                        f"{state.branch}\n\n"
                        f"This REPLACES the history of {state.remote_name}/"
                        f"{state.branch} with yours. It is refused if anyone "
                        "else pushed since your last fetch."
                    ),
                    destructive=True,
                )
            else:
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

        self.progress.setRange(0, 0)
        # Poussée forcée : un sous-processus git ne rapporte aucune
        # progression par objet (contrairement à pygit2). La barre reste
        # donc indéterminée jusqu'à la fin plutôt que de sembler figée à 0.
        self.progress.setFormat(
            "Pushing (force with lease)…" if force else "Pushing…"
        )
        self.progress.show()
        self.statusBar().showMessage("Pushing…")

        worker = FetchWorker(
            lambda on_progress: operations.push_branch(
                self.repository,
                on_progress=on_progress,
                force_with_lease=force,
            )
        )
        self._task = BackgroundTask(worker, self)
        self._task.progress.connect(self._on_fetch_progress)
        self._task.finished.connect(
            lambda result: self._on_push_finished(result, force)
        )
        self._task.start()

    def _on_push_finished(self, result, force: bool = False) -> None:
        """Le graphe change : la branche de suivi a avancé."""
        self.progress.hide()
        self.refresh()          # d'abord : `refresh` réécrit la barre d'état
        self.statusBar().showMessage(result.summary, 15000)

        if result.success:
            return

        if _needs_authentication(result) and self._ask_and_store_credentials():
            # Git connaît désormais les identifiants : le rappel les
            # retrouvera tout seul au prochain essai. `force` doit survivre
            # à ce second essai, sinon il repartirait en push normal et
            # échouerait à nouveau avec la même erreur non-fastforwardable.
            self._start_push(confirmed=True, force=force)
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


def _avec_noeud_de_travail(graph, state):
    """Greffe le nœud « Uncommitted changes » au-dessus de la branche
    courante, s'il y a du travail en attente.

    Demandé par l'utilisateur : une pastille faisait trop de bruit sur un
    rendu soigné. Le nœud fantôme dit littéralement de quoi il s'agit, et
    il est cliquable — l'information et l'action au même endroit.

    Rend le graphe inchangé quand l'arbre est propre, ce qui est le cas le
    plus fréquent : aucun nœud en trop, aucun coût.
    """
    from dataclasses import replace

    from tortoisepy.core.model import (
        DisplayNode, GraphEdge, NodeKind, WORKING_OID,
    )

    if graph is None or state is None or state.head_oid is None:
        return graph
    if not (state.has_unstaged_changes or state.has_staged_changes):
        return graph

    # Le nœud courant doit exister dans le graphe : sans lui, l'arête
    # pointerait dans le vide.
    if graph.node(state.head_oid) is None:
        return graph

    travail = DisplayNode(oid=WORKING_OID, kind=NodeKind.WORKING, refs=())
    arete = GraphEdge(
        ancestor=state.head_oid, descendant=WORKING_OID, skipped=()
    )
    return replace(
        graph,
        nodes=graph.nodes + (travail,),
        edges=graph.edges + (arete,),
    )
