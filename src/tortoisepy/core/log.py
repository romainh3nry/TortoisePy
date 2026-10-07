"""Journal de commits, par ref et/ou par chemin — `git log [ref] [-- path]`.

Deux questions auxquelles l'application ne savait pas répondre :

  - « quels commits porte cette branche ? » — `show_log` figurait au menu
    contextuel mais ne faisait **rien** (il rendait un succès vide) ;
  - « quand ce fichier a-t-il changé, et pourquoi ? » — aucun écran ne le
    disait, alors que c'est la question qu'on se pose juste avant un blâme.

**Lecture seule** (§7.0) : ni l'index, ni les refs, ni HEAD ne bougent.

Aucune dépendance à Qt : `ui/` appelle ces fonctions, jamais pygit2
directement.
"""

from __future__ import annotations

import pygit2

from tortoisepy.core.commits import CommitInfo, read_commit
from tortoisepy.core.model import Oid

DEFAULT_LIMIT = 100
"""Taille d'une page.

Le coût d'un journal filtré par chemin est linéaire en commits
**parcourus**, pas en commits trouvés : mesuré sur ce dépôt, 104 ms pour
70 commits, et un fichier peu touché paie le parcours complet pour une
poignée de résultats. Sur un dépôt de plusieurs milliers de commits, cela
se compte en secondes — d'où la pagination, et l'appel en arrière-plan
côté interface.
"""

PARCOURS_MAXIMUM = 50_000
"""Garde-fou : un historique pathologique ne doit pas tourner sans fin.

Sans cette borne, un chemin jamais versionné ferait parcourir l'intégralité
du dépôt avant de rendre une liste vide.
"""


def read_log(
    repo: pygit2.Repository,
    *,
    ref: str | None = None,
    path: str | None = None,
    limit: int = DEFAULT_LIMIT,
    after: Oid | None = None,
    until: Oid | None = None,
) -> tuple[CommitInfo, ...]:
    """Les commits de `ref`, du plus récent au plus vieux.

    `path` ne retient que ceux qui ont touché ce fichier, comme
    `git log -- <chemin>`. `after` reprend juste après ce commit : c'est
    le « Load more », qui évite autant la limite dure (qui mentirait sur
    l'historique) que le parcours complet (qui gèlerait l'interface).

    Rend un tuple vide plutôt que de lever si la ref est inconnue : une
    branche peut disparaître entre l'affichage du menu et le clic.
    """
    depart = _resoudre(repo, ref)
    if depart is None:
        return ()

    try:
        walker = repo.walk(depart, pygit2.GIT_SORT_TOPOLOGICAL)
    except (pygit2.GitError, ValueError, KeyError):
        return ()

    # `until` borne le parcours — « git log A..B » : les commits de B que
    # A n'a pas. La borne elle-même est exclue, comme git.
    #
    # Une borne introuvable est ignorée plutôt que de vider le journal :
    # rendre l'historique entier vaut mieux que de laisser croire qu'il
    # n'y a rien à voir.
    exclus: set[Oid] = set()
    if until is not None:
        exclus = _ancetres(repo, until)

    retenus: list[CommitInfo] = []
    # `after` est consommé pendant le parcours : on saute tout ce qui
    # précède, bornes comprises, puis on collecte.
    en_attente = after is not None
    parcourus = 0

    for commit in walker:
        parcourus += 1
        if parcourus > PARCOURS_MAXIMUM:
            break

        oid = str(commit.id)

        if en_attente:
            # On attend de PASSER `after`, sans l'inclure : il est la
            # dernière ligne de la page précédente.
            if oid == after:
                en_attente = False
            continue

        if oid in exclus:
            continue

        if path is not None and not _touche(commit, path):
            continue

        info = read_commit(repo, oid)
        if info is not None:
            retenus.append(info)
        if len(retenus) >= limit:
            break

    return tuple(retenus)


def _ancetres(repo: pygit2.Repository, borne: Oid) -> set[Oid]:
    """Tous les commits accessibles depuis `borne`, elle comprise.

    Parcourt plutôt que de comparer les dates : deux branches peuvent
    porter des horodatages trompeurs, et seule l'accessibilité dit ce
    qu'une révision « a déjà ».
    """
    depart = _resoudre(repo, borne)
    if depart is None:
        return set()

    try:
        return {
            str(commit.id)
            for commit in repo.walk(depart, pygit2.GIT_SORT_TOPOLOGICAL)
        }
    except (pygit2.GitError, ValueError, KeyError):
        return set()


def _resoudre(repo: pygit2.Repository, ref: str | None):
    """L'OID de départ du parcours. `None` si introuvable.

    Sans `ref`, on part de HEAD — le cas « journal du dépôt ».
    """
    if ref is None:
        try:
            return repo.head.target
        except (pygit2.GitError, KeyError):
            return None

    # `revparse_single` accepte aussi bien « master » que
    # « origin/master », un tag ou un OID brut.
    try:
        return repo.revparse_single(ref).peel(pygit2.Commit).id
    except (pygit2.GitError, ValueError, KeyError, TypeError):
        return None


def _touche(commit: pygit2.Commit, path: str) -> bool:
    """Ce commit modifie-t-il `path` par rapport à ses parents ?

    On compare l'**id du blob**, pas un diff : construire un diff par
    commit parcouru coûterait un ordre de grandeur de plus, pour une
    réponse identique sur un chemin unique.

    Deux cas que l'implémentation naïve perd :

      - un commit **racine** n'a pas de parent : le fichier qu'il
        introduit doit compter, sinon la création d'un fichier
        disparaîtrait du bas de son propre historique ;
      - une **création** donne `None` d'un côté : exiger la présence
        dans les deux arbres perdrait silencieusement ce commit.
    """
    ici = _blob(commit, path)
    parents = commit.parents

    if not parents:
        return ici is not None

    # Un merge ne compte que s'il diffère de TOUS ses parents : sinon il
    # réapparaîtrait pour chaque fichier déjà présent dans une branche
    # fusionnée, alors qu'il n'y a rien à y voir.
    return all(_blob(parent, path) != ici for parent in parents)


def _blob(commit: pygit2.Commit, path: str):
    """L'id du blob à `path` dans ce commit, ou `None` s'il est absent.

    `tree[path]` traverse les dossiers (« src/fichier.py »), là où un
    accès par entrée resterait à la racine.
    """
    try:
        return commit.tree[path].id
    except (KeyError, pygit2.GitError):
        return None
