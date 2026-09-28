"""Ce qui n'est pas encore sur le serveur — §5 de la spec phase 7.

Lecture seule, sans Qt : `ui/` décide comment le montrer.
"""

from __future__ import annotations

from dataclasses import dataclass

import pygit2

from tortoisepy.core.model import Oid
from tortoisepy.core.operations import _default_remote


@dataclass(frozen=True)
class PushState:
    """De quoi griser un bouton et l'expliquer."""

    branch: str | None = None
    remote_name: str | None = None
    unpushed_count: int = 0
    can_push: bool = False
    reason: str = ""
    """Pourquoi on ne peut pas pousser — vide quand on peut."""


def unpushed_oids(repo: pygit2.Repository) -> frozenset[Oid]:
    """Commits qu'aucune ref distante n'atteint — donc absents du serveur.

    C'est la réponse de `git log --not --remotes`, et c'est **toutes** les
    refs distantes qui comptent, pas seulement la branche de suivi de la
    branche courante.

    Corrigé le 2026-09-28 après un retour utilisateur sur le dépôt `xpc` :
    la branche courante `mcp` n'a pas d'upstream configuré, et la règle
    précédente — « pas d'upstream donc tout est à publier » — marquait ses
    1644 commits comme non poussés. Or ils sont tous sur le serveur, sous
    d'autres branches. Pire : les nœuds d'autres branches, `lightweight-calls`
    comprise, héritaient de la marque alors que leur tip local était
    **identique** à son tip distant. Vérifié après correction : 0 commit non
    poussé, ce que confirme `git log --not --remotes`.

    Sans remote, l'ensemble est vide : marquer tous les commits d'un dépôt
    purement local serait du bruit permanent, jamais une information.

    La marche cache les refs distantes plutôt que de construire deux
    ensembles complets : mesuré à 2 ms sur `xpc` (79 refs distantes).
    """
    if not list(repo.remotes.names()):
        return frozenset()

    tips = _local_tips(repo)
    if not tips:
        return frozenset()

    try:
        walker = repo.walk(tips[0])
        for tip in tips[1:]:
            walker.push(tip)
        for oid in _remote_tips(repo):
            walker.hide(oid)
        return frozenset(str(commit.id) for commit in walker)
    except (pygit2.GitError, KeyError):
        return frozenset()


def unpushed_on(repo: pygit2.Repository, branch) -> frozenset[Oid]:
    """Commits de cette branche qu'aucune ref distante n'atteint.

    Même définition que `unpushed_oids`, restreinte à une branche : c'est
    ce que le bouton Push enverrait réellement.
    """
    if not list(repo.remotes.names()):
        return frozenset()

    try:
        walker = repo.walk(branch.target)
        for oid in _remote_tips(repo):
            walker.hide(oid)
        return frozenset(str(commit.id) for commit in walker)
    except (pygit2.GitError, KeyError):
        return frozenset()


def _local_tips(repo: pygit2.Repository) -> list:
    """Sommets des branches locales.

    Toutes les branches, pas seulement la courante : le graphe affiche des
    nœuds pour chacune, et chacun doit porter une marque exacte.
    """
    tips = []
    for name in repo.branches.local:
        try:
            tips.append(repo.branches.local[name].target)
        except (KeyError, pygit2.GitError):
            continue
    return tips


def _remote_tips(repo: pygit2.Repository) -> list:
    """Sommets de toutes les refs distantes, tags distants inclus.

    Un commit atteint par n'importe laquelle est déjà sur le serveur.
    `peel` résout les refs symboliques comme `origin/HEAD`, qui sinon
    feraient lever la marche.
    """
    tips = []
    for name in repo.references:
        if not name.startswith("refs/remotes/"):
            continue
        try:
            tips.append(repo.references[name].peel(pygit2.Commit).id)
        except (KeyError, pygit2.GitError, ValueError, TypeError):
            continue
    return tips


def push_state(repo: pygit2.Repository) -> PushState:
    """État de poussée de la branche courante.

    Réutilise `_default_remote()` de operations.py pour que le remote nommé
    ici soit le même que celui où push_branch() pousse réellement. Évite un
    bogue où remotes[0] (ordre alphabétique) pourrait pointer vers un fork.
    """
    branch = _current_branch(repo)
    if branch is None:
        return PushState(reason="no branch checked out")

    branch_name = branch.branch_name
    remote_name = _default_remote(repo, branch_name)
    if remote_name is None:
        return PushState(branch=branch_name, reason="no remote configured")

    # Compté sur la seule branche courante : c'est elle que le bouton
    # pousse. `unpushed_oids` couvre toutes les branches locales, pour
    # marquer correctement chaque nœud du graphe — mais activer le bouton
    # sur des commits qu'il n'enverra pas serait mentir.
    count = len(unpushed_on(repo, branch))
    if count == 0:
        return PushState(
            branch=branch_name,
            remote_name=remote_name,
            reason="nothing to push",
        )

    return PushState(
        branch=branch_name,
        remote_name=remote_name,
        unpushed_count=count,
        can_push=True,
    )


def _current_branch(repo: pygit2.Repository):
    """Branche courante, ou `None` si HEAD est détachée ou non née.

    Vérifié : sur une HEAD détachée, `repo.branches[shorthand]` lève
    `KeyError` — d'où la garde explicite plutôt qu'un `try` autour de tout.
    """
    if repo.head_is_unborn or repo.head_is_detached:
        return None
    try:
        return repo.branches[repo.head.shorthand]
    except (KeyError, pygit2.GitError):
        return None
