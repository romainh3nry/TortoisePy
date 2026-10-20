"""Le bouton qui ouvre le projet courant dans un éditeur.

Demandé par l'utilisateur : « un bouton permettant d'ouvrir le projet
sur vscode à la manière de la commande `code .` ; il faudra au
préalable vérifier que l'user a bien la commande code installée. Si
oui on affiche le bouton, on clique et ça ouvre vscode sur le projet.
Si pas installé, on affiche rien. »

Puis : « possible de pouvoir ouvrir plusieurs éditeurs ? » — d'où le
menu quand il y en a plusieurs, et le bouton direct quand il n'y en a
qu'un.

La détection elle-même vit dans `core/editors.py`, sans Qt, et y est
testée (PATH, replis, droits d'exécution). Ici on éprouve le câblage.
"""

from __future__ import annotations

import os
import subprocess

import pygit2
import pytest
from PySide6.QtCore import QSettings

from tortoisepy.core.editors import Editor
from tortoisepy.ui.main_window import MainWindow
from tortoisepy.ui.settings_store import SettingsStore


def run_git(path, *args):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
    }
    return subprocess.run(
        ["git", *args], cwd=path, env=env, capture_output=True, text=True
    )


@pytest.fixture
def depot(tmp_path):
    chemin = tmp_path / "projet"
    chemin.mkdir()
    run_git(chemin, "init", "-q", "-b", "main")
    (chemin / "f.txt").write_text("x\n")
    run_git(chemin, "add", "f.txt")
    run_git(chemin, "commit", "-q", "-m", "base")
    return pygit2.Repository(str(chemin))


@pytest.fixture
def store(tmp_path):
    return SettingsStore(
        QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    )


def _fenetre(qtbot, depot, store, editeurs):
    """Une fenêtre dont la détection rend exactement `editeurs`."""
    import tortoisepy.ui.main_window as module

    reel = module.find_editors
    module.find_editors = lambda: tuple(editeurs)
    try:
        w = MainWindow(depot, settings=store)
    finally:
        module.find_editors = reel
    qtbot.addWidget(w)
    return w


_VSCODE = Editor("VS Code", "code", "/usr/local/bin/code")
_PYCHARM = Editor("PyCharm", "pycharm", "/opt/pycharm")


# --- « si pas installé, on affiche rien » -------------------------------


def test_no_button_when_no_editor_is_installed(qtbot, depot, store):
    """La demande, mot pour mot.

    Un bouton qui échouerait au clic serait pire que pas de bouton :
    il ferait chercher la cause d'un échec évitable.
    """
    fenetre = _fenetre(qtbot, depot, store, [])

    assert fenetre.editor_button is None


def test_a_button_appears_when_one_editor_is_installed(qtbot, depot,
                                                        store):
    """Un seul éditeur : un bouton direct, sans menu à dérouler.

    Ouvrir un menu pour choisir entre une seule option serait un clic
    de trop.
    """
    fenetre = _fenetre(qtbot, depot, store, [_VSCODE])

    assert fenetre.editor_button is not None
    assert fenetre.editor_button.menu() is None
    assert "VS Code" in fenetre.editor_button.text()


def test_a_menu_appears_when_several_are_installed(qtbot, depot, store):
    """« Possible de pouvoir ouvrir plusieurs éditeurs ? » — oui."""
    fenetre = _fenetre(qtbot, depot, store, [_VSCODE, _PYCHARM])

    menu = fenetre.editor_button.menu()
    assert menu is not None
    libelles = [a.text() for a in menu.actions()]
    assert "VS Code" in libelles
    assert "PyCharm" in libelles


def test_the_menu_keeps_the_detection_order(qtbot, depot, store):
    """L'ordre vient du catalogue, pas du disque.

    Deux lancements qui proposeraient les éditeurs différemment
    feraient cliquer au mauvais endroit par habitude.
    """
    fenetre = _fenetre(qtbot, depot, store, [_PYCHARM, _VSCODE])

    libelles = [a.text() for a in fenetre.editor_button.menu().actions()]
    assert libelles == ["PyCharm", "VS Code"]


# --- le clic ------------------------------------------------------------


def test_clicking_opens_the_current_repository(qtbot, depot, store,
                                               monkeypatch):
    """`code .` : le dossier de travail du dépôt ouvert.

    Pas le dossier `.git`, ni le dépôt courant de la fenêtre
    principale si l'on en a ouvert un autre à côté.
    """
    import tortoisepy.ui.main_window as module

    appels = []
    monkeypatch.setattr(
        module, "open_in_editor",
        lambda editeur, dossier: appels.append((editeur, dossier)) or True,
    )
    fenetre = _fenetre(qtbot, depot, store, [_VSCODE])

    fenetre.open_in_editor(_VSCODE)

    assert len(appels) == 1
    editeur, dossier = appels[0]
    assert editeur is _VSCODE
    assert os.path.realpath(dossier) == os.path.realpath(
        depot.workdir.rstrip("/")
    )


def test_a_single_editor_button_opens_on_click(qtbot, depot, store,
                                               monkeypatch):
    """Le bouton direct doit agir, pas seulement s'afficher.

    Le piège : un bouton sans action connectée reste cliquable et ne
    fait rien.
    """
    import tortoisepy.ui.main_window as module

    appels = []
    monkeypatch.setattr(
        module, "open_in_editor",
        lambda editeur, dossier: appels.append(editeur) or True,
    )
    fenetre = _fenetre(qtbot, depot, store, [_VSCODE])

    fenetre.editor_button.click()

    assert appels == [_VSCODE]


def test_a_menu_entry_opens_on_click(qtbot, depot, store, monkeypatch):
    """Et chaque entrée du menu doit viser SON éditeur.

    Le piège classique des fermetures dans une boucle : toutes les
    actions partageraient la dernière valeur.
    """
    import tortoisepy.ui.main_window as module

    appels = []
    monkeypatch.setattr(
        module, "open_in_editor",
        lambda editeur, dossier: appels.append(editeur.label) or True,
    )
    fenetre = _fenetre(qtbot, depot, store, [_VSCODE, _PYCHARM])

    for action in fenetre.editor_button.menu().actions():
        action.trigger()

    assert appels == ["VS Code", "PyCharm"], (
        "les entrées du menu ne visent pas chacune leur éditeur"
    )


# --- l'échec doit se voir ----------------------------------------------


def test_a_failed_launch_is_reported(qtbot, depot, store, monkeypatch):
    """Un éditeur peut exister et refuser de démarrer.

    Sans message, le clic resterait sans effet et l'utilisateur
    croirait à un bogue de l'application.
    """
    import tortoisepy.ui.main_window as module

    monkeypatch.setattr(
        module, "open_in_editor", lambda editeur, dossier: False
    )
    fenetre = _fenetre(qtbot, depot, store, [_VSCODE])

    fenetre.open_in_editor(_VSCODE)

    message = fenetre.statusBar().currentMessage()
    assert "VS Code" in message, (
        f"le message ne nomme pas l'éditeur : {message!r}"
    )


def test_a_successful_launch_says_nothing_alarming(qtbot, depot, store,
                                                   monkeypatch):
    """Le succès se voit à l'écran : l'éditeur s'ouvre.

    Un message d'erreur laissé là après une réussite ferait douter.
    """
    import tortoisepy.ui.main_window as module

    monkeypatch.setattr(
        module, "open_in_editor", lambda editeur, dossier: True
    )
    fenetre = _fenetre(qtbot, depot, store, [_VSCODE])

    fenetre.open_in_editor(_VSCODE)

    assert "not" not in fenetre.statusBar().currentMessage().lower()


# --- le reste ne doit pas se dégrader ----------------------------------


def test_the_other_toolbar_buttons_survive(qtbot, depot, store):
    """Le bouton s'ajoute, il ne remplace rien."""
    fenetre = _fenetre(qtbot, depot, store, [_VSCODE])

    assert fenetre.workdir_button is not None
    assert fenetre.recent_button is not None


def test_nothing_is_written_to_the_repository(qtbot, depot, store,
                                              monkeypatch):
    """§7.0 : ouvrir un éditeur ne touche pas au dépôt.

    L'éditeur, lui, écrira peut-être — mais c'est l'utilisateur qui
    l'aura décidé, dans une autre application.
    """
    import pathlib

    import tortoisepy.ui.main_window as module

    monkeypatch.setattr(
        module, "open_in_editor", lambda editeur, dossier: True
    )
    fenetre = _fenetre(qtbot, depot, store, [_VSCODE])
    racine = pathlib.Path(depot.workdir)
    avant = {c: c.stat().st_mtime for c in racine.rglob("*")}

    fenetre.open_in_editor(_VSCODE)

    apres = {c: c.stat().st_mtime for c in racine.rglob("*")}
    assert avant == apres
