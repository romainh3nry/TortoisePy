"""La fenêtre s'ouvre avant que le graphe soit construit.

Demandé par l'utilisateur : « si ça peut permettre que l'app s'ouvre plus
rapidement ». Mesuré sur son dépôt :

    build_graph : 1522.6 ms  (935 nœuds)

`MainWindow` se construisait d'un bloc, graphe compris : rien ne
s'affichait pendant une seconde et demie, et l'écran d'attente lui-même
restait figé faute de boucle d'événements.

Le démarrage est la DERNIÈRE opération longue à ne pas passer en
arrière-plan — refresh, blâme, commit et journal le font déjà. Le
commentaire du code l'expliquait : `restore_settings` et
`_center_on_head` ont besoin du graphe. Vérifié, c'est inexact :
`_center_on_head` sort proprement sans état, et `restore_settings` ne
touche que le zoom et le splitter. Il suffit de rappeler le centrage
quand le graphe arrive.
"""

from __future__ import annotations

import subprocess
import threading

import pygit2
import pytest

from tortoisepy.ui.main_window import MainWindow

ENV = {
    "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
    "PATH": "/usr/bin:/bin:/usr/local/bin",
}


def _git(chemin, *args, check=True):
    return subprocess.run(
        ["git", "-C", str(chemin), *args], check=check,
        capture_output=True, env=ENV, text=True,
    )


@pytest.fixture
def depot(tmp_path):
    w = tmp_path / "w"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "a.txt").write_text("a\n")
    _git(w, "add", ".")
    _git(w, "commit", "-qm", "base")
    _git(w, "checkout", "-qb", "autre")
    (w / "b.txt").write_text("b\n")
    _git(w, "add", ".")
    _git(w, "commit", "-qm", "second")
    _git(w, "checkout", "-q", "main")
    return pygit2.Repository(str(w))


def _attendre_le_graphe(qtbot, fenetre, timeout: int = 5000) -> None:
    qtbot.waitUntil(lambda: fenetre.graph is not None, timeout=timeout)


# --- l'ouverture n'attend plus le graphe --------------------------------


def test_the_window_opens_before_the_graph(qtbot, depot):
    """L'assertion centrale : la construction rend la main tout de suite.

    C'est ce qui permet à l'écran d'attente de s'animer, et à la fenêtre
    de paraître avant la fin du calcul.
    """
    fenetre = MainWindow(depot, defer_graph=True)
    qtbot.addWidget(fenetre)

    assert fenetre.graph is None, (
        "le graphe ne doit pas être construit dans le constructeur"
    )
    _attendre_le_graphe(qtbot, fenetre)


def test_the_graph_arrives_afterwards(qtbot, depot):
    """Différer n'est pas renoncer : le graphe doit bien arriver."""
    fenetre = MainWindow(depot, defer_graph=True)
    qtbot.addWidget(fenetre)

    _attendre_le_graphe(qtbot, fenetre)
    assert len(fenetre.graph.nodes) >= 2


def test_the_graph_is_built_off_the_main_thread(qtbot, depot):
    """Sinon la boucle Qt reste bloquée et l'écran d'attente fige.

    On observe le FIL, pas le résultat : construire sur le fil principal
    donnerait le même graphe tout en laissant l'interface gelée — le
    défaut exact qu'on corrige.
    """
    from tortoisepy.ui import main_window as module

    principal = threading.get_ident()
    fils = []
    vrai = module.build_graph

    def observe(*a, **k):
        fils.append(threading.get_ident())
        return vrai(*a, **k)

    module.build_graph = observe
    try:
        fenetre = MainWindow(depot, defer_graph=True)
        qtbot.addWidget(fenetre)
        qtbot.waitUntil(lambda: bool(fils), timeout=5000)
        assert fils[0] != principal, "le graphe gèle le démarrage"
        _attendre_le_graphe(qtbot, fenetre)
    finally:
        module.build_graph = vrai


# --- ce que le démarrage doit toujours faire ----------------------------


def test_the_view_centres_once_the_graph_arrives(qtbot, depot):
    """Le centrage sur HEAD était fait dans le constructeur.

    Il doit maintenant suivre l'arrivée du graphe : sans cela, la vue
    s'ouvrirait en haut d'un graphe de plusieurs milliers de pixels, et
    l'utilisateur devrait chercher où il se trouve.
    """
    fenetre = MainWindow(depot, defer_graph=True)
    qtbot.addWidget(fenetre)
    _attendre_le_graphe(qtbot, fenetre)

    assert fenetre.view.selected_oids() == (fenetre.state.head_oid,), (
        "le nœud courant doit être sélectionné une fois le graphe posé"
    )


def test_the_status_bar_is_filled(qtbot, depot):
    """La barre d'état nomme la branche : elle dépend de l'état lu."""
    fenetre = MainWindow(depot, defer_graph=True)
    qtbot.addWidget(fenetre)
    _attendre_le_graphe(qtbot, fenetre)

    assert "main" in fenetre.statusBar().currentMessage()


def test_the_settings_are_restored(qtbot, depot, tmp_path):
    """`restore_settings` ne dépend pas du graphe — il doit rester appelé."""
    from PySide6.QtCore import QSettings

    from tortoisepy.ui.settings_store import SettingsStore

    store = SettingsStore(
        QSettings(str(tmp_path / "p.ini"), QSettings.Format.IniFormat)
    )
    store.set_value("view/zoom", "1.5")

    fenetre = MainWindow(depot, settings=store, defer_graph=True)
    qtbot.addWidget(fenetre)
    _attendre_le_graphe(qtbot, fenetre)

    assert abs(fenetre.view.current_zoom() - 1.5) < 0.01


# --- le mode synchrone reste disponible ---------------------------------


def test_the_synchronous_mode_is_still_the_default(qtbot, depot):
    """Les tests existants comptent sur un graphe prêt à la construction.

    Changer ce défaut aurait obligé à réécrire des centaines de tests
    sans qu'aucun comportement utilisateur ne l'exige : le mode différé
    est demandé explicitement, par le démarrage réel.
    """
    fenetre = MainWindow(depot)
    qtbot.addWidget(fenetre)

    assert fenetre.graph is not None


def test_closing_before_the_graph_arrives_does_not_crash(qtbot, depot):
    """Fermer pendant la construction détruirait le QThread en cours.

    « QThread: Destroyed while thread is still running » — le défaut
    déjà corrigé sur les quatre autres fenêtres.
    """
    fenetre = MainWindow(depot, defer_graph=True)
    qtbot.addWidget(fenetre)

    fenetre.close()      # ne doit pas lever


def test_the_window_announces_the_graph_is_ready(qtbot, depot):
    """L'écran d'attente doit savoir quand se retirer.

    Le fermer dès que la fenêtre paraît laisserait une fenêtre vide le
    temps du calcul — pire que l'écran lui-même.
    """
    fenetre = MainWindow(depot, defer_graph=True)
    qtbot.addWidget(fenetre)

    with qtbot.waitSignal(fenetre.graph_ready, timeout=5000):
        pass


def test_the_signal_fires_once_the_graph_exists(qtbot, depot):
    """Le signal ne doit pas précéder ce qu'il annonce."""
    fenetre = MainWindow(depot, defer_graph=True)
    qtbot.addWidget(fenetre)

    vus = []
    fenetre.graph_ready.connect(lambda: vus.append(fenetre.graph))
    qtbot.waitUntil(lambda: bool(vus), timeout=5000)

    assert vus[0] is not None, "le signal a précédé le graphe"


# --- deux régressions du démarrage différé ------------------------------


def test_the_graph_keeps_the_larger_share(qtbot, depot):
    """Signalé : « la liste des commits à droite prend tout l'écran ».

    `show()` a lieu sur une vue VIDE en mode différé : sans contenu à
    mesurer, Qt répartit le splitter à l'envers. Mesuré — [90, 1306] au
    lieu de [976, 420].

    Le graphe est la raison d'être de la fenêtre : il doit garder la
    plus grande part, comme en mode synchrone.
    """
    fenetre = MainWindow(depot, defer_graph=True)
    qtbot.addWidget(fenetre)
    # Assez large pour que la largeur MINIMALE du panneau (420 px) ne
    # dicte plus la répartition : en dessous, Qt la respecte avant toute
    # proportion, et le test mesurerait cette contrainte plutôt que le
    # défaut signalé.
    fenetre.resize(1600, 900)
    fenetre.show()
    _attendre_le_graphe(qtbot, fenetre)
    qtbot.wait(50)

    graphe, panneau = fenetre.splitter.sizes()
    assert graphe > panneau, (
        f"le panneau ({panneau} px) déborde le graphe ({graphe} px)"
    )


def test_the_split_matches_the_synchronous_mode(qtbot, depot):
    """Différer le graphe ne doit rien changer à la mise en page.

    Le piège : corriger le symptôme avec une valeur arbitraire, et
    obtenir deux dispositions différentes selon le mode.
    """
    synchrone = MainWindow(depot)
    qtbot.addWidget(synchrone)
    synchrone.show()
    qtbot.wait(50)
    attendu = synchrone.splitter.sizes()

    differe = MainWindow(depot, defer_graph=True)
    qtbot.addWidget(differe)
    differe.show()
    _attendre_le_graphe(qtbot, differe)
    qtbot.wait(50)

    assert differe.splitter.sizes() == attendu


def test_no_second_progress_bar_during_startup(qtbot, depot):
    """Signalé : « il y a une double barre de chargement ».

    L'écran d'attente porte déjà la sienne ; celle de la barre d'état
    s'y ajoutait, puisque le premier chargement passe par
    `run_in_background`. Deux indicateurs pour une seule attente
    laissent croire à deux travaux distincts.
    """
    vues = []
    fenetre = MainWindow(depot, defer_graph=True)
    qtbot.addWidget(fenetre)
    fenetre.show()

    for _ in range(40):
        vues.append(fenetre.progress.isVisible())
        qtbot.wait(5)
        if fenetre.graph is not None:
            break

    assert not any(vues), (
        "la barre de la fenêtre s'affiche alors que l'écran d'attente "
        "en montre déjà une"
    )


def test_the_progress_bar_works_again_afterwards(qtbot, depot):
    """Masquer la barre au démarrage ne doit pas la désactiver pour de bon.

    Le piège : supprimer l'indicateur au lieu de le taire une fois.
    """
    fenetre = MainWindow(depot, defer_graph=True)
    qtbot.addWidget(fenetre)
    fenetre.show()
    _attendre_le_graphe(qtbot, fenetre)

    lance = fenetre.run_in_background(
        lambda: "fini", lambda _r: None, "Essai…"
    )

    assert lance
    assert fenetre.progress.isVisible(), (
        "la barre doit resservir après le démarrage"
    )


# --- largeur par défaut à la première ouverture -------------------------


def test_the_window_fills_the_screen_width_by_default(qtbot, depot):
    """Demandé par l'utilisateur : toute la largeur à l'ouverture.

    1400 px en dur laissait des bandes vides sur un écran large, et le
    graphe est justement ce qui profite de la place.
    """
    from PySide6.QtGui import QGuiApplication

    fenetre = MainWindow(depot)
    qtbot.addWidget(fenetre)

    disponible = QGuiApplication.primaryScreen().availableGeometry()
    assert fenetre.width() >= disponible.width() - 2, (
        f"{fenetre.width()} px pour un écran de {disponible.width()} px"
    )


def test_the_default_height_leaves_the_dock_alone(qtbot, depot):
    """`availableGeometry` et non `geometry` : la barre de menus et le
    Dock de macOS ne sont pas de l'espace utilisable.

    Le piège : prendre l'écran entier et passer sous le Dock.
    """
    from PySide6.QtGui import QGuiApplication

    fenetre = MainWindow(depot)
    qtbot.addWidget(fenetre)

    disponible = QGuiApplication.primaryScreen().availableGeometry()
    assert fenetre.height() <= disponible.height()


def test_a_remembered_geometry_wins(qtbot, depot, tmp_path):
    """Un réglage de l'utilisateur prime sur le défaut.

    C'est tout l'intérêt de mémoriser la géométrie : l'écraser à chaque
    ouverture rendrait le réglage inutile.
    """
    from PySide6.QtCore import QSettings

    from tortoisepy.ui.settings_store import SettingsStore

    chemin = str(tmp_path / "p.ini")
    store = SettingsStore(QSettings(chemin, QSettings.Format.IniFormat))

    # Une taille qui TIENT dans l'écran : `geometry_is_visible` refuse
    # une géométrie hors écran, et la refuser serait ici le bon
    # comportement — pas celui qu'on teste.
    from PySide6.QtGui import QGuiApplication

    disponible = QGuiApplication.primaryScreen().availableGeometry()
    voulue = max(400, disponible.width() // 2)

    premiere = MainWindow(depot, settings=store)
    qtbot.addWidget(premiere)
    premiere.resize(voulue, 400)
    premiere.save_settings()

    seconde = MainWindow(
        depot,
        settings=SettingsStore(
            QSettings(chemin, QSettings.Format.IniFormat)
        ),
    )
    qtbot.addWidget(seconde)

    assert seconde.width() == voulue, (
        f"la géométrie mémorisée a été écrasée ({seconde.width()} px)"
    )
