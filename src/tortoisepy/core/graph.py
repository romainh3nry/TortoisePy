"""Assemblage du graphe affiché — pipeline complet de §6.1.

    refs → commits significatifs → compression → réduction
         → simplification des jonctions → stashes
"""

from __future__ import annotations

import pygit2

from tortoisepy.core.collapse import (
    collapse_trivial_junctions,
    drop_all_junctions,
)
from tortoisepy.core.options import GraphOptions
from tortoisepy.core.compression import compress_linear_segments
from tortoisepy.core.model import DisplayGraph, DisplayNode, NodeKind
from tortoisepy.core.reduction import reduce_transitive_edges
from tortoisepy.core.refs import collect_refs, group_refs_by_oid
from tortoisepy.core.significance import significant_commits
from tortoisepy.core.stashes import collect_stashes


def build_graph(
    repo: pygit2.Repository, options: GraphOptions | None = None
) -> DisplayGraph:
    """Construit le graphe affiché d'un dépôt.

    `options` filtre les refs prises en compte. Sur un dépôt réel de 710
    refs, 413 étaient des tags de version : chacun tirait sa propre chaîne
    de jonctions, et le graphe devenait illisible. Masquer les tags par
    défaut est ce que font les clients Git sur les gros dépôts.

    Le tri par OID garantit le déterminisme exigé par §10.4.
    """
    options = options or GraphOptions()
    refs = options.filter(collect_refs(repo))
    significant = significant_commits(repo, refs)

    if not significant:
        return DisplayGraph(nodes=(), edges=())

    by_oid = group_refs_by_oid(refs)

    nodes = tuple(
        DisplayNode(
            oid=oid,
            kind=NodeKind.REF if oid in by_oid else NodeKind.JUNCTION,
            refs=by_oid.get(oid, ()),
        )
        for oid in sorted(significant)
    )

    edges = reduce_transitive_edges(compress_linear_segments(repo, significant))

    # Retire les jonctions sans intérêt visuel : sans cela, un historique où
    # chaque branche part d'un point différent produit une colonne de rangs
    # au lieu d'étaler les branches (§6.1).
    simplified = collapse_trivial_junctions(DisplayGraph(nodes=nodes, edges=edges))

    # Sur un dépôt réel, les jonctions étaient plus nombreuses que les refs
    # (234 contre 283) : elles encombraient le graphe sans rien apprendre
    # sur l'état des branches. Les retirer préserve toutes les refs et ne
    # déconnecte rien (§6.1).
    if not options.show_junctions:
        simplified = drop_all_junctions(simplified)

    nodes, edges = simplified.nodes, simplified.edges

    stash_nodes = []
    stash_edges = []

    # Les nœuds RÉELLEMENT présents après simplification, et non l'ensemble
    # des commits significatifs : `collapse_trivial_junctions` a pu retirer
    # le parent d'un stash, ce qui rendrait son arête orpheline et
    # violerait l'invariant de §10.3. Mesuré sur un dépôt réel de 710 refs.
    known = {node.oid for node in nodes}

    for node, edge in collect_stashes(repo):
        if edge.ancestor not in known:
            continue  # parent injoignable : le stash serait orphelin
        stash_nodes.append(node)
        stash_edges.append(edge)

    return DisplayGraph(
        nodes=nodes + tuple(stash_nodes),
        edges=edges + tuple(stash_edges),
    )
