"""Composantes connexes et ordre intra-rang — §6.2 étape 2, §10.4."""

from __future__ import annotations

from collections import defaultdict

from tortoisepy.core.model import DisplayGraph, Oid

BARYCENTRE_PASSES = 3
"""Passes de l'heuristique. Au-delà, le gain devient négligeable (§6.2)."""


def find_components(graph: DisplayGraph) -> tuple[tuple[Oid, ...], ...]:
    """Composantes connexes, en traitant les arêtes comme non orientées.

    Deux historiques sans ancêtre commun forment deux composantes, que le
    placement disposera côte à côte (§10.4).
    """
    oids = sorted(node.oid for node in graph.nodes)
    known = set(oids)

    neighbours: dict[Oid, set[Oid]] = defaultdict(set)
    for edge in graph.edges:
        if edge.ancestor in known and edge.descendant in known:
            neighbours[edge.ancestor].add(edge.descendant)
            neighbours[edge.descendant].add(edge.ancestor)

    seen: set[Oid] = set()
    components: list[tuple[Oid, ...]] = []

    for start in oids:  # ordre trié : déterminisme
        if start in seen:
            continue
        stack = [start]
        seen.add(start)
        members: list[Oid] = []
        while stack:
            current = stack.pop()
            members.append(current)
            for neighbour in sorted(neighbours[current]):
                if neighbour not in seen:
                    seen.add(neighbour)
                    stack.append(neighbour)
        components.append(tuple(sorted(members)))

    return tuple(components)


def order_within_ranks(
    graph: DisplayGraph, ranks: dict[Oid, int]
) -> dict[int, tuple[Oid, ...]]:
    """Ordre horizontal des nœuds de chaque rang.

    Heuristique du barycentre : un nœud se place à la moyenne des positions
    de ses voisins du rang précédent. Répétée quelques fois, elle réduit les
    croisements sans coûter cher. L'ordre initial est alphabétique, ce qui
    garantit le déterminisme exigé par §10.4.
    """
    by_rank: dict[int, list[Oid]] = defaultdict(list)
    for oid in sorted(ranks):
        by_rank[ranks[oid]].append(oid)

    known = set(ranks)
    ancestors: dict[Oid, list[Oid]] = defaultdict(list)
    for edge in graph.edges:
        if edge.ancestor in known and edge.descendant in known:
            ancestors[edge.descendant].append(edge.ancestor)

    for _ in range(BARYCENTRE_PASSES):
        for rank in sorted(by_rank):
            if rank == 0:
                continue
            previous = {oid: i for i, oid in enumerate(by_rank[rank - 1])}

            def barycentre(oid: Oid) -> tuple[float, str]:
                positions = [
                    previous[a] for a in ancestors[oid] if a in previous
                ]
                if not positions:
                    # Sans ancêtre au rang précédent, garder sa place :
                    # le nom départage, donc le résultat reste stable.
                    return (float("inf"), oid)
                return (sum(positions) / len(positions), oid)

            by_rank[rank].sort(key=barycentre)

    return {rank: tuple(oids) for rank, oids in by_rank.items()}
