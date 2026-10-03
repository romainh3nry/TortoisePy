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
