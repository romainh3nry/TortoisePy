"""Suppression des jonctions sans intérêt — §6.1, étape finale.

Le marquage des commits significatifs retient les parents directs de tout
merge (§6.1 étape 2), ce qui est indispensable pour ne pas perdre de branches
sur un octopus. Mais sur un historique où chaque branche part d'un point
différent, beaucoup de ces parents se retrouvent avec **un seul ancêtre et un
seul descendant** : ils n'apportent aucune information topologique.

Mesuré sur un dépôt réel de 93 commits : 15 des 17 jonctions étaient dans ce
cas, et chacune créait un rang supplémentaire. Le graphe formait une colonne
de 26 rangs pour 27 nœuds, alors que la capture TortoiseGit de référence étale
les branches horizontalement.

Les retirer ramène ce dépôt à 13 nœuds et 13 rangs, sans perdre une seule ref
ni changer le nombre de composantes connexes.
"""

from __future__ import annotations

from collections import defaultdict

from tortoisepy.core.model import DisplayGraph, GraphEdge, NodeKind, Oid


def collapse_trivial_junctions(graph: DisplayGraph) -> DisplayGraph:
    """Retire les jonctions à un seul ancêtre et un seul descendant.

    Seuls les nœuds `JUNCTION` sont concernés : un nœud portant une ref est
    toujours conservé, et un stash n'est jamais traversé.

    Les commits sautés des arêtes fusionnées sont concaténés, de sorte que
    §4.2.1 reste vrai — aucun commit ne devient inatteignable.
    """
    if not graph.nodes:
        return graph

    incoming: dict[Oid, list[GraphEdge]] = defaultdict(list)
    outgoing: dict[Oid, list[GraphEdge]] = defaultdict(list)
    for edge in graph.edges:
        outgoing[edge.ancestor].append(edge)
        incoming[edge.descendant].append(edge)

    removable = {
        node.oid
        for node in graph.nodes
        if node.kind is NodeKind.JUNCTION
        and len(incoming[node.oid]) == 1
        and len(outgoing[node.oid]) == 1
    }

    if not removable:
        return graph

    nodes = tuple(node for node in graph.nodes if node.oid not in removable)
    edges: list[GraphEdge] = []

    for edge in graph.edges:
        if edge.ancestor in removable:
            continue  # cette arête sera absorbée par celle qui la précède

        current = edge
        skipped = list(edge.skipped)
        guard = 0

        while current.descendant in removable:
            following = outgoing[current.descendant][0]
            # Le nœud traversé devient lui-même un commit sauté : il reste
            # accessible depuis l'arête (§4.2.1).
            skipped.append(current.descendant)
            skipped.extend(following.skipped)
            current = following

            guard += 1
            if guard > len(removable):
                break  # garde-fou : cycle impossible, mais coûte peu

        edges.append(
            GraphEdge(
                ancestor=edge.ancestor,
                descendant=current.descendant,
                skipped=tuple(skipped),
            )
        )

    return DisplayGraph(nodes=nodes, edges=tuple(edges))
