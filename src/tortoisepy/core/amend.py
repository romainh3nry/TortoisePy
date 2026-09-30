"""Corriger le dernier commit — phase 12.

Amender réécrit le commit : son identifiant change. S'il était poussé,
la branche diverge et le push normal est rejeté. **C'est le force-push
de la phase 10 qui rend ce geste praticable** ; sans lui, amender aurait
mené à une impasse.
"""

from __future__ import annotations

import pygit2

from tortoisepy.core.operations import _build_tree, _signature
from tortoisepy.core.results import OperationResult, failed, guarded, succeeded


def last_commit_message(repo: pygit2.Repository) -> str:
    """Message du dernier commit, ou chaîne vide s'il n'y en a pas."""
    if repo.head_is_unborn:
        return ""
    try:
        return repo.head.peel(pygit2.Commit).message
    except (pygit2.GitError, KeyError):
        return ""


def can_amend(repo: pygit2.Repository) -> str | None:
    """`None` si l'on peut amender, sinon la raison de ne pas pouvoir.

    Rendre la raison plutôt qu'un booléen : l'interface l'affiche en
    infobulle, et « grisé sans explication » n'apprend rien.
    """
    if repo.head_is_unborn:
        return "nothing to amend yet"

    if repo.head_is_detached:
        # **Vérifié** : libgit2 accepte l'amend sur une HEAD détachée, et
        # le commit produit n'est suivi par aucune branche — invisible
        # dans le graphe, récupérable seulement par le reflog. C'est le
        # seul cas où amender fait vraiment perdre du travail.
        return "cannot amend on a detached HEAD"

    if repo.state() != pygit2.enums.RepositoryState.NONE:
        return "an operation is already in progress"

    return None


@guarded("Amend")
def amend_commit(
    repo: pygit2.Repository, paths: tuple[str, ...], message: str
) -> OperationResult:
    """Réécrit le dernier commit : message, et fichiers ajoutés.

    L'auteur d'origine est conservé — on ne passe pas `author=` — car
    amender n'est pas se réapproprier le travail de quelqu'un d'autre.
    """
    raison = can_amend(repo)
    if raison is not None:
        return failed("Amend", raison, repository_changed=False)

    text = message.strip()
    if not text:
        return failed("Amend", "empty commit message", repository_changed=False)

    commit = repo.head.peel(pygit2.Commit)

    tree = commit.tree.id
    selected = tuple(p for p in paths if p)
    if selected:
        # Partir de l'arbre du commit amendé, et non de HEAD : ce sont les
        # mêmes ici, mais le dire évite une surprise si cela changeait.
        construit = _build_tree(repo, selected, base=commit.tree, etiquette="Amend")
        if isinstance(construit, OperationResult):
            return construit
        tree = construit

    oid = repo.amend_commit(
        commit,
        "HEAD",
        committer=_signature(repo),
        message=text + ("\n" if not text.endswith("\n") else ""),
        tree=tree,
    )
    return succeeded(f"Amended {str(oid)[:8]}")
