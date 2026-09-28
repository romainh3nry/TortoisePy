"""Réduction transitive — §6.1 étape 4.

Distincte de la compression (§6.1 étape 3) : celle-ci supprime des arêtes
redondantes, celle-là remplace des chaînes de commits. Les garder séparées
évite qu'une correction de l'une casse l'autre.
"""

from __future__ import annotations

from collections import defaultdict

from tortoisepy.core.model import GraphEdge, Oid


def reduce_transitive_edges(edges: tuple[GraphEdge, ...]) -> tuple[GraphEdge, ...]:
    """Supprime (A, B) s'il existe un chemin A → … → B d'au moins deux arêtes."""
    if not edges:
        return ()

    successors: dict[Oid, set[Oid]] = defaultdict(set)
    for e in edges:
        successors[e.ancestor].add(e.descendant)

    kept = [e for e in edges if not _has_indirect_path(successors, e.ancestor, e.descendant)]
    return tuple(kept)


def _has_indirect_path(
    successors: dict[Oid, set[Oid]], start: Oid, target: Oid
) -> bool:
    """Existe-t-il un chemin start → target passant par au moins un nœud ?"""
    stack = [s for s in successors.get(start, ()) if s != target]
    visited: set[Oid] = set()

    while stack:
        node = stack.pop()
        if node == target:
            return True
        if node in visited:
            continue
        visited.add(node)
        stack.extend(successors.get(node, ()))

    return False
