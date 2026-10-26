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
from typing import Iterable

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


def find_projects_in(
    workdirs: "Iterable[str] | None",
) -> tuple[Project, ...]:
    """Les dépôts contenus dans plusieurs dossiers de projets.

    Demandé par l'utilisateur : « possible de pouvoir ajouter
    plusieurs répertoires de projet ? » — des projets perso d'un côté,
    professionnels de l'autre, parfois un disque externe.

    **Les noms ne sont préfixés qu'en cas de collision** (choix de
    l'utilisateur). Mesuré avant d'écrire : deux dossiers contenant
    chacun un dépôt `api` donnaient deux entrées indiscernables, dans
    le menu comme dans `topy -s`. Préfixer systématiquement aurait
    rendu `vti` en `perso/vti` sans qu'aucune ambiguïté ne l'exige.

    Le tri est **global**, pas dossier par dossier : concaténer des
    listes déjà triées ferait repartir l'ordre de zéro à chaque
    dossier, et le menu paraîtrait désordonné.

    Un dossier illisible n'en prive pas des autres — c'est la raison
    d'être d'en avoir plusieurs : si un disque tombe, le reste
    fonctionne.
    """
    if not workdirs:
        return ()

    trouves: list[Project] = []
    vus: set[str] = set()
    for workdir in workdirs:
        for projet in find_projects(workdir):
            # Le même dépôt peut venir de deux dossiers configurés :
            # le même ajouté deux fois, ou un dossier et son parent
            # (`~/Projects` puis `~/Projects/clients`). Le lister
            # deux fois créerait une « collision » du dépôt avec
            # lui-même, et donc un préfixe absurde.
            if projet.path in vus:
                continue
            vus.add(projet.path)
            trouves.append(
                Project(name=projet.name, path=projet.path)
            )

    trouves = _lever_les_ambiguites(trouves, workdirs)
    return tuple(sorted(trouves, key=lambda projet: projet.name.lower()))


def _lever_les_ambiguites(
    projets: list[Project], workdirs: "Iterable[str]"
) -> list[Project]:
    """Préfixe du nom de son dossier chaque projet homonyme d'un autre.

    Seuls les noms en double sont touchés : leurs voisins gardent
    leur libellé court. Le piège de la correction serait de préfixer
    tout un dossier dès qu'une seule collision s'y produit.
    """
    comptes: dict[str, int] = {}
    for projet in projets:
        comptes[projet.name] = comptes.get(projet.name, 0) + 1

    # Pas de raccourci « aucune collision -> on rend tel quel » : la
    # boucle ci-dessous ne touche déjà que les noms dont le compte
    # dépasse 1. Vérifié par mutation — le retirer ne changeait
    # strictement rien, donc c'était du code qu'aucun test ne pouvait
    # justifier.
    racines = [Path(w) for w in workdirs]
    leves: list[Project] = []
    for projet in projets:
        if comptes[projet.name] == 1:
            leves.append(projet)
            continue
        leves.append(
            Project(
                name=f"{_dossier_de(projet, racines)}/{projet.name}",
                path=projet.path,
            )
        )
    return leves


def _dossier_de(projet: Project, racines: list[Path]) -> str:
    """Le nom du dossier de projets d'où vient `projet`.

    Une seule racine configurée peut le contenir : les doublons ont
    été écartés en amont, et deux racines imbriquées donneraient le
    même dépôt deux fois. Départager par longueur de chemin serait du
    code qu'aucun scénario n'atteint — vérifié par mutation, `max` et
    `min` rendent le même résultat sur tous les cas réels.
    """
    chemin = Path(projet.path)
    for racine in racines:
        try:
            chemin.relative_to(racine)
        except ValueError:
            continue
        return racine.name
    # Hors de toute racine connue : son dossier parent reste la
    # meilleure information disponible.
    return chemin.parent.name


def search_projects(
    projects: tuple[Project, ...], keyword: str
) -> tuple[Project, ...]:
    """Les projets dont le nom contient `keyword`, casse ignorée.

    Demandé par l'utilisateur : `topy -s vti` cherche un dépôt par
    mot-clé plutôt que par chemin. Taper le nom entier n'aurait pas
    d'intérêt — mesuré sur son dossier réel, les noms font 15,3
    caractères en moyenne, et « crm » suffit à ramener 5 projets sur
    61.

    La casse est ignorée : exiger `CRM-Signature` exactement
    transformerait un raccourci en devinette.

    Un motif vide rend un tuple vide plutôt que TOUT : `topy -s` sans
    argument afficherait sinon 61 lignes, illisibles dans un
    terminal. C'est à l'appelant de le refuser avec un message.
    """
    motif = keyword.strip().lower()
    if not motif:
        return ()

    return tuple(
        projet for projet in projects if motif in projet.name.lower()
    )
