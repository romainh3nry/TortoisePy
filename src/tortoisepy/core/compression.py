"""Compression des segments linéaires — §6.1 étape 3.

Remplace toute chaîne de commits non significatifs entre deux commits
significatifs par une arête unique conservant les OID traversés.
"""

from __future__ import annotations

import pygit2

from tortoisepy.core.model import GraphEdge, Oid


def compress_linear_segments(
    repo: pygit2.Repository, significant: set[Oid]
) -> tuple[GraphEdge, ...]:
    """Une arête par chemin reliant deux commits significatifs."""
    edges: list[GraphEdge] = []
    seen: set[tuple[Oid, Oid]] = set()

    for oid in sorted(significant):
        try:
            commit = repo.get(pygit2.Oid(hex=oid))
        except (pygit2.GitError, ValueError):
            continue
        if commit is None:
            continue

        # Les parents sont itérés : un octopus en a plus de deux.
        for parent in commit.parents:
            ancestor, skipped = _walk_to_significant(repo, parent, significant)
            if ancestor is None:
                continue
            key = (ancestor, oid)
            if key in seen:
                continue
            seen.add(key)
            edges.append(
                GraphEdge(ancestor=ancestor, descendant=oid, skipped=tuple(skipped))
            )

    return tuple(edges)


def _walk_to_significant(
    repo: pygit2.Repository, start, significant: set[Oid]
) -> tuple[Oid | None, list[Oid]]:
    """Remonte le premier parent jusqu'au prochain commit significatif.

    Retourne cet ancêtre et les OID traversés, du plus récent au plus ancien
    inversés pour respecter l'ordre ancien → récent.
    """
    skipped: list[Oid] = []
    current = start
    guard = 0

    while current is not None:
        oid = str(current.id)
        if oid in significant:
            skipped.reverse()
            return oid, skipped

        skipped.append(oid)
        guard += 1
        if guard > 100_000:
            break  # garde-fou : historique anormalement long

        current = current.parents[0] if current.parents else None

    return None, []
