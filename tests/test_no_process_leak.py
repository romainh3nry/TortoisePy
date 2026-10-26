"""Aucun test ne doit lancer une vraie application détachée.

Constaté sur la machine de l'utilisateur : un processus `tortoisepy.cli`
tournait depuis des heures, pointant sur un dossier temporaire
(`pytest-526/test_a_path_argument_still_wor0`) supprimé depuis. Un
essai intermédiaire avait appelé `main([<chemin>])` sans intercepter la
relance, et `subprocess.Popen` avec `start_new_session=True` survit à
la fin de la suite — personne ne le remarque.

Le risque n'est pas théorique : un test qui oublie l'interception
passe au vert tout en laissant une application ouverte. Ces deux
tests ferment la porte, chacun à un endroit différent.
"""

from __future__ import annotations

import pathlib
import subprocess

import pytest

import tortoisepy.cli as cli


@pytest.fixture
def popen_interdit(monkeypatch):
    """Rend tout appel réel à `Popen` impossible à manquer."""
    appels = []

    def refuser(*args, **kwargs):
        appels.append(args)
        raise AssertionError(
            "un test a lancé une vraie application détachée : "
            f"{args!r}. Intercepter `_ouvrir` ou `subprocess.Popen`."
        )

    monkeypatch.setattr(cli.subprocess, "Popen", refuser)
    return appels


def test_the_guard_fixture_itself_fires(popen_interdit):
    """Le garde-fou doit lever, sinon il ne garde rien.

    Un `monkeypatch` mal posé rendrait les deux tests suivants
    silencieusement inutiles.
    """
    with pytest.raises(AssertionError, match="vraie application"):
        cli.subprocess.Popen(["/bin/true"])


def test_the_detach_marker_stops_the_relaunch(monkeypatch, popen_interdit):
    """Le marqueur d'environnement suffit à couper la relance.

    C'est la protection la moins coûteuse pour un test qui doit
    traverser `_afficher` : poser le marqueur, et `_relancer_detache`
    rend `False` sans jamais appeler `Popen`.
    """
    monkeypatch.setenv(cli._MARQUEUR_DETACHE, "1")

    assert cli._relancer_detache(["/un/chemin"]) is False


def test_relaunching_without_the_marker_would_spawn(monkeypatch):
    """Et sans marqueur, la relance appelle BIEN `Popen`.

    Le test précédent ne prouve rien si la relance n'appelle jamais
    `Popen` de toute façon. Celui-ci le vérifie, sans rien lancer.
    """
    vus = []
    monkeypatch.setattr(
        cli.subprocess, "Popen",
        lambda *args, **kwargs: vus.append((args, kwargs)),
    )
    monkeypatch.delenv(cli._MARQUEUR_DETACHE, raising=False)

    assert cli._relancer_detache(["/un/chemin"]) is True
    assert len(vus) == 1
    # Et c'est bien un processus détaché : c'est ce qui le fait
    # survivre à la suite.
    assert vus[0][1].get("start_new_session") is True


def test_no_tortoisepy_process_survives_this_suite():
    """Filet de sécurité : aucun processus résiduel à la fin.

    Ne regarde que les processus pointant sur un dossier temporaire de
    pytest — l'utilisateur peut avoir sa propre application ouverte
    sur un vrai dépôt, et l'accuser serait un faux positif.
    """
    sortie = subprocess.run(
        ["ps", "-Ao", "command"], capture_output=True, text=True
    ).stdout

    # Le filtre porte sur le PREMIER MOT de la commande, qui doit etre
    # un interpreteur Python. Chercher le nom du module n'importe ou
    # dans la ligne ne marche pas : ce fichier de test le contient, et
    # tout shell qui l'ecrit ou le lit s'accuse lui-meme (constate deux
    # fois en ecrivant ce test).
    fuites = []
    for ligne in sortie.splitlines():
        mots = ligne.split()
        if len(mots) < 3:
            continue
        executable = pathlib.Path(mots[0]).name
        lance_le_module = mots[1:3] == ["-m", "tortoisepy.cli"]
        if executable.startswith("python") and lance_le_module:
            if any("pytest-of-" in mot for mot in mots[3:]):
                fuites.append(ligne)

    assert not fuites, (
        "des applications lancées par la suite tournent encore :\n"
        + "\n".join(fuites)
    )
