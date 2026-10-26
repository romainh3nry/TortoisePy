"""Gérer plusieurs dossiers de projets depuis l'interface.

Demandé par l'utilisateur : « possible de pouvoir ajouter plusieurs
répertoires de projet ? »

Deux garanties portent tout le reste :

  - **le réglage existant n'est pas perdu** à la mise à jour. Un seul
    dossier était mémorisé dans `view/workdir` ; il devient le premier
    de la liste ;
  - **rien ne change pour qui n'a qu'un dossier.** Le menu, les noms
    de projets et `topy -s` se comportent exactement comme avant.
"""

from __future__ import annotations

import os
import subprocess

import pygit2
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QMenu

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


def _depot(chemin):
    chemin.mkdir(parents=True, exist_ok=True)
    run_git(chemin, "init", "-q", "-b", "main")
    (chemin / "f.txt").write_text("x\n")
    run_git(chemin, "add", "f.txt")
    run_git(chemin, "commit", "-q", "-m", "base")
    return chemin


@pytest.fixture
def reglages(tmp_path):
    """Des réglages neufs, isolés de la machine."""
    return SettingsStore(
        QSettings(str(tmp_path / "r.ini"), QSettings.Format.IniFormat)
    )


@pytest.fixture
def fenetre(qtbot, tmp_path, reglages):
    depot = _depot(tmp_path / "courant")
    f = MainWindow(pygit2.Repository(str(depot)), settings=reglages)
    qtbot.addWidget(f)
    return f


# --- la migration, ce qui protège le réglage existant -------------------


def test_the_old_single_folder_is_kept(fenetre, reglages, tmp_path):
    """Un dossier réglé par une version précédente reste accessible.

    C'est la garantie la plus importante : sans elle, mettre à jour
    efface silencieusement un réglage que l'utilisateur a posé une
    fois et oublié.
    """
    ancien = str(_depot(tmp_path / "ancien").parent)
    reglages.set_value("view/workdir", ancien)

    assert fenetre.current_workdirs() == (ancien,)


def test_the_old_setting_is_not_added_twice(fenetre, reglages, tmp_path):
    """La migration ne doit pas doubler un dossier déjà dans la liste."""
    dossier = str(tmp_path / "commun")
    reglages.set_value("view/workdir", dossier)
    reglages.set_value("view/workdirs", (dossier,))

    assert fenetre.current_workdirs() == (dossier,)


def test_no_folder_at_all_gives_an_empty_list(fenetre):
    """Première installation : aucun dossier, pas d'erreur."""
    assert fenetre.current_workdirs() == ()


# --- ajouter et retirer -------------------------------------------------


def test_a_folder_can_be_added(fenetre, tmp_path):
    """Le besoin demandé."""
    un = str(tmp_path / "un")
    deux = str(tmp_path / "deux")

    fenetre.add_workdir(un)
    fenetre.add_workdir(deux)

    assert fenetre.current_workdirs() == (un, deux)


def test_adding_the_same_folder_twice_changes_nothing(fenetre, tmp_path):
    """Ajouter deux fois le même dossier ne le double pas.

    Sans cela, chaque projet apparaîtrait en double dans le menu.
    """
    dossier = str(tmp_path / "un")

    fenetre.add_workdir(dossier)
    fenetre.add_workdir(dossier)

    assert fenetre.current_workdirs() == (dossier,)


def test_a_folder_can_be_removed(fenetre, tmp_path):
    """Retirer un dossier sans toucher aux autres."""
    un, deux = str(tmp_path / "un"), str(tmp_path / "deux")
    fenetre.add_workdir(un)
    fenetre.add_workdir(deux)

    fenetre.remove_workdir(un)

    assert fenetre.current_workdirs() == (deux,)


def test_removing_an_unknown_folder_is_harmless(fenetre, tmp_path):
    """Retirer ce qui n'est pas là ne doit pas lever."""
    dossier = str(tmp_path / "un")
    fenetre.add_workdir(dossier)

    fenetre.remove_workdir(str(tmp_path / "jamais-ajoute"))

    assert fenetre.current_workdirs() == (dossier,)


def test_the_choice_survives_a_restart(fenetre, reglages, tmp_path, qtbot):
    """Les dossiers sont mémorisés, comme l'était le dossier unique.

    Demandé à l'origine : « une fois sélectionné, le réglage doit
    rester à chaque fois ».
    """
    un, deux = str(tmp_path / "un"), str(tmp_path / "deux")
    fenetre.add_workdir(un)
    fenetre.add_workdir(deux)

    depot = _depot(tmp_path / "autre")
    seconde = MainWindow(pygit2.Repository(str(depot)), settings=reglages)
    qtbot.addWidget(seconde)

    assert seconde.current_workdirs() == (un, deux)


# --- le menu ------------------------------------------------------------


def _sous_menu_dossiers(fenetre) -> QMenu | None:
    menu = fenetre.workdir_button.menu()
    menu.aboutToShow.emit()
    for action in menu.actions():
        if action.menu() is not None and action.text() == "Folders":
            return action.menu()
    return None


def test_the_menu_offers_a_folders_submenu(fenetre):
    """Le sous-menu « Folders » existe, même sans dossier configuré.

    C'est par lui qu'on en ajoute un : le cacher quand la liste est
    vide rendrait la fonctionnalité introuvable.
    """
    sous_menu = _sous_menu_dossiers(fenetre)

    assert sous_menu is not None, "pas de sous-menu « Folders »"


def test_the_submenu_lists_every_folder(fenetre, tmp_path):
    """Chaque dossier configuré y figure, avec de quoi le retirer."""
    un, deux = str(tmp_path / "un"), str(tmp_path / "deux")
    fenetre.add_workdir(un)
    fenetre.add_workdir(deux)

    sous_menu = _sous_menu_dossiers(fenetre)
    sous_menu.aboutToShow.emit()
    intitules = [a.text() for a in sous_menu.actions()]

    assert any("Add folder" in t for t in intitules)
    assert any(un in t for t in intitules), f"« {un} » absent : {intitules}"
    assert any(deux in t for t in intitules)


def test_the_projects_of_every_folder_are_listed(fenetre, tmp_path):
    """Le menu principal montre les projets de TOUS les dossiers."""
    perso, boulot = tmp_path / "perso", tmp_path / "boulot"
    _depot(perso / "vti")
    _depot(boulot / "crm")
    fenetre.add_workdir(str(perso))
    fenetre.add_workdir(str(boulot))

    menu = fenetre.workdir_button.menu()
    menu.aboutToShow.emit()
    intitules = [a.text() for a in menu.actions()]

    assert any("vti" in t for t in intitules), intitules
    assert any("crm" in t for t in intitules), intitules


def test_a_missing_folder_does_not_hide_the_others(fenetre, tmp_path):
    """Un disque débranché ne doit pas vider le menu.

    C'est la raison d'être de plusieurs dossiers : si l'un tombe, les
    autres restent. Le menu doit les lister ET signaler l'absent.
    """
    bon = tmp_path / "bon"
    _depot(bon / "vti")
    fenetre.add_workdir(str(bon))
    fenetre.add_workdir(str(tmp_path / "jamais-cree"))

    menu = fenetre.workdir_button.menu()
    menu.aboutToShow.emit()
    intitules = [a.text() for a in menu.actions()]

    assert any("vti" in t for t in intitules), (
        f"le dossier valide a disparu : {intitules}"
    )
    assert any("not found" in t.lower() for t in intitules), (
        f"l'absence n'est pas signalée : {intitules}"
    )


# --- ce qui ne doit pas changer -----------------------------------------


def test_a_single_folder_looks_exactly_as_before(fenetre, tmp_path):
    """Un seul dossier : le menu est celui d'avant.

    Pas de préfixe sur les noms, pas d'entrée supplémentaire hormis
    le sous-menu.
    """
    racine = tmp_path / "Projects"
    _depot(racine / "vti")
    _depot(racine / "crm-equipment")
    fenetre.add_workdir(str(racine))

    menu = fenetre.workdir_button.menu()
    menu.aboutToShow.emit()
    projets = [
        a.text() for a in menu.actions()
        if a.text() in ("vti", "crm-equipment")
    ]

    assert sorted(projets) == ["crm-equipment", "vti"]
