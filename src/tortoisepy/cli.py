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
  topy -s MOT          Cherche un dépôt par mot-clé et propose une liste
  topy --wait          Garde le terminal occupé jusqu'à la fermeture
  topy --version       Affiche la version
  topy --install-icon  Installe l'icône système (macOS)
  topy --help          Affiche ce message

Exemples:
  topy .                     depuis un projet
  topy ~/code/mon-projet     un dépôt ailleurs
  topy -s vti                cherche « vti » dans le dossier de projets

Comme git, topy remonte l'arborescence : lancé depuis projet/src/, il
ouvre projet/.

topy rend la main au terminal aussitôt la fenêtre ouverte. Utilisez
`--wait` pour l'enchaîner dans un script.
"""


def _workdir_memorise() -> str:
    """Le dossier de projets choisi depuis « Open Project ».

    Lu ici plutôt que passé en argument : c'est le même réglage que
    l'interface, et en avoir deux les ferait diverger.

    L'import de Qt est LOCAL : `topy --version` ne doit pas payer le
    chargement de PySide6, et `QSettings` en fait partie.
    """
    try:
        from tortoisepy.ui.settings_store import SettingsStore

        return str(SettingsStore().value("view/workdir") or "")
    except Exception:
        # Réglages illisibles : la recherche échouera avec son propre
        # message, ce qui vaut mieux qu'une trace d'exécution.
        return ""


def _choisir(projets) -> str | None:
    """Affiche la liste numérotée et lit le choix. `None` si annulé.

    Numérotée et non à curseur : `curses` est absent de CPython sous
    Windows, et un menu plein écran ne fonctionne pas dans un tube —
    il aurait fallu écrire les deux (décidé avec l'utilisateur).

    Mesuré sur son dossier réel : les recherches rendent 1 à 5
    résultats. Taper « 4 » est plus rapide que quatre flèches.
    """
    for rang, projet in enumerate(projets, start=1):
        print(f"  {rang}. {projet.name}")
    print()

    try:
        reponse = input("Projet (numéro, ou Entrée pour annuler) : ")
    except (KeyboardInterrupt, EOFError):
        # Annulation volontaire : une trace d'exécution ici serait
        # effrayante pour un geste normal.
        print(file=sys.stderr)
        return None

    reponse = reponse.strip()
    if not reponse:
        return None

    try:
        rang = int(reponse)
    except ValueError:
        print(f"« {reponse} » n'est pas un numéro.", file=sys.stderr)
        return None

    if not 1 <= rang <= len(projets):
        print(
            f"Il n'y a pas de projet {rang} dans cette liste.",
            file=sys.stderr,
        )
        return None

    return projets[rang - 1].path


def _rechercher(motif: str) -> str | None:
    """Le chemin du projet choisi, ou `None` si rien n'aboutit.

    Demandé par l'utilisateur : « topy -s vti ».
    """
    from tortoisepy.core.projects import find_projects, search_projects

    workdir = _workdir_memorise()
    if not workdir:
        print(
            "Aucun dossier de projets choisi.\n"
            "Ouvrez-en un depuis « Open Project » dans l'application.",
            file=sys.stderr,
        )
        return None

    trouves = search_projects(find_projects(workdir), motif)

    if not trouves:
        print(
            f"Aucun projet ne correspond à « {motif} » dans {workdir}",
            file=sys.stderr,
        )
        return None

    if len(trouves) == 1:
        # Un seul résultat : pas de question à poser. `topy -s vti`
        # sans frappe supplémentaire est le but de la fonctionnalité.
        return trouves[0].path

    return _choisir(trouves)


def _afficher(repository, arguments: list[str]) -> int:
    """Ouvre la fenêtre sur `repository`. Code de sortie du programme.

    Séparé de `main` depuis l'ajout de `-s` : la recherche aboutit au
    même affichage qu'un argument de chemin, et dupliquer ce bloc
    l'aurait fait diverger.
    """
    attendre = "--wait" in arguments


    # Le dépôt est validé AVANT de relancer : sinon l'erreur partirait
    # dans le processus détaché, dont les sorties vont vers le vide, et
    # l'utilisateur ne verrait rien du tout.
    if not attendre and _relancer_detache(arguments):
        return 0

    # Les imports Qt restent ici : `--version` et le message d'erreur
    # ci-dessus ne doivent pas payer le chargement de PySide6.
    from PySide6.QtWidgets import QApplication

    from tortoisepy.ui.main_window import MainWindow
    from tortoisepy.ui.splash import StartupSplash, should_show_splash

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

    # L'écran d'attente AVANT la construction : c'est elle qui coûte —
    # mesuré sur un dépôt de 935 nœuds, `build_graph` demande 1522 ms, et
    # `MainWindow` se construit d'un bloc. Pendant ce temps, rien ne
    # s'affichait et l'application paraissait ne pas démarrer.
    #
    # `processEvents` est indispensable : sans lui, l'écran est créé mais
    # jamais peint, puisque la boucle d'événements ne démarre qu'à
    # `app.exec()`, après la construction.
    ecran = None
    if should_show_splash(repository):
        from pathlib import Path

        ecran = StartupSplash(Path(repository.workdir or ".").name)
        ecran.show()
        app.processEvents()

    try:
        # `defer_graph` : le graphe se construit en arrière-plan, donc la
        # fenêtre paraît tout de suite et l'écran d'attente peut s'animer.
        # Mesuré sur un dépôt de 935 nœuds, `build_graph` coûte 1522 ms —
        # pendant lesquelles rien ne s'affichait.
        #
        # Seulement quand l'écran est montré : sur un petit dépôt, le
        # mode synchrone évite un aller-retour entre fils pour 17 ms.
        window = MainWindow(
            repository,
            on_progress=ecran.pump if ecran is not None else None,
            defer_graph=ecran is not None,
        )
    except Exception:
        # L'écran ne doit pas rester orphelin si la construction échoue.
        if ecran is not None:
            ecran.finish()
        raise

    window.show()

    if ecran is not None:
        # L'écran se retire quand le graphe est posé, pas avant : le
        # fermer ici laisserait une fenêtre vide le temps du calcul.
        window.graph_ready.connect(ecran.finish)

    return app.exec()


def _ouvrir(chemin: str, arguments: list[str]) -> int:
    """Ouvre le dépôt trouvé à `chemin`. Code de sortie du programme.

    Isolé de `main` depuis l'ajout de `-s` : les deux chemins — un
    argument de chemin, ou un projet choisi dans une liste —
    aboutissent ici, et les tests l'interceptent pour ne pas ouvrir
    de fenêtre.
    """
    repository = find_repository(chemin)
    if repository is None:
        print(f"Pas de dépôt Git trouvé dans {chemin}", file=sys.stderr)
        return 1

    return _afficher(repository, arguments)


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

    # `-s` AVANT le refus des options inconnues, qui rejetterait tout
    # ce qui commence par un tiret.
    if arguments and arguments[0] in ("-s", "--search"):
        if len(arguments) < 2 or not arguments[1].strip():
            # `topy -s` seul rendrait 61 lignes sur un dossier réel :
            # mieux vaut l'usage qu'un terminal noyé.
            print(
                f"« {arguments[0]} » attend un mot-clé.\n\n{_USAGE}",
                file=sys.stderr,
            )
            return 1

        trouve = _rechercher(arguments[1])
        if trouve is None:
            return 1
        # Les arguments passés à la relance ne portent plus `-s` : le
        # processus détaché reçoit un chemin, et ne doit pas refaire
        # la recherche ni redemander un choix.
        return _ouvrir(trouve, [trouve])

    # Une option inconnue n'est pas un chemin. Sans ce refus,
    # `topy --verison` cherchait un dépôt nommé « --verison » et
    # répondait « Pas de dépôt Git trouvé dans --verison » (vérifié) —
    # un message qui n'aide pas à corriger la faute de frappe.
    if arguments and arguments[0].startswith("-"):
        print(
            f"Option inconnue : {arguments[0]}\n\n{_USAGE}", file=sys.stderr
        )
        return 1

    return _ouvrir(arguments[0] if arguments else ".", arguments)

if __name__ == "__main__":
    raise SystemExit(main())
