"""Rang de chaque nœud — §6.2 étape 1.

Rang = longueur du plus LONG chemin depuis une racine. Le plus court ne
conviendrait pas : avec les arêtes a→b→c→d et a→d, il placerait `d` juste
au-dessus de `a`, donc au même niveau que `b`, alors que `d` descend de `c`.
"""

from __future__ import annotations

from collections import defaultdict, deque

from tortoisepy.core.model import DisplayGraph, Oid


def compute_ranks(graph: DisplayGraph) -> dict[Oid, int]:
    """Rang de chaque nœud, les racines à 0.

    Tri topologique de Kahn. Le graphe est acyclique par construction
    (invariant vérifié en phase 1) ; un cycle laisserait des nœuds non
    traités, qui retombent alors au rang 0 plutôt que de boucler.
    """
    oids = [node.oid for node in graph.nodes]
    known = set(oids)

    successors: dict[Oid, list[Oid]] = defaultdict(list)
    indegree: dict[Oid, int] = {oid: 0 for oid in oids}

    for edge in graph.edges:
        if edge.ancestor not in known or edge.descendant not in known:
            continue
        successors[edge.ancestor].append(edge.descendant)
        indegree[edge.descendant] += 1

    ranks: dict[Oid, int] = {oid: 0 for oid in oids}
    remaining = dict(indegree)

    # sorted() : deux exécutions doivent donner le même résultat (§10.4)
    queue = deque(sorted(oid for oid in oids if remaining[oid] == 0))

    while queue:
        current = queue.popleft()
        for successor in sorted(successors[current]):
            if ranks[current] + 1 > ranks[successor]:
                ranks[successor] = ranks[current] + 1
            remaining[successor] -= 1
            if remaining[successor] == 0:
                queue.append(successor)

    return ranks
