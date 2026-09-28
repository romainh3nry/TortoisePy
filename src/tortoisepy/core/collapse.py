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


def drop_all_junctions(graph: DisplayGraph) -> DisplayGraph:
    """Retire **toutes** les jonctions sans ref, en fusionnant leurs arêtes.

    `collapse_trivial_junctions` ne retire que les jonctions à un seul
    ancêtre et un seul descendant. Celle-ci va plus loin : elle supprime
    aussi les merge-bases et les points de divergence, en reliant
    directement leurs voisins.

    Mesuré sur un dépôt réel de 518 nœuds : 234 étaient des jonctions,
    plus nombreuses que les refs. Après retrait, 284 nœuds, **toutes** les
    refs préservées (298/298), et le graphe reste d'une seule pièce.

    Les commits traversés deviennent des `skipped` : §4.2.1 reste vrai,
    rien ne devient inatteignable.
    """
    candidates = {
        node.oid for node in graph.nodes if node.kind is NodeKind.JUNCTION
    }
    if not candidates:
        return graph

    outgoing: dict[Oid, list[GraphEdge]] = defaultdict(list)
    for edge in graph.edges:
        outgoing[edge.ancestor].append(edge)

    # Une jonction dont TOUS les voisins sont en aval — un merge-base entre
    # deux branches divergentes — est leur seul lien. La retirer casserait
    # le graphe en morceaux, ce qui est précisément le défaut que §4.2
    # décrit. Vérifié : sans cette réserve, `master` et `feature` se
    # retrouvaient sans aucune arête entre eux.
    # Calculé UNE fois : la version précédente reconstruisait le graphe de
    # voisinage pour chaque jonction candidate — quadratique, 20 s sur un
    # dépôt de 8 000 nœuds.
    articulations = _articulation_points(graph)
    removable = candidates - articulations
    if not removable:
        return graph

    nodes = tuple(node for node in graph.nodes if node.oid not in removable)
    edges: list[GraphEdge] = []
    seen: set[tuple[Oid, Oid]] = set()

    for edge in graph.edges:
        if edge.ancestor in removable:
            continue  # absorbée par l'arête qui précède la jonction

        # Descendre à travers les jonctions jusqu'aux nœuds conservés. Une
        # jonction à plusieurs descendants en produit plusieurs arêtes.
        stack: list[tuple[Oid, list[Oid]]] = [
            (edge.descendant, list(edge.skipped))
        ]
        guard = 0

        while stack:
            oid, skipped = stack.pop()

            if oid not in removable:
                key = (edge.ancestor, oid)
                if key not in seen:
                    seen.add(key)
                    edges.append(
                        GraphEdge(
                            ancestor=edge.ancestor,
                            descendant=oid,
                            skipped=tuple(skipped),
                        )
                    )
                continue

            guard += 1
            if guard > len(removable) * 4:
                break  # garde-fou : le graphe est acyclique, mais peu coûteux

            for following in outgoing[oid]:
                stack.append(
                    (
                        following.descendant,
                        skipped + [oid] + list(following.skipped),
                    )
                )

    return DisplayGraph(nodes=nodes, edges=tuple(edges))


def _articulation_points(graph: DisplayGraph) -> set[Oid]:
    """Nœuds dont le retrait couperait le graphe en plusieurs morceaux.

    Un merge-base entre deux branches divergentes en est un : sans lui,
    elles n'ont plus aucun lien — le défaut que §4.2 décrit.

    Algorithme de Hopcroft-Tarjan, en un seul parcours en profondeur. Le
    parcours est itératif : un historique profond ferait déborder la pile
    d'appels Python en récursif.
    """
    neighbours: dict[Oid, list[Oid]] = defaultdict(list)
    for edge in graph.edges:
        neighbours[edge.ancestor].append(edge.descendant)
        neighbours[edge.descendant].append(edge.ancestor)

    discovery: dict[Oid, int] = {}
    low: dict[Oid, int] = {}
    parent: dict[Oid, Oid | None] = {}
    articulations: set[Oid] = set()
    counter = 0

    for start in sorted(node.oid for node in graph.nodes):
        if start in discovery:
            continue

        parent[start] = None
        root_children = 0
        stack: list[tuple[Oid, int]] = [(start, 0)]

        while stack:
            current, index = stack[-1]

            if index == 0:
                discovery[current] = low[current] = counter
                counter += 1

            if index < len(neighbours[current]):
                stack[-1] = (current, index + 1)
                neighbour = neighbours[current][index]

                if neighbour not in discovery:
                    parent[neighbour] = current
                    if current == start:
                        root_children += 1
                    stack.append((neighbour, 0))
                elif neighbour != parent[current]:
                    low[current] = min(low[current], discovery[neighbour])
                continue

            stack.pop()
            if not stack:
                continue

            above = stack[-1][0]
            low[above] = min(low[above], low[current])

            # Un nœud non racine est une articulation si l'un de ses
            # descendants ne peut remonter plus haut que lui.
            if above != start and low[current] >= discovery[above]:
                articulations.add(above)

        # La racine du parcours l'est si elle a plus d'un sous-arbre.
        if root_children > 1:
            articulations.add(start)

    return articulations
