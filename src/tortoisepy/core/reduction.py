"""Réduction transitive — §6.1 étape 4.

Distincte de la compression (§6.1 étape 3) : celle-ci supprime des arêtes
redondantes, celle-là remplace des chaînes de commits. Les garder séparées
évite qu'une correction de l'une casse l'autre.
"""

from __future__ import annotations

from collections import defaultdict

from tortoisepy.core.model import GraphEdge, Oid


def reduce_transitive_edges(edges: tuple[GraphEdge, ...]) -> tuple[GraphEdge, ...]:
    """Supprime (A, B) s'il existe un chemin A → … → B d'au moins deux arêtes.

    **Les descendants de chaque nœud sont calculés une seule fois**, en
    remontant l'ordre topologique. La version précédente reparcourait le
    graphe pour *chaque* arête : signalé par l'utilisateur sur un dépôt
    de 21 816 commits, où cette fonction prenait à elle seule **16,8 s**
    sur les 19 s de construction du graphe — 102 millions d'opérations de
    liste au profileur.

    Les ensembles de descendants sont des **entiers**, un bit par nœud :
    `a | b` est alors une instruction machine, là où `set | set`
    parcourt les éléments. C'est ce qui fait l'essentiel du gain —
    mesuré sur ce dépôt : 16,4 s, puis 4,6 s avec des `set`, puis
    **0,04 s** avec des entiers, pour un résultat identique arête pour
    arête (21 608 de part et d'autre).
    """
    if not edges:
        return ()

    successors: dict[Oid, set[Oid]] = defaultdict(set)
    nodes: set[Oid] = set()
    for e in edges:
        successors[e.ancestor].add(e.descendant)
        nodes.add(e.ancestor)
        nodes.add(e.descendant)

    index = {node: position for position, node in enumerate(nodes)}
    descendants = _descendant_masks(successors, nodes, index)

    kept: list[GraphEdge] = []
    for edge in edges:
        siblings = successors[edge.ancestor]
        # Avec un seul descendant, aucun autre chemin n'existe : rien à
        # vérifier. Ce test écarte l'immense majorité des arêtes d'un
        # dépôt réel.
        if len(siblings) < 2:
            kept.append(edge)
            continue

        bit = 1 << index[edge.descendant]
        indirect = any(
            descendants.get(sibling, 0) & bit
            for sibling in siblings
            if sibling != edge.descendant
        )
        if not indirect:
            kept.append(edge)

    return tuple(kept)


def _descendant_masks(
    successors: dict[Oid, set[Oid]], nodes: set[Oid], index: dict[Oid, int]
) -> dict[Oid, int]:
    """Pour chaque nœud, le masque de tout ce qu'il atteint.

    Remonter l'ordre topologique fait hériter chaque nœud des
    descendants de ses enfants, en une passe.

    **Un cycle laisserait ses nœuds hors de l'ordre**, donc sans masque.
    Leurs arêtes seraient alors conservées plutôt que supprimées à tort
    — vérifié, et c'est exactement ce que faisait l'implémentation
    précédente. Un graphe Git est acyclique ; la dégradation est sûre.
    """
    incoming: dict[Oid, int] = defaultdict(int)
    for ancestor in successors:
        for descendant in successors[ancestor]:
            incoming[descendant] += 1

    ready = [node for node in nodes if incoming[node] == 0]
    order: list[Oid] = []
    while ready:
        node = ready.pop()
        order.append(node)
        for child in successors[node]:
            incoming[child] -= 1
            if incoming[child] == 0:
                ready.append(child)

    masks: dict[Oid, int] = {}
    for node in reversed(order):
        mask = 0
        for child in successors[node]:
            mask |= (1 << index[child]) | masks.get(child, 0)
        masks[node] = mask
    return masks


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
