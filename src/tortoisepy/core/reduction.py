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

    # Seules les arêtes dont l'ancêtre a PLUSIEURS descendants peuvent être
    # redondantes : avec un seul, il n'existe aucun autre chemin. Ce test
    # écarte l'immense majorité des arêtes d'un dépôt réel sans rien
    # parcourir — mesuré, 19 s ramenées à une fraction de seconde sur un
    # dépôt de 710 refs.
    kept: list[GraphEdge] = []
    for edge in edges:
        siblings = successors[edge.ancestor]
        if len(siblings) < 2:
            kept.append(edge)
            continue
        if not _reaches(successors, siblings - {edge.descendant}, edge.descendant):
            kept.append(edge)

    return tuple(kept)


def _reaches(
    successors: dict[Oid, set[Oid]], starts: set[Oid], target: Oid
) -> bool:
    """Le `target` est-il atteignable depuis l'un des `starts` ?

    Chaque départ est un descendant direct de l'ancêtre : trouver la cible
    à partir de lui prouve qu'un chemin indirect existe, donc que l'arête
    directe est redondante.
    """
    seen: set[Oid] = set()
    stack = list(starts)

    while stack:
        node = stack.pop()
        if node == target:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(successors[node])

    return False


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
