"""Les scripts d'installation — vérifiés, jamais exécutés.

Les lancer installerait vraiment tortoisePy sur la machine qui joue la
suite de tests. On éprouve donc leur contenu, pas leur effet.
"""

import re
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
SCRIPTS = ("install.sh", "install.ps1")


@pytest.mark.parametrize("nom", SCRIPTS)
def test_the_script_exists(nom):
    assert (RACINE / "scripts" / nom).is_file()


@pytest.mark.parametrize("nom", SCRIPTS)
def test_the_script_checks_that_the_command_answers(nom):
    """D32 : le piège du PATH.

    Vérifié lors d'une vraie installation : `uv` avertit que
    `~/.local/bin` n'est pas dans le PATH, l'installation réussit, et la
    commande reste introuvable. C'est là qu'un utilisateur abandonne — un
    installeur qui ne vérifie pas son propre résultat n'a pas fini.
    """
    contenu = (RACINE / "scripts" / nom).read_text()

    # Chercher « topy --version » ne suffit pas : la chaîne pourrait
    # n'apparaître que dans un message d'aide. Vérifié par mutation —
    # remplacer l'appel par `true` laissait le test passer. Ce qui
    # compte, c'est que le script **branche** sur le résultat.
    if nom.endswith(".sh"):
        assert re.search(r"if\s+.*topy\s+--version", contenu), (
            "le script doit éprouver la commande, pas seulement la citer"
        )
        assert "exit 1" in contenu, "un échec doit se voir dans le code de sortie"
    else:
        assert re.search(r"topy\s+--version", contenu)
        assert "$LASTEXITCODE" in contenu, "le script doit lire le code de retour"
        assert "exit 1" in contenu

    assert "PATH" in contenu, "il doit savoir expliquer le PATH"
    assert "update-shell" in contenu, "il doit donner la commande qui répare"


def test_the_shell_script_is_executable():
    import os

    assert os.access(RACINE / "scripts" / "install.sh", os.X_OK), "chmod +x manquant"


@pytest.mark.parametrize("nom", SCRIPTS)
def test_the_script_never_publishes(nom):
    """Un installeur qui publierait serait un accident grave."""
    contenu = (RACINE / "scripts" / nom).read_text()
    assert "uv publish" not in contenu
    assert "pypi.org/legacy" not in contenu


@pytest.mark.parametrize("nom", SCRIPTS)
def test_the_script_installs_from_the_repository(nom):
    """D33 : depuis GitHub, donc rien d'irréversible à faire d'abord."""
    contenu = (RACINE / "scripts" / nom).read_text()
    assert "git+https://github.com/romainh3nry/TortoisePy" in contenu


def test_the_version_references_agree():
    """D34, et le piège du tag : deux endroits, une seule version.

    Figer l'URL du README sans figer le `@tag` du script ne fige **rien** :
    le script prendrait la branche par défaut. Et c'est l'oubli invisible,
    puisque le README, lui, a l'air juste.
    """
    readme = (RACINE / "README.md").read_text()
    dans_url = set(re.findall(r"TortoisePy/(v[\d.]+)/scripts/", readme))
    assert dans_url, "aucun tag dans les URL du README"

    for nom in SCRIPTS:
        contenu = (RACINE / "scripts" / nom).read_text()
        # Les scripts composent l'URL depuis une variable de version :
        # chercher « TortoisePy@v0.1.0» littéralement échouerait alors que
        # le script est juste. C'est la variable qu'on éprouve.
        declarees = set(re.findall(r'(?:VERSION|\$Version)\s*=\s*"(v[\d.]+)"', contenu))
        assert declarees, f"{nom} n'épingle aucune version"
        assert declarees == dans_url, (
            f"{nom} installe {declarees}, le README annonce {dans_url}"
        )
        assert "TortoisePy@" in contenu, (
            f"{nom} doit viser le tag, pas la branche par défaut"
        )


def test_the_readme_version_matches_the_package():
    """Un README qui annonce une version que le paquet n'a pas mentirait."""
    import tomllib

    config = tomllib.loads((RACINE / "pyproject.toml").read_text())
    version = config["project"]["version"]

    readme = (RACINE / "README.md").read_text()
    tags = set(re.findall(r"TortoisePy/v([\d.]+)/scripts/", readme))
    assert tags == {version}, f"README annonce {tags}, le paquet est en {version}"
