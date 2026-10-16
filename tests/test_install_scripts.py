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


def test_the_download_urls_point_at_a_stable_branch():
    """Les URL de téléchargement ne portent plus de version.

    Demandé par l'utilisateur : « que l'URL d'installation pointe
    toujours vers la dernière version sans spécifier le numéro ».

    Avant, chaque URL citait le tag (`…/v0.13.0/scripts/install.sh`) :
    toute version obligeait à réécrire le README, et une URL copiée
    dans un wiki ou un message périmait en silence. `main` est servie
    par GitHub comme n'importe quelle référence, et c'est la branche
    de production du projet — elle ne reçoit que du publié.

    Attention à ce que ce test NE dit pas : la référence *installée*
    reste un tag figé (cf. `test_the_scripts_install_a_pinned_tag`).
    Seul le chemin de téléchargement devient stable.
    """
    readme = (RACINE / "README.md").read_text()

    versionnees = re.findall(r"TortoisePy/v[\d.]+/scripts/", readme)
    assert not versionnees, (
        f"des URL portent encore un tag : {set(versionnees)}"
    )

    assert "TortoisePy/main/scripts/install.sh" in readme
    assert "TortoisePy/main/scripts/install.ps1" in readme

    # Les deux installeurs citent leur propre URL en en-tête : elle doit
    # suivre, sinon un lecteur copierait la forme périmée.
    for nom in SCRIPTS:
        contenu = (RACINE / "scripts" / nom).read_text()
        entete = [l for l in contenu.splitlines() if "raw.githubusercontent" in l]
        assert entete, f"{nom} ne cite plus son URL d'installation"
        for ligne in entete:
            assert "/main/scripts/" in ligne, (
                f"{nom} cite une URL versionnée : {ligne.strip()}"
            )


def test_the_scripts_install_from_main():
    """Les installeurs ne portent plus aucun numéro de version.

    Choix de l'utilisateur. Avant, `VERSION="v0.17.0"` était écrit en
    dur dans les deux scripts et dans le README : quatre fichiers à
    maintenir d'accord, et une version oubliée publiait un installeur
    qui posait la précédente.

    `@main` supprime la synchronisation plutôt que de l'automatiser.
    `pyproject.toml` reste le seul endroit où la version s'écrit, et
    c'est lui que lit `importlib.metadata` pour `topy --version`.

    Le compromis, assumé : l'installation suit `main` et non un tag
    figé. Chez ce projet, `main` est la production et rien n'y entre
    sans pull request verte.
    """
    for nom in SCRIPTS:
        contenu = (RACINE / "scripts" / nom).read_text()

        assert "TortoisePy@main" in contenu, (
            f"{nom} n'installe pas depuis `main`"
        )
        epinglees = re.findall(
            r'(?:VERSION|\$Version)\s*=\s*"v[\d.]+"', contenu
        )
        assert not epinglees, (
            f"{nom} épingle encore une version : {epinglees}"
        )


def test_the_readme_holds_no_version():
    """Le README cite des commandes à copier : aucune ne doit vieillir.

    Une commande qui nomme `v0.17.0` devient fausse à la version
    suivante, et personne ne s'en aperçoit avant qu'un utilisateur
    installe du code périmé.
    """
    readme = (RACINE / "README.md").read_text()

    versionnees = re.findall(r"TortoisePy[@/]v[\d.]+", readme)
    assert not versionnees, (
        f"le README épingle des versions : {set(versionnees)}"
    )


def test_pyproject_is_the_only_place_a_version_is_written():
    """Une seule source, et le reste la déduit.

    Ce test est le garde-fou du choix : si quelqu'un réintroduit un
    numéro ailleurs demain, la synchronisation manuelle revient avec
    lui — et c'est exactement ce qu'on vient de supprimer.
    """
    import tomllib

    config = tomllib.loads((RACINE / "pyproject.toml").read_text())
    version = config["project"]["version"]

    # On interroge Git plutôt que d'exclure des dossiers à la main :
    # `src/tortoisepy.egg-info/PKG-INFO` est un artefact de build qui
    # porte légitimement la version, et une liste écrite en dur
    # périmerait au premier dossier ajouté.
    import subprocess

    suivis = subprocess.run(
        ["git", "ls-files"], cwd=RACINE,
        capture_output=True, text=True, check=True,
    ).stdout.split()

    ailleurs = []
    for relatif in suivis:
        chemin = RACINE / relatif
        if relatif == "pyproject.toml" or chemin.suffix in {".png", ".ico"}:
            continue
        # Les tests citent des versions dans leurs explications : ils
        # décrivent l'histoire du projet, ils ne la configurent pas.
        if relatif.startswith(("tests/", "docs/")):
            continue
        try:
            contenu = chemin.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        if version in contenu:
            ailleurs.append(relatif)

    assert not ailleurs, (
        f"la version {version} apparaît hors de pyproject.toml : "
        f"{ailleurs}"
    )


def test_the_reported_version_follows_the_package():
    """Trouvé en testant une mise à jour : `topy --version` mentait.

    `cli.py` portait `__version__ = "0.1.0"` en dur. Avec un
    `pyproject.toml` passé en 0.2.0, le paquet installé était bien en
    0.2.0 mais la commande annonçait 0.1.0 — et rien ne le signalait.
    """
    import tomllib

    from tortoisepy.cli import __version__

    config = tomllib.loads((RACINE / "pyproject.toml").read_text())
    declaree = config["project"]["version"]

    assert __version__ == declaree, (
        f"`topy --version` dit {__version__}, le paquet est en "
        f"{declaree}.\n"
        "Si vous venez de monter la version dans pyproject.toml, le "
        "venv local est resté en arrière :\n"
        "    uv pip install -e . --no-deps\n"
        "La CI ne connaît pas ce cas — elle installe le paquet à "
        "chaque exécution. Depuis la suppression de `set-version.py`, "
        "qui rafraîchissait le venv, c'est à faire à la main."
    )


def test_the_readme_does_not_promise_uv_tool_upgrade():
    """Vérifié : sur une install épinglée, uv répond « Nothing to upgrade ».

    C'est le comportement correct d'un tag figé — mais le README le
    documentait comme chemin de mise à jour, ce qui était faux.
    """
    readme = (RACINE / "README.md").read_text()
    section = readme[readme.index("### Updating"):readme.index("## Usage")]

    assert "install.sh" in section, "le chemin réel est de relancer l'installeur"
    if "uv tool upgrade" in section:
        assert "will not work" in section, (
            "si la commande est citée, il faut dire qu'elle ne s'applique pas"
        )
