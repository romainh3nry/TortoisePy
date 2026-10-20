"""Trouver les éditeurs installés, pour ouvrir le projet dedans.

Demandé par l'utilisateur : un bouton qui ouvre le projet comme le
ferait `code .`, affiché seulement si l'éditeur est là.

Le piège, mesuré avant d'écrire : l'application se lance depuis un
**bundle macOS**, qui ne reçoit pas le `PATH` du terminal mais un
`PATH` minimal. `shutil.which("code")` y rend `None` alors que VSCode
est installé — le bouton disparaîtrait chez quelqu'un qui l'a. D'où
les chemins de repli, éprouvés par un test dédié.

Aucun Qt : la détection est de la logique pure, et `tests/core` ne
dépend d'aucune fenêtre.
"""

from __future__ import annotations

import os
import stat

import pytest

from tortoisepy.core.editors import (
    CATALOGUE,
    Editor,
    find_editors,
    open_in_editor,
)


def _faux_executable(chemin):
    """Un fichier exécutable : ce que `which` et les replis cherchent."""
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text("#!/bin/sh\nexit 0\n")
    chemin.chmod(chemin.stat().st_mode | stat.S_IEXEC)
    return chemin


# --- le catalogue -------------------------------------------------------


def test_the_catalogue_is_not_empty():
    """Sans catalogue, aucun éditeur ne serait jamais proposé."""
    assert CATALOGUE


def test_vscode_is_in_the_catalogue():
    """La demande nommait VSCode."""
    assert any(e.command == "code" for e in CATALOGUE)


def test_every_entry_has_a_label_and_a_command():
    """Le libellé va dans le menu, la commande sert à lancer.

    Une entrée sans libellé afficherait une ligne vide ; sans
    commande, elle ne lancerait rien.
    """
    for entree in CATALOGUE:
        assert entree.label.strip(), entree
        assert entree.command.strip(), entree


def test_the_labels_are_unique():
    """Deux lignes identiques dans le menu rendraient le choix
    impossible."""
    libelles = [e.label for e in CATALOGUE]
    assert len(libelles) == len(set(libelles)), libelles


# --- la détection -------------------------------------------------------


def test_an_editor_on_the_path_is_found(tmp_path, monkeypatch):
    """Le cas ordinaire : la commande est dans le `PATH`."""
    faux = _faux_executable(tmp_path / "bin" / "code")
    monkeypatch.setenv("PATH", str(faux.parent))

    trouves = find_editors()

    assert any(e.command == "code" for e in trouves)
    vscode = next(e for e in trouves if e.command == "code")
    assert vscode.path == str(faux)


def test_nothing_is_found_when_nothing_is_installed(tmp_path,
                                                    monkeypatch):
    """« Si pas installé, on affiche rien » — la demande.

    Un menu qui proposerait un éditeur absent ferait cliquer pour
    apprendre un échec évitable.
    """
    monkeypatch.setenv("PATH", str(tmp_path / "vide"))
    monkeypatch.setattr(
        "tortoisepy.core.editors._REPLIS", {}, raising=False
    )

    assert find_editors() == ()


def test_a_fallback_path_is_used_when_the_path_is_minimal(tmp_path,
                                                          monkeypatch):
    """LE piège, mesuré : le `PATH` du Dock.

    Une application lancée depuis un bundle macOS reçoit un `PATH`
    minimal, où `which("code")` rend `None` alors que VSCode est bien
    installé. Vérifié avant d'écrire :

        which("code") depuis le terminal    -> /usr/local/bin/code
        which("code") avec un PATH minimal  -> None

    Sans repli, le bouton disparaîtrait chez un utilisateur qui l'a.
    """
    cache = _faux_executable(tmp_path / "ailleurs" / "code")
    monkeypatch.setenv("PATH", str(tmp_path / "vide"))
    monkeypatch.setattr(
        "tortoisepy.core.editors._REPLIS",
        {"code": (str(cache),)},
        raising=False,
    )

    trouves = find_editors()

    assert any(e.path == str(cache) for e in trouves), (
        "le repli n'a pas été consulté : le bouton disparaîtrait sur "
        "une application lancée depuis le Dock"
    )


def test_the_path_wins_over_the_fallback(tmp_path, monkeypatch):
    """Ce que l'utilisateur a mis dans son `PATH` fait foi.

    Il peut y avoir placé une version précise, ou un script à lui.
    Le repli est un filet, pas une préférence.
    """
    dans_path = _faux_executable(tmp_path / "bin" / "code")
    repli = _faux_executable(tmp_path / "ailleurs" / "code")
    monkeypatch.setenv("PATH", str(dans_path.parent))
    monkeypatch.setattr(
        "tortoisepy.core.editors._REPLIS",
        {"code": (str(repli),)},
        raising=False,
    )

    vscode = next(e for e in find_editors() if e.command == "code")

    assert vscode.path == str(dans_path)


def test_a_non_executable_file_is_not_an_editor(tmp_path, monkeypatch):
    """Un fichier du bon nom mais sans droit d'exécution.

    Le lancer échouerait ; le proposer ferait cliquer pour rien.
    """
    faux = tmp_path / "ailleurs" / "code"
    faux.parent.mkdir(parents=True)
    faux.write_text("pas executable")
    monkeypatch.setenv("PATH", str(tmp_path / "vide"))
    monkeypatch.setattr(
        "tortoisepy.core.editors._REPLIS",
        {"code": (str(faux),)},
        raising=False,
    )

    assert find_editors() == ()


def test_a_missing_fallback_is_skipped(tmp_path, monkeypatch):
    """Un chemin de repli qui n'existe pas ne doit pas lever.

    La liste des replis vieillira : un éditeur déplacé ne doit pas
    empêcher de trouver les autres.
    """
    monkeypatch.setenv("PATH", str(tmp_path / "vide"))
    monkeypatch.setattr(
        "tortoisepy.core.editors._REPLIS",
        {"code": ("/chemin/qui/n/existe/pas",)},
        raising=False,
    )

    assert find_editors() == ()


def test_the_results_keep_the_catalogue_order(tmp_path, monkeypatch):
    """L'ordre du menu doit être stable, pas celui du disque.

    Deux lancements qui proposeraient les éditeurs dans un ordre
    différent feraient cliquer au mauvais endroit par habitude.
    """
    binaire = tmp_path / "bin"
    for entree in CATALOGUE:
        _faux_executable(binaire / entree.command)
    monkeypatch.setenv("PATH", str(binaire))

    trouves = find_editors()

    assert [e.command for e in trouves] == [
        e.command for e in CATALOGUE
    ]


# --- l'ouverture --------------------------------------------------------


def test_opening_runs_the_editor_with_the_folder(tmp_path, monkeypatch):
    """`code .` — la demande, mot pour mot."""
    faux = _faux_executable(tmp_path / "bin" / "code")
    projet = tmp_path / "mon-projet"
    projet.mkdir()
    lances = []

    monkeypatch.setattr(
        "tortoisepy.core.editors._lancer",
        lambda commande: lances.append(commande) or True,
    )
    editeur = Editor(label="VS Code", command="code", path=str(faux))

    assert open_in_editor(editeur, str(projet)) is True
    assert lances == [[str(faux), str(projet)]]


def test_opening_reports_a_failure(tmp_path, monkeypatch):
    """Un éditeur peut exister et refuser de démarrer.

    Installation abîmée, droits manquants : l'appelant doit pouvoir
    le dire à l'utilisateur plutôt que de laisser un clic sans effet.
    """
    monkeypatch.setattr(
        "tortoisepy.core.editors._lancer", lambda commande: False
    )
    editeur = Editor(label="VS Code", command="code", path="/bin/code")

    assert open_in_editor(editeur, str(tmp_path)) is False


def test_opening_a_missing_folder_is_refused(tmp_path, monkeypatch):
    """Le projet a pu disparaître entre l'affichage et le clic.

    Même cas que « Open Project » : on refuse plutôt que de lancer
    un éditeur sur un dossier absent.
    """
    lances = []
    monkeypatch.setattr(
        "tortoisepy.core.editors._lancer",
        lambda commande: lances.append(commande) or True,
    )
    editeur = Editor(label="VS Code", command="code", path="/bin/code")

    assert open_in_editor(editeur, str(tmp_path / "jamais")) is False
    assert lances == [], "l'éditeur a été lancé sur un dossier absent"


# --- §7.0 : rien ne doit être écrit ------------------------------------


def test_detection_writes_nothing(tmp_path, monkeypatch):
    """Chercher un éditeur est une lecture du disque.

    §7.0 : l'application ne modifie rien sans action explicite.
    Détecter n'en est pas une.
    """
    binaire = tmp_path / "bin"
    _faux_executable(binaire / "code")
    monkeypatch.setenv("PATH", str(binaire))

    avant = {
        c: c.stat().st_mtime for c in tmp_path.rglob("*")
    }
    find_editors()
    apres = {
        c: c.stat().st_mtime for c in tmp_path.rglob("*")
    }

    assert avant == apres


def test_the_editor_is_launched_detached(monkeypatch, tmp_path):
    """Attendre la fermeture de l'éditeur gèlerait l'application.

    Le même défaut que l'ouverture de projet synchrone, corrigée
    ailleurs : tant que le processus fils vit, le fil principal ne
    peindrait plus rien. Un éditeur reste ouvert des heures.

    On éprouve l'APPEL, pas l'intention : `start_new_session` détache
    le fils de la session, et `Popen` rend la main aussitôt.
    """
    from tortoisepy.core import editors

    appels = []

    class _FauxPopen:
        def __init__(self, commande, **kw):
            appels.append(kw)

    monkeypatch.setattr(editors.subprocess, "Popen", _FauxPopen)
    projet = tmp_path / "projet"
    projet.mkdir()

    editors.open_in_editor(
        Editor("VS Code", "code", "/bin/code"), str(projet)
    )

    assert appels, "aucun processus lancé"
    assert appels[0].get("start_new_session") is True, (
        "le processus n'est pas détaché : l'application attendrait la "
        f"fermeture de l'éditeur — {appels[0]}"
    )
    assert "wait" not in str(appels[0])


def test_every_catalogue_entry_can_be_found_somewhere():
    """Une entrée sans commande dans le `PATH` ni repli est morte.

    Elle ne serait jamais proposée, quoi que l'utilisateur installe.
    Le piège : ajouter un éditeur au catalogue en oubliant son chemin
    de repli — invisible, puisque rien ne lève.
    """
    from tortoisepy.core.editors import _REPLIS

    sans_repli = [
        e.command for e in CATALOGUE if e.command not in _REPLIS
    ]

    assert not sans_repli, (
        f"ces éditeurs n'ont aucun chemin de repli : {sans_repli}. "
        "Ils seraient introuvables sur une application lancée depuis "
        "le Dock, qui ne reçoit pas le PATH de l'utilisateur."
    )


def test_the_jetbrains_family_is_complete():
    """PhpStorm manquait à la première version, et il était installé.

    Relevé par l'utilisateur. Tous ces outils partagent le même
    dossier de scripts posé par Toolbox : en oublier un revient à le
    rendre invisible sans raison.
    """
    commandes = {e.command for e in CATALOGUE}
    attendus = {
        "phpstorm", "pycharm", "idea", "webstorm", "goland",
        "rubymine", "clion", "rider", "datagrip", "studio",
    }

    manquants = attendus - commandes
    assert not manquants, f"outils JetBrains absents : {manquants}"
