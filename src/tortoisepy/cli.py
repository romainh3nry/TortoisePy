"""Point d'entrée `tgraph` — §8.

    tgraph              # dépôt du dossier courant
    tgraph /chemin      # dépôt à ce chemin
"""

from __future__ import annotations

import os
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version as _version

import pygit2


def _lire_version() -> str:
    """Version du paquet installé, et non une copie codée en dur.

    Vérifié : `pyproject.toml` en 0.2.0 et cette constante restée à
    0.1.0 donnaient un `topy --version` qui mentait après une mise à
    jour. Une seule source de vérité — les métadonnées du paquet.

    Le repli sert au dépôt cloné sans installation (`uv run topy`), où
    aucune métadonnée n'existe.
    """
    try:
        return _version("tortoisepy")
    except PackageNotFoundError:
        return "0.0.0+dev"


__version__ = _lire_version()


def find_repository(start: str) -> pygit2.Repository | None:
    """Remonte l'arborescence comme le fait Git.

    Vérifié sur pygit2 1.20 : `discover_repository` RETOURNE `None` quand
    elle ne trouve rien, elle ne lève pas. Le `try/except` couvre les
    versions qui levaient, et les chemins illisibles.
    """
    try:
        path = pygit2.discover_repository(start)
    except (pygit2.GitError, KeyError, ValueError):
        return None

    if not path:
        return None

    try:
        return pygit2.Repository(path)
    except (pygit2.GitError, KeyError, ValueError):
        return None


def application_icon():
    """Icône de l'application, à toutes les tailles fournies.

    Sans elle, le système affiche l'icône de l'interpréteur Python — la
    fusée. Les fichiers sont livrés avec le paquet, donc l'icône est la
    même pour tout le monde, sans dépendre de l'installation.

    Windows préfère le `.ico`, qui contient déjà ses six tailles ; ailleurs
    on charge les PNG un par un. Dans les deux cas Qt prend la taille la
    plus proche du besoin, et un rendu dédié en 16 px reste net là où une
    réduction du 512 baverait.

    Note : sur Windows, cela suffit pour la fenêtre **et** la barre des
    tâches. Sur macOS, le Dock lit l'icône du bundle, pas celle-ci — voir
    `tortoisepy.desktop`, posé au premier lancement.
    """
    import sys
    from pathlib import Path

    from PySide6.QtGui import QIcon, QPixmap

    resources = Path(__file__).parent / "resources"

    if sys.platform.startswith("win"):
        windows_icon = resources / "tortoisepy.ico"
        if windows_icon.exists():
            return QIcon(str(windows_icon))

    icon = QIcon()
    for size in (512, 256, 128, 64, 48, 32, 16):
        chemin = resources / f"icon-{size}.png"
        if chemin.exists():
            icon.addPixmap(QPixmap(str(chemin)))
    return icon


_MARQUEUR_DETACHE = "TORTOISEPY_DETACHE"
"""Dit à l'enfant qu'il est déjà détaché.

Sans lui, chaque relance en relancerait une autre : une bombe à
fourche qui remplirait la machine de processus.
"""


def _options_de_detachement() -> dict:
    """Options `Popen` qui coupent l'enfant du terminal.

    Aucun mécanisme n'est portable : `DETACHED_PROCESS` n'existe que sur
    Windows, `start_new_session` que sur POSIX. `os.fork` n'est pas une
    option — il est **absent de Windows** (vérifié).
    """
    if sys.platform == "win32":
        return {
            "creationflags": (
                subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NEW_PROCESS_GROUP
            )
        }
    return {"start_new_session": True}


def _relancer_detache(arguments: list[str]) -> bool:
    """Relance `topy` détaché du terminal. `True` si la relance a eu lieu.

    Mesuré : le shell reprend la main en 0,07 s au lieu d'attendre la
    fermeture de la fenêtre.

    Les trois flux vont vers le vide — c'est le comportement d'une
    application de bureau, et écrire dans un terminal qui a disparu
    lèverait une erreur que plus personne ne lirait.

    En cas d'échec, on rend `False` : l'appelant ouvre alors la fenêtre
    normalement. Mieux vaut un shell bloqué qu'une application qui refuse
    de démarrer.
    """
    if os.environ.get(_MARQUEUR_DETACHE) == "1":
        return False

    try:
        subprocess.Popen(
            [sys.executable, "-m", "tortoisepy.cli", *arguments],
            env={**os.environ, _MARQUEUR_DETACHE: "1"},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **_options_de_detachement(),
        )
    except OSError:
        return False

    return True


_USAGE = """topy — TortoiseGit Revision Graph

Usage:
  topy [CHEMIN]        Ouvre le dépôt (défaut : le répertoire courant)
  topy --wait          Garde le terminal occupé jusqu'à la fermeture
  topy --version       Affiche la version
  topy --install-icon  Installe l'icône système (macOS)
  topy --help          Affiche ce message

Exemples:
  topy .                     depuis un projet
  topy ~/code/mon-projet     un dépôt ailleurs

Comme git, topy remonte l'arborescence : lancé depuis projet/src/, il
ouvre projet/.

topy rend la main au terminal aussitôt la fenêtre ouverte. Utilisez
`--wait` pour l'enchaîner dans un script.
"""


def main(argv: list[str] | None = None) -> int:
    """Ouvre la fenêtre sur le dépôt demandé."""
    arguments = list(sys.argv[1:] if argv is None else argv)

    # `--wait` est retiré AVANT le contrôle des options inconnues, qui
    # le rejetterait sinon. Il garde le terminal occupé, pour enchaîner
    # dans un script.
    attendre = "--wait" in arguments
    if attendre:
        arguments = [a for a in arguments if a != "--wait"]

    if arguments and arguments[0] in ("--help", "-h"):
        print(_USAGE)
        return 0

    if arguments and arguments[0] in ("--version", "-V"):
        print(f"tortoisePy {__version__}")
        return 0

    if arguments and arguments[0] == "--install-icon":
        from tortoisepy.desktop import install_bundle

        bundle = install_bundle()
        if bundle is None:
            print(
                "Icône système non installée : "
                "réservée à macOS, et l'icône doit être présente.",
                file=sys.stderr,
            )
            return 1
        print(f"Icône installée : {bundle}")
        return 0

    # Une option inconnue n'est pas un chemin. Sans ce refus,
    # `topy --verison` cherchait un dépôt nommé « --verison » et
    # répondait « Pas de dépôt Git trouvé dans --verison » (vérifié) —
    # un message qui n'aide pas à corriger la faute de frappe.
    if arguments and arguments[0].startswith("-"):
        print(
            f"Option inconnue : {arguments[0]}\n\n{_USAGE}", file=sys.stderr
        )
        return 1

    target = arguments[0] if arguments else "."

    repository = find_repository(target)
    if repository is None:
        print(f"Pas de dépôt Git trouvé dans {target}", file=sys.stderr)
        return 1

    # Le dépôt est validé AVANT de relancer : sinon l'erreur partirait
    # dans le processus détaché, dont les sorties vont vers le vide, et
    # l'utilisateur ne verrait rien du tout.
    if not attendre and _relancer_detache(arguments):
        return 0

    # Les imports Qt restent ici : `--version` et le message d'erreur
    # ci-dessus ne doivent pas payer le chargement de PySide6.
    from PySide6.QtWidgets import QApplication

    from tortoisepy.ui.main_window import MainWindow

    # Le nom affiché vient de `argv[0]`, lu par Qt **à la construction**
    # de la QApplication : appelé après, `setApplicationName` ne change
    # plus l'infobulle du Dock ni le menu de l'application. Lancé via
    # `python -c`, `argv[0]` vaut « -c » et macOS affichait « Python »
    # (signalé par l'utilisateur, capture à l'appui).
    app = QApplication(["tortoisePy"])
    app.setApplicationName("tortoisePy")
    app.setApplicationDisplayName("tortoisePy")
    app.setOrganizationName("tortoisePy")
    app.setWindowIcon(application_icon())

    # Le Dock de macOS lit l'icône du bundle, pas celle de la fenêtre :
    # sans lui, tortoisePy y apparaît sous les traits de l'interpréteur
    # Python. On le pose au premier lancement, puis plus jamais.
    from tortoisepy.desktop import install_if_missing

    install_if_missing()

    window = MainWindow(repository)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
