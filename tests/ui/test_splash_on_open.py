"""L'écran d'attente, aussi quand on ouvre un projet depuis l'UI.

Signalé par l'utilisateur : « quand on clique sur Open Project et
qu'on clique sur un projet, l'app freeze quelques secondes le temps
d'ouvrir le projet, pourquoi le splash n'apparaît pas ? »

Parce que tout le mécanisme — `StartupSplash`, `defer_graph`,
`on_progress`, le signal `graph_ready` — vivait dans `cli.py` et
n'était utilisé qu'au lancement en ligne de commande. Les deux
entrées de l'interface, « Open Project » et « Open Recent »,
construisaient une `MainWindow` nue : le graphe se bâtissait sur le
fil principal, et rien ne s'affichait pendant ce temps.

Mesuré ailleurs dans le projet : `build_graph` coûte 1522 ms sur un
dépôt de 935 nœuds. C'est exactement le gel décrit.
"""

from __future__ import annotations

import os
import subprocess

import pygit2
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from tortoisepy.ui.main_window import MainWindow
from tortoisepy.ui.settings_store import SettingsStore
from tortoisepy.ui.splash import StartupSplash, should_show_splash


def run_git(path, *args):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
    }
    return subprocess.run(
        ["git", *args], cwd=path, env=env, capture_output=True, text=True
    )


def _depot(chemin, branches=0):
    """Un dépôt réel. `branches` gonfle le nombre de refs.

    C'est ce nombre que `should_show_splash` compte pour décider si
    l'ouverture mérite un écran d'attente.
    """
    chemin.mkdir(parents=True, exist_ok=True)
    run_git(chemin, "init", "-q", "-b", "main")
    (chemin / "f.txt").write_text("x\n")
    run_git(chemin, "add", "f.txt")
    run_git(chemin, "commit", "-q", "-m", "base")
    for i in range(branches):
        run_git(chemin, "branch", f"b{i}")
    return chemin


def _ecrans_visibles():
    """Les écrans d'attente réellement affichés.

    `topLevelWidgets()` garde les fenêtres des tests précédents tant
    que Qt ne les a pas détruites : compter sans filtrer faisait
    échouer un test à cause de ses voisins (constaté).
    """
    return [
        w for w in QApplication.topLevelWidgets()
        if isinstance(w, StartupSplash) and w.isVisible()
    ]


@pytest.fixture(autouse=True)
def _sans_ecran_residuel():
    """Ferme les écrans laissés par un test précédent."""
    yield
    for ecran in _ecrans_visibles():
        ecran.close()


@pytest.fixture
def store(tmp_path):
    return SettingsStore(
        QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    )


@pytest.fixture
def fenetre(qtbot, tmp_path, store):
    courant = _depot(tmp_path / "courant")
    w = MainWindow(pygit2.Repository(str(courant)), settings=store)
    qtbot.addWidget(w)
    return w


# --- le cas signalé -----------------------------------------------------


def test_opening_a_large_project_shows_a_splash(qtbot, fenetre, tmp_path):
    """La demande : un écran d'attente au lieu d'un gel.

    Le seuil est celui de `should_show_splash`, qui compte les refs
    plutôt que de mesurer — construire le graphe pour savoir s'il
    faut annoncer sa construction serait absurde.
    """

    gros = _depot(tmp_path / "gros", branches=80)
    assert should_show_splash(pygit2.Repository(str(gros))), (
        "le dépôt d'essai est trop petit pour mériter un écran"
    )

    fenetre.open_project(str(gros))


    ecrans = _ecrans_visibles()
    assert ecrans, "aucun écran d'attente n'est apparu"


def test_a_small_project_opens_without_a_splash(qtbot, fenetre, tmp_path):
    """Sur un petit dépôt, l'écran clignoterait pour rien.

    Le mode synchrone évite aussi un aller-retour entre fils pour
    17 ms — la raison pour laquelle `cli.py` conditionne déjà les
    deux au même test.
    """

    petit = _depot(tmp_path / "petit")
    assert not should_show_splash(pygit2.Repository(str(petit)))

    fenetre.open_project(str(petit))

    ecrans = _ecrans_visibles()
    assert not ecrans, "un écran est apparu pour un dépôt minuscule"


def test_the_graph_is_deferred_when_a_splash_shows(qtbot, fenetre,
                                                   tmp_path):
    """Le test qui compte : l'écran ne sert à rien sans le report.

    Un écran affiché pendant que `build_graph` bloque le fil
    principal ne se peindrait jamais — c'est précisément le gel
    signalé, avec une fenêtre de plus.
    """
    gros = _depot(tmp_path / "gros", branches=80)

    fenetre.open_project(str(gros))
    ouverte = fenetre._recent_windows.last()

    assert ouverte._defer_graph, (
        "le graphe se construit sur le fil principal : l'écran "
        "d'attente ne pourra pas se peindre"
    )


def test_the_splash_closes_when_the_graph_arrives(qtbot, fenetre,
                                                  tmp_path):
    """Un écran qui ne se retire pas est pire que pas d'écran.

    Il doit suivre `graph_ready`, et non un délai : le graphe peut
    prendre une seconde ou dix selon le dépôt.
    """
    gros = _depot(tmp_path / "gros", branches=80)
    fenetre.open_project(str(gros))

    qtbot.waitUntil(lambda: not _ecrans_visibles(), timeout=10000)


# --- « Open Recent » doit se comporter pareil ---------------------------


def test_open_recent_also_shows_a_splash(qtbot, fenetre, tmp_path):
    """Deux boutons voisins ne doivent pas différer.

    `open_recent_repository` souffre du même gel, pour la même
    raison : il construisait lui aussi une `MainWindow` nue.
    """
    gros = _depot(tmp_path / "recent", branches=80)
    fenetre.open_recent_repository(str(gros))

    ecrans = _ecrans_visibles()
    assert ecrans, "« Open Recent » n'affiche pas d'écran d'attente"


# --- robustesse ---------------------------------------------------------


def test_a_failed_open_leaves_no_orphan_splash(qtbot, fenetre, tmp_path):
    """Un écran orphelin resterait à l'écran pour toujours.

    `cli.py` traite déjà ce cas par un `try/except` ; l'oublier ici
    laisserait une fenêtre que rien ne ferme.
    """
    sans_git = tmp_path / "pas-un-depot"
    sans_git.mkdir()

    fenetre.open_project(str(sans_git))

    ecrans = _ecrans_visibles()
    assert not ecrans, "un écran est resté orphelin"


def test_the_opened_window_still_works(qtbot, fenetre, tmp_path):
    """L'écran ne doit rien changer au résultat.

    Le piège : un report de graphe mal branché ouvrirait une fenêtre
    qui reste vide.
    """
    gros = _depot(tmp_path / "gros", branches=80)
    fenetre.open_project(str(gros))
    ouverte = fenetre._recent_windows.last()

    qtbot.waitUntil(lambda: ouverte.graph is not None, timeout=10000)
    assert ouverte.graph.nodes, "le graphe est vide"


def test_the_splash_closes_even_if_the_build_cannot_start(qtbot, fenetre,
                                                          tmp_path):
    """Signalé par l'utilisateur : « le splash reste bloqué à l'écran ».

    `run_in_background` rend `False` quand le verrou d'opération est
    déjà pris — une autre tâche tourne. Dans ce cas le graphe n'était
    jamais construit, `graph_ready` jamais émis, et l'écran restait
    affiché indéfiniment, par-dessus une fenêtre vide.

    Le résultat de `run_in_background` n'était tout simplement pas lu
    sur ce chemin, alors qu'il l'est partout ailleurs.
    """
    gros = _depot(tmp_path / "gros", branches=80)

    # Le verrou pris : exactement l'état qui faisait échouer le
    # démarrage de la construction.
    reel = MainWindow.run_in_background
    MainWindow.run_in_background = lambda self, *a, **k: False
    try:
        fenetre.open_project(str(gros))
        ouverte = fenetre._recent_windows.last()

        qtbot.waitUntil(lambda: ouverte.graph is not None, timeout=10000)
        qtbot.waitUntil(lambda: not _ecrans_visibles(), timeout=10000)
    finally:
        MainWindow.run_in_background = reel


def test_both_entry_points_share_one_implementation(fenetre):
    """Le seul moyen de garantir qu'elles ne divergeront pas.

    Demandé par l'utilisateur : « il faudra le même comportement pour
    Open Recent ». Deux copies du même code se seraient séparées à la
    première correction — celle de l'écran bloqué, par exemple,
    n'aurait touché qu'une des deux.
    """
    import inspect

    for nom in ("open_project", "open_recent_repository"):
        source = inspect.getsource(getattr(type(fenetre), nom))
        assert "_ouvrir_dans_une_fenetre" in source, (
            f"`{nom}` ne passe pas par la méthode commune"
        )
        assert "MainWindow(" not in source, (
            f"`{nom}` construit sa propre fenêtre : les deux chemins "
            "divergeront"
        )


def test_open_recent_also_closes_a_stuck_splash(qtbot, fenetre, tmp_path):
    """Le correctif de l'écran bloqué vaut pour les deux entrées.

    C'est la conséquence concrète du partage : corrigé une fois,
    corrigé partout.
    """
    gros = _depot(tmp_path / "recent2", branches=80)

    reel = MainWindow.run_in_background
    MainWindow.run_in_background = lambda self, *a, **k: False
    try:
        fenetre.open_recent_repository(str(gros))
        ouverte = fenetre._recent_windows.last()

        qtbot.waitUntil(lambda: ouverte.graph is not None, timeout=10000)
        qtbot.waitUntil(lambda: not _ecrans_visibles(), timeout=10000)
    finally:
        MainWindow.run_in_background = reel
