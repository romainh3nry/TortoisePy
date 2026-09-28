"""Collecte et typage des refs Git. Voir §6.1 étape 1."""

from __future__ import annotations

from collections import defaultdict

import pygit2

from tortoisepy.core.model import Oid, Ref, RefType


def _peel_to_commit(repo: pygit2.Repository, ref) -> Oid | None:
    """Résout une ref vers l'OID de son commit.

    Deux indirections possibles :

    - Une ref **symbolique** pointe vers une autre ref, pas vers un objet :
      `ref.target` est alors une chaîne comme `refs/remotes/origin/master`.
      `refs/remotes/origin/HEAD` est dans ce cas dans presque tout dépôt
      cloné — rencontré sur un dépôt réel, où il faisait lever `ValueError`.
    - Un tag **annoté** pointe sur un objet `tag`, pas sur un `commit` :
      sans déréférencement, l'OID obtenu n'existe pas dans le DAG (§4.1).
    """
    try:
        resolved = ref.resolve() if isinstance(ref.target, str) else ref
        commit = repo.get(resolved.target).peel(pygit2.Commit)
        return str(commit.id)
    except (pygit2.GitError, AttributeError, TypeError, ValueError, KeyError):
        return None


def collect_refs(repo: pygit2.Repository) -> tuple[Ref, ...]:
    """Toutes les refs du dépôt, tags annotés déréférencés.

    Les stashes sont exclus : ils sont traités à part (§6.1 étape 5).
    """
    refs: list[Ref] = []

    for name in repo.references:
        if name.startswith("refs/stash"):
            continue
        ref = repo.references[name]
        oid = _peel_to_commit(repo, ref)
        if oid is None:
            continue

        if name.startswith("refs/heads/"):
            refs.append(Ref(name[len("refs/heads/"):], RefType.LOCAL_BRANCH, oid))
        elif name.startswith("refs/remotes/"):
            refs.append(Ref(name[len("refs/remotes/"):], RefType.REMOTE_BRANCH, oid))
        elif name.startswith("refs/tags/"):
            refs.append(Ref(name[len("refs/tags/"):], RefType.TAG, oid))

    head_oid = _head_oid(repo)
    if head_oid is not None:
        refs.append(Ref("HEAD", RefType.HEAD, head_oid))

    return tuple(refs)


def _head_oid(repo: pygit2.Repository) -> Oid | None:
    try:
        return str(repo.head.target)
    except (pygit2.GitError, KeyError):
        return None  # dépôt sans commit, ou HEAD non résolvable


def group_refs_by_oid(refs: tuple[Ref, ...]) -> dict[Oid, tuple[Ref, ...]]:
    """Regroupe les refs partageant un même commit (§4.1)."""
    grouped: dict[Oid, list[Ref]] = defaultdict(list)
    for ref in refs:
        grouped[ref.target].append(ref)
    return {oid: tuple(rs) for oid, rs in grouped.items()}
