"""Trouver les projets Git d'un dossier de travail.

Demandé par l'utilisateur : choisir un répertoire de projets une fois,
puis retrouver dans un menu déroulant tout ce qu'il contient.

Pourquoi un module à part plutôt que `find_repository` (dans `cli.py`) :
celle-ci repose sur `pygit2.discover_repository`, qui **remonte**
l'arborescence comme le fait Git. Appelée sur chaque sous-dossier d'un
workdir lui-même versionné, elle « trouverait » partout le dépôt parent,
et la liste serait entièrement fausse. Ici on regarde chaque dossier
LUI-MÊME, sans jamais remonter.

Aucun Qt, et pas même pygit2 : instancier un dépôt pourrait écrire un
fichier de verrou sur un dépôt abîmé, et §7.0 garantit que
l'application ne touche à rien sans action explicite. Lister reste une
lecture du disque.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROFONDEUR = 2
"""Niveaux explorés sous le dossier choisi.

Deux, pour couvrir les arborescences rangées par client
(`~/Projets/client/leur-projet`) sans parcourir des `node_modules`
entiers — ce qui rendrait le scan lent pour rien.
"""


@dataclass(frozen=True)
class Project:
    """Un dépôt trouvé : son nom pour le menu, son chemin pour l'ouvrir."""

    name: str
    path: str


def _est_un_depot(dossier: Path) -> bool:
    """`dossier` contient-il un `.git` ?

    Pas de `is_dir()` : un worktree ou un sous-module porte un
    **fichier** `.git` contenant `gitdir: …`. Les exclure écarterait de
    vrais dépôts que l'application sait ouvrir.
    """
    try:
        return (dossier / ".git").exists()
    except OSError:
        # Chemin illisible, lien cassé, disque débranché en cours de
        # route : ce dossier n'est pas listable, les autres le restent.
        return False


def _sous_dossiers(dossier: Path) -> list[Path]:
    """Les sous-dossiers visibles, ou rien si on ne peut pas lire.

    Une `PermissionError` au milieu du parcours priverait l'utilisateur
    de TOUS ses projets, pas seulement de celui-là.

    Les dossiers cachés sont écartés : `.cache` et `.Trash` ne sont pas
    des projets, et sans cette exclusion un workdir lui-même versionné
    se listerait comme un de ses propres enfants (son `.git`).
    """
    try:
        entrees = list(dossier.iterdir())
    except OSError:
        return []

    visibles = []
    for entree in entrees:
        if entree.name.startswith("."):
            continue
        try:
            if entree.is_dir():
                visibles.append(entree)
        except OSError:
            continue
    return visibles


def find_projects(workdir: str | None) -> tuple[Project, ...]:
    """Les dépôts Git contenus dans `workdir`, triés pour un menu.

    Rend un tuple vide plutôt que de lever quand le dossier manque :
    il peut être sur un disque externe débranché, et l'application doit
    pouvoir le dire à l'utilisateur, pas s'arrêter.
    """
    if not workdir:
        return ()

    racine = Path(workdir)
    try:
        if not racine.is_dir():
            return ()
    except OSError:
        return ()

    trouves: list[Project] = []
    _explorer(racine, racine, PROFONDEUR, trouves)

    # Tri insensible à la casse : l'ordre d'`iterdir` est celui du
    # système de fichiers, ni alphabétique ni stable d'une machine à
    # l'autre — illisible dans un menu.
    return tuple(sorted(trouves, key=lambda projet: projet.name.lower()))


def _explorer(
    dossier: Path, racine: Path, reste: int, trouves: list[Project]
) -> None:
    """Descend `reste` niveaux, en s'arrêtant à chaque dépôt trouvé.

    Un dépôt ne contient pas d'autres projets à lister : ses
    sous-modules et ses dossiers de dépendances n'ont rien à faire dans
    le menu, et les parcourir coûterait cher sur un gros projet.
    """
    if reste <= 0:
        return

    for enfant in _sous_dossiers(dossier):
        if _est_un_depot(enfant):
            trouves.append(Project(name=_nom(enfant, racine),
                                   path=str(enfant)))
            continue
        _explorer(enfant, racine, reste - 1, trouves)


def _nom(depot: Path, racine: Path) -> str:
    """Nom affiché : relatif à la racine, séparateurs normalisés.

    Deux projets `api` sous deux clients différents afficheraient le
    même libellé et rendraient le choix impossible ; le nom porte donc
    son dossier parent (`client-a/api`).

    Le séparateur est forcé à `/` même sous Windows : c'est un libellé
    de menu, pas un chemin à ouvrir — celui-ci vit dans `path`.
    """
    try:
        return depot.relative_to(racine).as_posix()
    except ValueError:
        return depot.name
