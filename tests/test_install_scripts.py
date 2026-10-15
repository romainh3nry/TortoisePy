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


def test_the_scripts_install_a_pinned_tag():
    """Ce que le script INSTALLE reste épinglé, et suit le paquet.

    C'est la moitié du contrat que le changement d'URL ne doit pas
    emporter. Un script servi depuis `main` qui installerait aussi
    `main` livrerait du code non publié à quiconque lance la commande —
    et `topy --version` annoncerait une version qui n'existe pas.
    """
    import tomllib

    config = tomllib.loads((RACINE / "pyproject.toml").read_text())
    attendu = {f"v{config['project']['version']}"}

    for nom in SCRIPTS:
        contenu = (RACINE / "scripts" / nom).read_text()
        declarees = set(
            re.findall(r'(?:VERSION|\$Version)\s*=\s*"(v[\d.]+)"', contenu)
        )
        assert declarees, f"{nom} n'épingle aucune version"
        assert declarees == attendu, (
            f"{nom} installe {declarees}, le paquet est en {attendu}"
        )
        assert "TortoisePy@" in contenu, (
            f"{nom} doit viser une référence explicite, pas la branche "
            "par défaut"
        )


def test_the_readme_install_command_matches_the_package():
    """Le README cite `uv tool install …@vX.Y.Z` : il doit suivre.

    Cette commande-là garde son tag — c'est l'installation manuelle,
    où l'on veut savoir ce qu'on pose.
    """
    import tomllib

    config = tomllib.loads((RACINE / "pyproject.toml").read_text())
    version = config["project"]["version"]

    readme = (RACINE / "README.md").read_text()
    tags = set(re.findall(r"TortoisePy@v([\d.]+)", readme))
    assert tags == {version}, f"README annonce {tags}, le paquet est en {version}"


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
        f"`topy --version` dit {__version__}, le paquet est en {declaree}"
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


# --- La version se change à un seul endroit ------------------------------


def _charger_set_version(racine=None):
    """Charge `scripts/set-version.py`, dont le tiret interdit l'import."""
    import importlib.util

    base = racine or RACINE
    spec = importlib.util.spec_from_file_location(
        "set_version", base / "scripts" / "set-version.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if racine is not None:
        module.RACINE = racine
    return module


def test_the_version_script_reports_the_current_version():
    """`set-version.py` sans argument lit la source unique."""
    import tomllib

    module = _charger_set_version()
    config = tomllib.loads((RACINE / "pyproject.toml").read_text())
    assert module.version_courante() == config["project"]["version"]


def test_the_version_script_covers_every_file_that_holds_it(tmp_path):
    """Le test qui compte : aucun fichier ne doit être oublié.

    Sans lui, ajouter demain une version dans un nouveau fichier sans
    l'ajouter au script recréerait exactement le problème que le script
    existe pour supprimer — et personne ne le verrait avant une release
    incohérente.

    On travaille sur une COPIE : le dépôt réel n'est jamais modifié.
    """
    import shutil

    fichiers = ("pyproject.toml", "README.md",
                "scripts/install.sh", "scripts/install.ps1")

    racine_copie = tmp_path / "depot"
    (racine_copie / "scripts").mkdir(parents=True)
    for nom in fichiers:
        shutil.copy2(RACINE / nom, racine_copie / nom)
    shutil.copy2(
        RACINE / "scripts" / "set-version.py",
        racine_copie / "scripts" / "set-version.py",
    )

    module = _charger_set_version(racine_copie)

    ancienne = module.version_courante()
    module.poser("7.8.9")

    for nom in fichiers:
        contenu = (racine_copie / nom).read_text()
        assert ancienne not in contenu, (
            f"{nom} porte encore {ancienne} : le script l'a oublié"
        )
        assert "7.8.9" in contenu, f"{nom} n'a pas reçu la nouvelle version"


def test_a_version_bump_leaves_the_download_urls_alone(tmp_path):
    """Monter de version ne doit pas reversionner les URL de `main`.

    `set-version.py` remplace tout `vX.Y.Z` par expression régulière.
    Le jour où quelqu'un élargit ce motif, les URL repasseraient en
    `…/v1.2.3/scripts/…` sans que rien ne le dise — et la corvée que ce
    changement supprime reviendrait en silence.

    On travaille sur une COPIE : le dépôt réel n'est jamais modifié.
    """
    import shutil

    fichiers = ("pyproject.toml", "README.md",
                "scripts/install.sh", "scripts/install.ps1")

    racine = tmp_path / "depot"
    (racine / "scripts").mkdir(parents=True)
    for nom in fichiers:
        shutil.copy2(RACINE / nom, racine / nom)
    shutil.copy2(
        RACINE / "scripts" / "set-version.py",
        racine / "scripts" / "set-version.py",
    )

    _charger_set_version(racine).poser("9.9.9")

    for nom in fichiers:
        contenu = (racine / nom).read_text()
        assert not re.search(r"TortoisePy/v[\d.]+/scripts/", contenu), (
            f"{nom} : une URL de téléchargement a été reversionnée"
        )

    readme = (racine / "README.md").read_text()
    assert "TortoisePy/main/scripts/install.sh" in readme
    # Et la référence installée, elle, a bien suivi.
    assert "TortoisePy@v9.9.9" in readme


def test_every_version_in_the_repository_is_reachable_by_the_script():
    """Aucune version codée en dur hors des fichiers que le script couvre.

    Garde-fou contre un futur fichier qui épinglerait la version sans être
    déclaré dans `set-version.py`.
    """
    import tomllib

    config = tomllib.loads((RACINE / "pyproject.toml").read_text())
    version = config["project"]["version"]

    couverts = {
        RACINE / "pyproject.toml",
        RACINE / "README.md",
        RACINE / "scripts" / "install.sh",
        RACINE / "scripts" / "install.ps1",
    }

    oublies = []
    for chemin in RACINE.rglob("*"):
        if not chemin.is_file() or chemin in couverts:
            continue
        if any(part in {".git", ".venv", ".superpowers", "__pycache__",
                        "docs"} for part in chemin.parts):
            continue
        if chemin.suffix not in {".toml", ".md", ".sh", ".ps1", ".cfg"}:
            continue
        if version in chemin.read_text(errors="ignore"):
            oublies.append(str(chemin.relative_to(RACINE)))

    assert not oublies, (
        "ces fichiers épinglent la version sans être couverts par "
        f"scripts/set-version.py : {oublies}"
    )


# --- Le venv de développement suit la version ---------------------------


def test_the_script_refreshes_the_local_venv(tmp_path, monkeypatch):
    """Demandé par l'utilisateur après l'avoir fait à la main deux fois.

    Un venv en mode éditable pointe sur le code source — les
    modifications sont immédiates — mais sa VERSION est figée à
    l'installation. Changer `pyproject.toml` ne la met pas à jour, d'où
    l'écart que `test_the_reported_version_follows_the_package` signale.
    """
    import shutil

    module = _charger_set_version()

    racine = tmp_path / "projet"
    (racine / "scripts").mkdir(parents=True)
    (racine / ".venv" / "bin").mkdir(parents=True)
    (racine / ".venv" / "bin" / "python").write_text("")
    for nom in ("pyproject.toml", "README.md",
                "scripts/install.sh", "scripts/install.ps1"):
        shutil.copy2(RACINE / nom, racine / nom)

    module.RACINE = racine

    lances = []
    monkeypatch.setattr(
        module.subprocess, "run",
        lambda commande, **kw: lances.append(commande) or _Termine(),
    )

    module.rafraichir_venv()

    assert lances, "aucune réinstallation lancée"
    commande = lances[0]
    assert str(racine / ".venv" / "bin" / "python") in commande[0]
    assert "install" in commande and "-e" in commande
    assert "--no-deps" in commande, (
        "sans --no-deps, PySide6 et pygit2 seraient réexaminés pour rien"
    )


class _Termine:
    returncode = 0
    stdout = ""
    stderr = ""


def test_no_venv_is_not_an_error(tmp_path, monkeypatch):
    """Sur une machine sans venv, le script doit continuer sans broncher.

    Changer la version et réinstaller sont deux choses : échouer sur la
    seconde priverait de la première.
    """
    module = _charger_set_version()
    module.RACINE = tmp_path          # aucun .venv ici

    lances = []
    monkeypatch.setattr(
        module.subprocess, "run",
        lambda commande, **kw: lances.append(commande) or _Termine(),
    )

    module.rafraichir_venv()          # ne doit pas lever
    assert lances == [], "une réinstallation a été tentée sans venv"


def test_setting_a_version_also_refreshes(tmp_path, monkeypatch):
    """Le bout de la chaîne : poser une version rafraîchit le venv."""
    import shutil

    module = _charger_set_version()
    racine = tmp_path / "projet"
    (racine / "scripts").mkdir(parents=True)
    for nom in ("pyproject.toml", "README.md",
                "scripts/install.sh", "scripts/install.ps1"):
        shutil.copy2(RACINE / nom, racine / nom)
    module.RACINE = racine

    appels = []
    monkeypatch.setattr(module, "rafraichir_venv", lambda: appels.append(1))

    module.main(["9.8.7"])
    assert appels == [1], "le venv n'a pas été rafraîchi"
