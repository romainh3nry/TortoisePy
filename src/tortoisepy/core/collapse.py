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
    removable = {
        oid for oid in candidates if not _is_sole_connector(oid, graph)
    }
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


def _is_sole_connector(oid: Oid, graph: DisplayGraph) -> bool:
    """La jonction est-elle l'unique lien entre ses descendants ?

    C'est le cas d'un merge-base : deux branches divergentes n'ont aucun
    autre chemin entre elles. Le retirer les séparerait (§4.2).
    """
    descendants = [e.descendant for e in graph.edges if e.ancestor == oid]
    if len(descendants) < 2:
        return False

    # Existe-t-il un autre chemin entre deux de ces descendants, sans
    # passer par cette jonction ?
    neighbours: dict[Oid, set[Oid]] = defaultdict(set)
    for edge in graph.edges:
        if oid in (edge.ancestor, edge.descendant):
            continue
        neighbours[edge.ancestor].add(edge.descendant)
        neighbours[edge.descendant].add(edge.ancestor)

    reachable = {descendants[0]}
    stack = [descendants[0]]
    while stack:
        current = stack.pop()
        for neighbour in neighbours[current]:
            if neighbour not in reachable:
                reachable.add(neighbour)
                stack.append(neighbour)

    return any(d not in reachable for d in descendants[1:])
