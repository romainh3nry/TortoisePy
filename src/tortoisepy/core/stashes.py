"""Rattachement des stashes — §6.1 étape 5.

Un commit de stash a deux ou trois parents : HEAD au moment du stash,
l'index, et éventuellement les fichiers non suivis. Seul le premier est
une vraie relation d'historique ; les autres créeraient des arêtes
parasites (§4.1). Les stashes ne participent donc ni au marquage des
commits significatifs ni à la réduction transitive.
"""

from __future__ import annotations

import pygit2

from tortoisepy.core.model import DisplayNode, GraphEdge, NodeKind, Ref, RefType


def collect_stashes(
    repo: pygit2.Repository,
) -> tuple[tuple[DisplayNode, GraphEdge], ...]:
    """Un nœud et une arête par stash."""
    try:
        entries = repo.listall_stashes()
    except (AttributeError, pygit2.GitError):
        return ()

    result: list[tuple[DisplayNode, GraphEdge]] = []

    for index, entry in enumerate(entries):
        oid = str(entry.commit_id)
        commit = repo.get(entry.commit_id)
        if commit is None or not commit.parents:
            continue

        name = f"stash@{{{index}}}"
        node = DisplayNode(
            oid=oid,
            kind=NodeKind.STASH,
            refs=(Ref(name=name, type=RefType.STASH, target=oid),),
        )
        edge = GraphEdge(
            ancestor=str(commit.parents[0].id),  # premier parent seulement
            descendant=oid,
            skipped=(),
        )
        result.append((node, edge))

    return tuple(result)
