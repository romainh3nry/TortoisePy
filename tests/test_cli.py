import os
import subprocess
from pathlib import Path

import pytest

from tortoisepy.cli import find_repository


def run_git(path, *args):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
    }
    return subprocess.run(
        ["git", *args], cwd=path, env=env, capture_output=True, text=True
    )


@pytest.fixture
def repo_path(tmp_path):
    path = tmp_path / "cli"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "master")
    (path / "f.txt").write_text("base\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "base")
    return path


def test_finds_a_repository_at_its_root(repo_path):
    assert find_repository(str(repo_path)) is not None


def test_finds_a_repository_from_a_subdirectory(repo_path):
    """§8 : la commande marche depuis n'importe quel sous-dossier."""
    nested = repo_path / "src" / "deep"
    nested.mkdir(parents=True)
    assert find_repository(str(nested)) is not None


def test_returns_none_outside_a_repository(tmp_path):
    """Vérifié : discover_repository retourne None, elle ne lève pas."""
    outside = tmp_path / "rien"
    outside.mkdir()
    assert find_repository(str(outside)) is None


def test_returns_none_for_a_missing_path(tmp_path):
    assert find_repository(str(tmp_path / "inexistant")) is None


def test_finding_a_repository_writes_nothing(repo_path):
    """§7.0 : même la découverte ne touche pas au dépôt."""
    import hashlib

    def fingerprint():
        digest = hashlib.sha256()
        for path in sorted((repo_path / ".git").rglob("*")):
            if path.is_file():
                stat = path.stat()
                digest.update(f"{path}:{stat.st_mtime_ns}".encode())
        return digest.hexdigest()

    before = fingerprint()
    find_repository(str(repo_path))
    assert fingerprint() == before


def test_the_icon_is_available(qtbot):
    """Sans icône, macOS affiche la fusée de l'interpréteur Python."""
    from tortoisepy.cli import application_icon

    icon = application_icon()
    assert icon.isNull() is False


def test_the_icon_ships_several_sizes(qtbot):
    """Un rendu dédié en 16 px reste net là où une réduction baverait."""
    from tortoisepy.cli import application_icon

    tailles = sorted(size.width() for size in application_icon().availableSizes())
    assert 16 in tailles
    assert 512 in tailles


def test_the_icon_files_travel_with_the_package():
    """Sans `package-data`, les PNG ne sont pas installés chez les autres
    utilisateurs et l'icône retombe sur celle de Python."""
    import tomllib
    from pathlib import Path

    racine = Path(__file__).resolve().parents[1]
    config = tomllib.loads((racine / "pyproject.toml").read_text())
    donnees = config["tool"]["setuptools"]["package-data"]["tortoisepy"]
    assert any("resources" in motif for motif in donnees)

    ressources = racine / "src" / "tortoisepy" / "resources"
    assert list(ressources.glob("icon-*.png")), "les PNG doivent exister"


def test_the_icon_is_roughly_square(qtbot):
    """Une icône non carrée est déformée par le système."""
    from PySide6.QtGui import QImage

    from tortoisepy import cli

    chemin = Path(cli.__file__).parent / "resources" / "icon-256.png"
    image = QImage(str(chemin))
    assert image.width() == image.height() == 256


def test_the_icon_drops_the_wordmark(qtbot):
    """Le mot « tortoisePy » est retiré des icônes.

    Sous 64 px il devient illisible et brouille la silhouette. Le bas de
    l'icône doit donc être bien plus vide que sa moitié haute, où se
    trouve le dessin — un logo complet remplirait les deux.
    """
    from PySide6.QtGui import QImage

    from tortoisepy import cli

    chemin = Path(cli.__file__).parent / "resources" / "icon-256.png"
    image = QImage(str(chemin))

    def sombres(debut: int, fin: int) -> float:
        """Part de pixels sombres : le texte est bleu marine.

        On ne peut pas compter le « non blanc » : depuis l'ajout du fond
        arrondi, celui-ci compte aussi et noie la mesure (56 % au lieu
        de 14 %). Seule la teinte du texte le distingue du fond clair.
        """
        marques = 0
        total = 0
        for y in range(debut, fin, 2):
            for x in range(0, image.width(), 2):
                couleur = image.pixelColor(x, y)
                total += 1
                if (
                    couleur.alpha() > 20
                    and couleur.red() < 150
                    and couleur.green() < 150
                ):
                    marques += 1
        return marques / max(total, 1)

    # Bande où le mot atterrirait si le logo complet était remis à
    # l'échelle. Une première version regardait 215-256, vide dans les
    # deux cas — le test ne détectait alors rien.
    bas = sombres(190, 240)

    assert sombres(60, 170) > 0.05, (
        "le dessin doit occuper le corps de l'icône"
    )
    assert bas < 0.04, (
        f"{bas:.1%} de pixels sombres en bas : le mot « tortoisePy » "
        "a-t-il été réintroduit ? (0 % attendu sans lui)"
    )


def test_the_icon_has_rounded_corners(qtbot):
    """macOS attend un carré arrondi, pas une image carrée.

    Sans cela l'icône tranche avec ses voisines dans le Dock — signalé
    par l'utilisateur, capture à l'appui.
    """
    from PySide6.QtGui import QImage

    from tortoisepy import cli

    chemin = Path(cli.__file__).parent / "resources" / "icon-512.png"
    image = QImage(str(chemin))
    n = image.width()

    for x, y in ((6, 6), (n - 6, 6), (6, n - 6), (n - 6, n - 6)):
        assert image.pixelColor(x, y).alpha() == 0, (
            "les coins doivent être transparents : sans arrondi, "
            "l'icône apparaît comme un carré plein"
        )


def test_the_icon_respects_the_macos_margin(qtbot):
    """Mesuré sur une icône système : ~9,4 % de marge.

    Trop peu, l'icône paraît plus grande que ses voisines ; trop, plus
    petite.
    """
    from PySide6.QtGui import QImage

    from tortoisepy import cli

    chemin = Path(cli.__file__).parent / "resources" / "icon-512.png"
    image = QImage(str(chemin))

    marge = next(
        y
        for y in range(image.height())
        if any(
            image.pixelColor(x, y).alpha() > 40
            for x in range(0, image.width(), 4)
        )
    )
    proportion = marge / image.height()
    assert 0.06 <= proportion <= 0.14, (
        f"marge de {proportion:.1%} : hors de la grille macOS (~10 %)"
    )


def test_the_icon_has_no_white_box(qtbot):
    """Le logo source est sur fond blanc ; ce fond doit disparaître.

    Sinon le Dock affiche un carré blanc au lieu de la silhouette —
    mesuré à 38 % de l'image avant correction.
    """
    from PySide6.QtGui import QImage

    from tortoisepy import cli

    chemin = Path(cli.__file__).parent / "resources" / "icon-512.png"
    image = QImage(str(chemin))

    blancs = 0
    total = 0
    for y in range(0, image.height(), 4):
        for x in range(0, image.width(), 4):
            couleur = image.pixelColor(x, y)
            total += 1
            if (
                couleur.alpha() > 200
                and couleur.red() > 245
                and couleur.green() > 245
                and couleur.blue() > 245
            ):
                blancs += 1

    part = blancs / max(total, 1)
    assert part < 0.12, (
        f"{part:.0%} de blanc opaque : le fond du logo est-il revenu ? "
        "(38 % avant correction, 4 % après)"
    )


def test_help_does_not_look_for_a_repository(capsys):
    """Vérifié avant correction : `--help` était pris pour un chemin.

    « Pas de dépôt Git trouvé dans --help » — c'est pourtant la première
    chose que tape quelqu'un qui découvre l'outil.
    """
    from tortoisepy.cli import main

    assert main(["--help"]) == 0
    sortie = capsys.readouterr().out
    assert "topy" in sortie
    assert "Pas de dépôt" not in sortie


def test_an_unknown_option_is_refused(capsys):
    """`topy --verison` ne doit pas chercher un dépôt nommé « --verison »."""
    from tortoisepy.cli import main

    assert main(["--verison"]) == 1
    erreur = capsys.readouterr().err
    assert "--verison" in erreur
    # Sans cette assertion, le test passait déjà — mais parce que l'outil
    # cherchait un *dépôt* nommé « --verison », pas parce qu'il refusait
    # l'option. Le message doit dire de quoi il s'agit.
    assert "Pas de dépôt" not in erreur
    assert "ption" in erreur, "le message doit parler d'une option"


def test_version_still_works(capsys):
    """Le refus des options inconnues ne doit pas manger les options vraies."""
    from tortoisepy.cli import main

    assert main(["--version"]) == 0
    assert "tortoisePy" in capsys.readouterr().out


def test_the_entry_point_is_named_topy():
    """Le renommage ne doit pas se perdre dans une fusion."""
    import tomllib

    racine = Path(__file__).resolve().parent.parent
    config = tomllib.loads((racine / "pyproject.toml").read_text())
    scripts = config["project"]["scripts"]

    assert "topy" in scripts
    assert scripts["topy"] == "tortoisepy.cli:main"
    assert "tgraph" not in scripts, "l'ancien nom ne doit pas subsister"
