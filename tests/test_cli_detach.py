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


def test_relaunching_is_skipped_when_already_detached(monkeypatch):
    """Sans ce garde-fou, `topy` se relancerait à l'infini."""
    lancements = []
    monkeypatch.setattr(
        cli.subprocess, "Popen",
        lambda *a, **k: lancements.append(a) or None,
    )
    monkeypatch.setenv(cli._MARQUEUR_DETACHE, "1")

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
    assert cli.main(["--verison"]) == 1
