"""`topy -s <motif>` : chercher un dépôt et le choisir dans une liste.

Demandé par l'utilisateur : « un paramètre qui permet de faire une
sorte de recherche de dépôt. Ex : `topy -s vti`. On affiche les
résultats en CLI sous forme de liste et on permet à l'user de choisir
le dépôt qu'il souhaite ouvrir. »

Puis, après avoir envisagé un menu aux flèches : « on part sur une
liste numérotée simple ». `curses` est absent de CPython sous
Windows, et un menu plein écran ne fonctionne pas dans un tube — il
aurait fallu écrire les deux.

Un point d'ordre, vérifié dans `cli.py` : `topy` se relance DÉTACHÉ
pour rendre la main au terminal en 0,07 s, les trois flux vers le
vide. L'invite doit donc venir AVANT ce détachement, sinon elle
poserait sa question à un terminal qui n'écoute plus.
"""

from __future__ import annotations

import os
import subprocess

import pytest

from tortoisepy.cli import main


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
def espace(tmp_path, monkeypatch):
    """Un dossier de projets, posé comme workdir mémorisé."""
    racine = tmp_path / "Projets"
    for nom in ("vti", "crm-equipment", "crm-signature", "airflow"):
        _depot(racine / nom)

    import tortoisepy.cli as cli

    monkeypatch.setattr(
        cli, "_workdir_memorise", lambda: str(racine), raising=False
    )
    return racine


@pytest.fixture
def ouvertures(monkeypatch):
    """Intercepte l'ouverture : aucun dépôt n'est réellement affiché."""
    import tortoisepy.cli as cli

    vus = []
    monkeypatch.setattr(
        cli, "_ouvrir", lambda chemin, arguments: vus.append(chemin) or 0,
        raising=False,
    )
    return vus


# --- le cas demandé -----------------------------------------------------


def test_a_single_match_opens_directly(espace, ouvertures, capsys):
    """Un seul résultat : pas de question à poser.

    `topy -s vti` sans aucune frappe de plus est exactement ce que
    l'utilisateur cherche. Afficher « 1. vti — votre choix ? »
    serait un clic pour rien.
    """
    assert main(["-s", "vti"]) == 0

    assert len(ouvertures) == 1
    assert ouvertures[0].endswith("vti")


def test_several_matches_are_listed_and_numbered(espace, ouvertures,
                                                  monkeypatch, capsys):
    """Le cas nominal : 5 résultats sur le dossier réel pour « crm »."""
    monkeypatch.setattr("builtins.input", lambda _: "2")

    assert main(["-s", "crm"]) == 0

    sortie = capsys.readouterr().out
    assert "1." in sortie and "2." in sortie
    assert "crm-equipment" in sortie
    assert "crm-signature" in sortie
    assert ouvertures[0].endswith("crm-signature")


def test_no_match_says_so(espace, ouvertures, capsys):
    """Zéro résultat est un cas ordinaire, pas une trace d'exécution."""
    assert main(["-s", "zzz"]) == 1

    assert not ouvertures
    message = capsys.readouterr().err
    assert "zzz" in message


def test_the_long_option_works_too(espace, ouvertures):
    """`--search` est plus explicite ; `-s` reste le raccourci."""
    assert main(["--search", "vti"]) == 0
    assert ouvertures


# --- le choix de l'utilisateur -----------------------------------------


def test_an_empty_answer_cancels(espace, ouvertures, monkeypatch):
    """Entrée seule : on sort sans rien ouvrir.

    Changer d'avis doit être possible sans chercher comment.

    Le code de sortie est 1 et NON 0, bien que l'annulation soit
    volontaire : 0 signifie « ce qui était demandé a été fait ». Un
    script enchaînant `topy -s crm && deploy` partirait sinon sur un
    déploiement alors que rien n'a été ouvert.
    """
    monkeypatch.setattr("builtins.input", lambda _: "")

    assert main(["-s", "crm"]) == 1
    assert not ouvertures


def test_ctrl_c_cancels_without_a_traceback(espace, ouvertures,
                                            monkeypatch):
    """`Ctrl-C` pendant l'invite.

    Sans traitement, `KeyboardInterrupt` remonterait en trace
    d'exécution — effrayant pour une annulation volontaire.
    """
    def _interrompre(_):
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", _interrompre)

    assert main(["-s", "crm"]) == 1
    assert not ouvertures


def test_end_of_input_cancels(espace, ouvertures, monkeypatch):
    """`Ctrl-D`, ou une entrée fermée par un script.

    `EOFError` lèverait aussi une trace d'exécution.
    """
    def _fin(_):
        raise EOFError

    monkeypatch.setattr("builtins.input", _fin)

    assert main(["-s", "crm"]) == 1
    assert not ouvertures


def test_an_out_of_range_number_is_refused(espace, ouvertures,
                                           monkeypatch, capsys):
    """« 9 » sur une liste de deux.

    Ouvrir le dernier par défaut serait pire : on croirait avoir
    choisi.
    """
    monkeypatch.setattr("builtins.input", lambda _: "9")

    assert main(["-s", "crm"]) == 1
    assert not ouvertures


def test_a_non_numeric_answer_is_refused(espace, ouvertures,
                                         monkeypatch):
    """Une faute de frappe ne doit pas lever."""
    monkeypatch.setattr("builtins.input", lambda _: "abc")

    assert main(["-s", "crm"]) == 1
    assert not ouvertures


def test_the_first_choice_is_one_not_zero(espace, ouvertures,
                                          monkeypatch):
    """La liste s'affiche de 1 à n : « 1 » doit viser le premier.

    Numéroter à partir de 0 ferait ouvrir le mauvais projet à
    quiconque lit l'écran.
    """
    monkeypatch.setattr("builtins.input", lambda _: "1")

    assert main(["-s", "crm"]) == 0
    assert ouvertures[0].endswith("crm-equipment")


# --- les cas limites ----------------------------------------------------


def test_search_without_a_keyword_is_refused(espace, ouvertures,
                                             capsys):
    """`topy -s` seul rendrait 61 lignes sur le dossier réel.

    Mieux vaut l'usage qu'un terminal noyé.
    """
    assert main(["-s"]) == 1
    assert not ouvertures


def test_search_without_a_workdir_explains(tmp_path, ouvertures,
                                           monkeypatch, capsys):
    """Sans dossier de projets choisi, la recherche n'a rien à lire.

    Le message doit dire quoi faire, pas seulement constater
    l'échec : l'utilisateur ne devinera pas qu'il faut passer par
    « Open Project ».
    """
    import tortoisepy.cli as cli

    monkeypatch.setattr(cli, "_workdir_memorise", lambda: "",
                        raising=False)

    assert main(["-s", "vti"]) == 1

    message = capsys.readouterr().err.lower()
    assert "open project" in message or "dossier" in message


def test_a_path_argument_still_works(espace, ouvertures):
    """La recherche ne doit pas casser l'usage existant.

    `topy <chemin>` reste le comportement par défaut ; `-s` est une
    option, pas un remplacement.
    """
    assert main([str(espace / "vti")]) == 0
    assert ouvertures
