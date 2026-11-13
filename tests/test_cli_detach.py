"""`topy` rend la main au shell au lieu de le bloquer.

Signalé par l'utilisateur, capture à l'appui : lancer `topy` figeait le
terminal jusqu'à la fermeture de la fenêtre. C'est le comportement normal
de `QApplication.exec()`, mais pas celui qu'on attend d'un lanceur
d'application graphique.

La relance passe par `subprocess.Popen` et non `os.fork` : **`fork`
n'existe pas sur Windows** (vérifié), et l'application doit marcher sur
les deux plateformes.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from tortoisepy import cli


def test_fork_is_not_called(monkeypatch):
    """Le test qui protège Windows.

    `os.fork` et `os.setsid` y sont ABSENTS : s'en servir casserait
    l'application sur la moitié des plateformes visées, sans qu'aucun
    test macOS ne le voie.

    On inspecte l'arbre syntaxique et non le texte : chercher « os.fork »
    dans la source trouverait aussi le commentaire qui explique pourquoi
    on ne l'emploie pas — un test vert pour la mauvaise raison.
    """
    import ast
    import pathlib

    arbre = ast.parse(pathlib.Path(cli.__file__).read_text())
    appels = {
        f"{n.func.value.id}.{n.func.attr}"
        for n in ast.walk(arbre)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and isinstance(n.func.value, ast.Name)
    }

    assert "os.fork" not in appels, (
        "os.fork n'existe pas sur Windows — utiliser subprocess.Popen"
    )
    assert "os.setsid" not in appels, (
        "os.setsid n'existe pas non plus sur Windows"
    )


def test_the_detach_flags_match_the_platform():
    """Chaque plateforme a son mécanisme ; aucun n'est portable seul."""
    options = cli._options_de_detachement()

    if sys.platform == "win32":
        assert "creationflags" in options
        assert options["creationflags"] & subprocess.DETACHED_PROCESS
    else:
        assert options.get("start_new_session") is True
        assert "creationflags" not in options, (
            "creationflags n'existe que sur Windows"
        )


def test_an_inherited_marker_does_not_block_the_relaunch(monkeypatch):
    """Signalé par l'utilisateur : le prompt n'est pas rendu sous VSCode.

        « quand j'ouvre un graph avec la commande topy depuis le cli de
          vscode, le prompt n'est pas libéré, par contre depuis mon
          terminal oui »

    Diagnostic : `TORTOISEPY_DETACHE=1` traînait dans son shell. Une
    variable d'environnement est **héritée par tout descendant,
    indéfiniment** — il suffit qu'un `topy` ait un jour lancé un shell,
    ou que VSCode ait démarré depuis un contexte contaminé, pour que
    tous ses terminaux la portent. `topy` se croyait alors déjà
    détaché, ouvrait la fenêtre dans le processus courant et gardait le
    prompt.

    Le marqueur ne doit donc plus décider de rien.
    """
    import tortoisepy.cli as cli

    monkeypatch.setenv("TORTOISEPY_DETACHE", "1")
    vus = []
    monkeypatch.setattr(
        cli.subprocess, "Popen",
        lambda *a, **k: vus.append((a, k)),
    )
    # Pas chef de session : un shell ordinaire.
    monkeypatch.setattr(cli.os, "getpid", lambda: 1000)
    monkeypatch.setattr(cli.os, "getsid", lambda _pid: 999)

    assert cli._relancer_detache(["/un/chemin"]) is True, (
        "une variable héritée empêche encore le détachement"
    )
    assert vus, "aucune relance lancée"


def test_a_session_leader_does_not_relaunch_itself(monkeypatch):
    """Le processus DÉJÀ détaché ne doit pas en relancer un autre.

    C'est ce que le marqueur assurait, et que le test de session
    remplace. Mesuré : `start_new_session=True` fait du processus le
    chef de sa session — propriété observable, et contrairement à une
    variable, **non héritable**. Un petit-enfant rend `False` et peut
    donc se relancer normalement.
    """
    import tortoisepy.cli as cli

    monkeypatch.delenv("TORTOISEPY_DETACHE", raising=False)
    vus = []
    monkeypatch.setattr(
        cli.subprocess, "Popen",
        lambda *a, **k: vus.append((a, k)),
    )
    monkeypatch.setattr(cli.os, "getpid", lambda: 1000)
    monkeypatch.setattr(cli.os, "getsid", lambda _pid: 1000)

    assert cli._relancer_detache(["/un/chemin"]) is False
    assert not vus, "le processus détaché s'est relancé lui-même"


def test_a_grandchild_is_not_mistaken_for_the_detached_process(monkeypatch):
    """LE cas que la variable rendait faux.

    Mesuré : un petit-enfant d'un processus détaché n'est PAS chef de
    session (sid différent de son pid), alors qu'il héritait bien de
    `TORTOISEPY_DETACHE=1`.
    """
    import tortoisepy.cli as cli

    monkeypatch.setenv("TORTOISEPY_DETACHE", "1")
    vus = []
    monkeypatch.setattr(
        cli.subprocess, "Popen",
        lambda *a, **k: vus.append((a, k)),
    )
    # Petit-enfant : la session est celle de son parent détaché.
    monkeypatch.setattr(cli.os, "getpid", lambda: 2000)
    monkeypatch.setattr(cli.os, "getsid", lambda _pid: 1000)

    assert cli._relancer_detache(["/un/chemin"]) is True
    assert vus


def test_relaunching_is_skipped_when_already_detached(monkeypatch):
    """Sans ce garde-fou, `topy` se relancerait à l'infini.

    Le critère n'est plus une variable d'environnement mais la qualité
    de chef de session : elle dit la même chose, sans être héritée par
    les descendants. Voir `_deja_detache`.
    """
    lancements = []
    monkeypatch.setattr(
        cli.subprocess, "Popen",
        lambda *a, **k: lancements.append(a) or None,
    )
    monkeypatch.setattr(cli.os, "getpid", lambda: 1000)
    monkeypatch.setattr(cli.os, "getsid", lambda _pid: 1000)

    assert cli._relancer_detache([".", ]) is False
    assert lancements == [], "l'enfant ne doit jamais se relancer"


def test_relaunching_passes_the_arguments(monkeypatch):
    """Le chemin du dépôt doit survivre à la relance."""
    captures = []
    monkeypatch.setattr(
        cli.subprocess, "Popen",
        lambda commande, **k: captures.append((commande, k)) or None,
    )
    monkeypatch.delenv(cli._MARQUEUR_DETACHE, raising=False)
    # Pas chef de session : un shell ordinaire, qui doit relancer.
    monkeypatch.setattr(cli.os, "getsid", lambda _pid: os.getpid() + 1)

    assert cli._relancer_detache(["/un/chemin"]) is True
    commande, options = captures[0]
    assert "/un/chemin" in commande
    assert options["env"][cli._MARQUEUR_DETACHE] == "1"


def test_the_detached_child_is_cut_from_the_terminal(monkeypatch):
    """Sorties vers le vide : le terminal peut disparaître (§choix user).

    Écrire dessus après sa fermeture lèverait une erreur dans une
    application qui n'a plus personne pour la lire.
    """
    captures = []
    monkeypatch.setattr(
        cli.subprocess, "Popen",
        lambda commande, **k: captures.append(k) or None,
    )
    monkeypatch.delenv(cli._MARQUEUR_DETACHE, raising=False)
    # Pas chef de session : un shell ordinaire, qui doit relancer.
    monkeypatch.setattr(cli.os, "getsid", lambda _pid: os.getpid() + 1)

    cli._relancer_detache([])
    options = captures[0]
    assert options["stdin"] is subprocess.DEVNULL
    assert options["stdout"] is subprocess.DEVNULL
    assert options["stderr"] is subprocess.DEVNULL


def test_wait_keeps_the_old_behaviour(monkeypatch):
    """`--wait` doit bloquer, pour les scripts qui en dépendent."""
    lancements = []
    monkeypatch.setattr(
        cli.subprocess, "Popen",
        lambda *a, **k: lancements.append(a) or None,
    )
    monkeypatch.delenv(cli._MARQUEUR_DETACHE, raising=False)
    # Pas chef de session : un shell ordinaire, qui doit relancer.
    monkeypatch.setattr(cli.os, "getsid", lambda _pid: os.getpid() + 1)
    monkeypatch.setattr(cli, "find_repository", lambda cible: None)

    # `--wait` est consommé, et aucune relance n'a lieu.
    code = cli.main(["--wait", "/pas/un/depot"])
    assert code == 1, "le chemin invalide doit être signalé"
    assert lancements == [], "`--wait` ne doit pas relancer en détaché"


def test_wait_is_documented():
    """Une option invisible n'existe pas pour l'utilisateur."""
    assert "--wait" in cli._USAGE


def test_an_unknown_option_is_still_refused(monkeypatch):
    monkeypatch.delenv(cli._MARQUEUR_DETACHE, raising=False)
    # Pas chef de session : un shell ordinaire, qui doit relancer.
    monkeypatch.setattr(cli.os, "getsid", lambda _pid: os.getpid() + 1)
    assert cli.main(["--verison"]) == 1
