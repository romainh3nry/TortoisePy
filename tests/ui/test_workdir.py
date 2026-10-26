"""Le dossier de projets et son menu déroulant.

Demandé par l'utilisateur : un bouton pour choisir un répertoire de
projets ; le réglage reste d'un lancement à l'autre ; le menu liste les
projets qu'il contient ; un clic ouvre le graphe ; un message d'erreur
si le projet n'est pas un dépôt Git.

Ce que ces tests ne couvrent PAS, et pourquoi : la détection elle-même
vit dans `core/projects.py`, sans Qt, et y est testée (profondeur,
dossiers cachés, worktrees, permissions). Ici on éprouve le câblage —
le réglage, le menu, l'ouverture, les messages.
"""

from __future__ import annotations

import os
import subprocess

import pygit2
import pytest
from PySide6.QtCore import QSettings

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


def _vrai_depot(chemin):
    """Un dépôt réellement ouvrable, pas seulement un `.git` vide."""
    chemin.mkdir(parents=True, exist_ok=True)
    run_git(chemin, "init", "-q", "-b", "main")
    (chemin / "f.txt").write_text("x\n")
    run_git(chemin, "add", "f.txt")
    run_git(chemin, "commit", "-q", "-m", "base")
    return chemin


@pytest.fixture
def store(tmp_path):
    """Un `.ini` jetable : jamais les vraies préférences.

    Sans cette injection, les tests écriraient le workdir dans
    `~/Library/Preferences` et le modifieraient pour de bon.
    """
    return SettingsStore(
        QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    )


@pytest.fixture
def depot(tmp_path):
    return pygit2.Repository(str(_vrai_depot(tmp_path / "courant")))


@pytest.fixture
def espace(tmp_path):
    """Un dossier de projets : deux dépôts et un dossier ordinaire."""
    racine = tmp_path / "Projets"
    _vrai_depot(racine / "alpha")
    _vrai_depot(racine / "beta")
    (racine / "documents").mkdir()
    return racine


@pytest.fixture
def window(qtbot, depot, store):
    w = MainWindow(depot, settings=store)
    qtbot.addWidget(w)
    return w


def _entrees(fenetre) -> list[str]:
    """Les libellés du menu, une fois peuplé."""
    menu = fenetre.workdir_button.menu()
    menu.aboutToShow.emit()
    return [action.text() for action in menu.actions()]


# --- choisir le dossier -------------------------------------------------


def test_the_button_exists(window):
    """La demande : « un bouton qui permet de sélectionner un workdir »."""
    assert window.workdir_button is not None
    assert window.workdir_button.menu() is not None


def test_choosing_a_folder_remembers_it(window, espace):
    """« Une fois sélectionné, le réglage doit rester. »"""
    window.set_workdir(str(espace))

    assert window.settings.value("view/workdir") == str(espace)


def test_the_folder_is_restored_on_the_next_launch(qtbot, depot, store,
                                                   espace):
    """Le test qui compte : mémoriser sans relire ne sert à rien.

    C'est l'oubli invisible — `set_workdir` a l'air juste, et le
    réglage se perd quand même au lancement suivant.
    """
    premiere = MainWindow(depot, settings=store)
    qtbot.addWidget(premiere)
    premiere.set_workdir(str(espace))

    seconde = MainWindow(depot, settings=store)
    qtbot.addWidget(seconde)

    assert seconde.current_workdir() == str(espace)
    assert "alpha" in " ".join(_entrees(seconde))


def test_choosing_another_folder_replaces_it(window, espace, tmp_path):
    """« …à part s'il est re-modifié ensuite. »"""
    autre = tmp_path / "Autre"
    _vrai_depot(autre / "gamma")

    window.set_workdir(str(espace))
    window.set_workdir(str(autre))

    assert window.current_workdir() == str(autre)
    entrees = " ".join(_entrees(window))
    assert "gamma" in entrees
    assert "alpha" not in entrees, "l'ancien dossier est encore listé"


# --- le menu ------------------------------------------------------------


def test_the_menu_lists_the_projects(window, espace):
    """« Il doit pouvoir détecter et lister tous les projets. »"""
    window.set_workdir(str(espace))

    entrees = _entrees(window)

    assert any("alpha" in e for e in entrees)
    assert any("beta" in e for e in entrees)


def test_a_folder_without_git_is_not_listed(window, espace):
    """Choix de l'utilisateur : masquer ce qui ne s'ouvre pas."""
    window.set_workdir(str(espace))

    assert not any("documents" in e for e in _entrees(window))


def test_the_menu_always_offers_to_manage_folders(window, espace):
    """Changer de dossier doit rester accessible depuis le menu.

    Sans cela, le réglage serait posé une fois pour toutes et
    l'utilisateur n'aurait aucun moyen d'en changer depuis l'UI.

    Depuis les dossiers multiples, « Add folder… » vit dans le
    sous-menu « Folders » — qui existe même quand aucun dossier n'est
    configuré, justement pour que l'ajout reste trouvable.
    """
    from PySide6.QtWidgets import QMenu

    def ajout_accessible():
        menu = window.workdir_button.menu()
        menu.aboutToShow.emit()
        for action in menu.actions():
            sous_menu = action.menu()
            if sous_menu is None:
                continue
            sous_menu.aboutToShow.emit()
            if any("Add folder" in a.text() for a in sous_menu.actions()):
                return True
        return False

    assert ajout_accessible(), "aucun dossier configuré : ajout introuvable"

    window.add_workdir(str(espace))

    assert ajout_accessible(), "avec un dossier : ajout introuvable"


def test_an_empty_workdir_says_so(window, tmp_path):
    """Un dossier sans aucun dépôt ne doit pas laisser un menu muet."""
    vide = tmp_path / "Vide"
    vide.mkdir()
    window.set_workdir(str(vide))

    entrees = " ".join(_entrees(window))
    assert "No Git project" in entrees, entrees


def test_a_missing_workdir_says_so(window, tmp_path):
    """Un disque externe débranché : le menu doit l'expliquer.

    Rester vide sans raison ferait croire à un dossier sans projets,
    et l'utilisateur chercherait au mauvais endroit.
    """
    window.set_workdir(str(tmp_path / "jamais-cree"))

    entrees = " ".join(_entrees(window))
    assert "not found" in entrees.lower(), entrees


def test_the_menu_is_rebuilt_each_time(window, espace):
    """Un projet cloné entre deux ouvertures doit apparaître.

    Un menu construit une fois montrerait indéfiniment l'état du
    premier affichage.
    """
    window.set_workdir(str(espace))
    assert not any("gamma" in e for e in _entrees(window))

    _vrai_depot(espace / "gamma")

    assert any("gamma" in e for e in _entrees(window))


def test_the_menu_does_not_grow_on_each_opening(window, espace):
    """Le menu est VIDÉ avant d'être repeuplé.

    Trouvé par mutation : sans `menu.clear()`, les tests passaient
    tous — l'ajout d'un projet était bien visible, mais les anciennes
    entrées restaient et le menu doublait de taille à chaque
    affichage. Un défaut qu'on ne voit qu'en ouvrant deux fois.
    """
    window.set_workdir(str(espace))

    premier = _entrees(window)
    second = _entrees(window)

    assert premier == second, (
        f"{len(premier)} entrées puis {len(second)} : le menu s'empile"
    )


def test_a_removed_project_disappears(window, espace):
    """L'inverse du clonage : un projet supprimé quitte le menu."""
    import shutil

    window.set_workdir(str(espace))
    assert any("beta" in e for e in _entrees(window))

    shutil.rmtree(espace / "beta")

    assert not any("beta" in e for e in _entrees(window))


# --- ouvrir un projet ---------------------------------------------------


def test_clicking_a_project_opens_it(window, espace):
    """« Au clic dessus, ça ouvre le graphe. »"""
    window.set_workdir(str(espace))
    avant = len(window._recent_windows)

    window.open_project(str(espace / "alpha"))

    assert len(window._recent_windows) == avant + 1
    ouverte = window._recent_windows.last()
    assert "alpha" in ouverte.windowTitle()


def test_the_opened_project_has_its_graph(window, espace):
    """Ouvrir doit montrer le graphe, pas une fenêtre vide."""
    window.set_workdir(str(espace))
    window.open_project(str(espace / "alpha"))

    ouverte = window._recent_windows.last()
    assert ouverte.graph is not None
    assert ouverte.graph.nodes, "le graphe est vide"


def test_the_current_window_is_left_alone(window, espace):
    """Comme « Open Recent » : on ouvre à côté, on ne remplace pas.

    Deux boutons voisins qui se comporteraient différemment
    surprendraient.
    """
    titre = window.windowTitle()
    window.set_workdir(str(espace))
    window.open_project(str(espace / "alpha"))

    assert window.windowTitle() == titre


# --- le message d'erreur demandé ---------------------------------------


def test_opening_a_folder_without_git_reports_an_error(window, tmp_path):
    """« Si pas de .git dans un projet de la liste, message d'erreur. »

    Le menu ne liste que des dépôts : ce cas survient quand le projet
    a été supprimé ou déplacé ENTRE le scan et le clic. Sans message,
    le clic ne ferait rien et l'utilisateur croirait à un bug.
    """
    sans_git = tmp_path / "pas-un-depot"
    sans_git.mkdir()
    avant = len(window._recent_windows)

    window.open_project(str(sans_git))

    assert len(window._recent_windows) == avant, "une fenêtre s'est ouverte"
    assert "Git" in window.statusBar().currentMessage(), (
        f"message peu clair : {window.statusBar().currentMessage()!r}"
    )


def test_opening_a_vanished_project_reports_an_error(window, espace):
    """Le projet existait au scan, plus au clic."""
    window.set_workdir(str(espace))
    disparu = str(espace / "jamais-la")

    window.open_project(disparu)

    assert window.statusBar().currentMessage(), "aucun message affiché"


def test_the_error_names_the_project(window, tmp_path):
    """Un message qui ne nomme pas ce qui échoue n'aide pas (§9).

    Avec plusieurs projets au même nom court, « impossible d'ouvrir »
    ne dirait pas lequel.
    """
    sans_git = tmp_path / "projet-casse"
    sans_git.mkdir()

    window.open_project(str(sans_git))

    assert "projet-casse" in window.statusBar().currentMessage()


# --- le reste ne doit pas se dégrader -----------------------------------


def test_open_recent_still_works(window, espace):
    """Le bouton voisin ne doit pas être touché."""
    assert window.recent_button is not None
    assert window.recent_button.menu() is not None


def test_the_scan_does_not_touch_the_repositories(window, espace):
    """§7.0 : l'application n'écrit dans un dépôt que sur action.

    Ouvrir le menu est une lecture ; le scan ne doit pas instancier de
    dépôt, ce qui pourrait poser un fichier de verrou.
    """
    window.set_workdir(str(espace))
    avant = {
        c: c.stat().st_mtime for c in (espace / "alpha").rglob("*")
    }

    _entrees(window)

    apres = {
        c: c.stat().st_mtime for c in (espace / "alpha").rglob("*")
    }
    assert avant == apres, "le scan a modifié un dépôt"
