"""Sérialisation du graphe — outil de test (§10.1).

Volontairement absent de la CLI : une commande publique de plus serait à
maintenir sans bénéfice pour l'utilisateur.
"""

from __future__ import annotations

from tortoisepy.core.model import DisplayGraph


def graph_to_dict(graph: DisplayGraph) -> dict:
    """Forme comparable en test, ordonnée donc déterministe."""
    return {
        "nodes": [
            {
                "oid": node.oid,
                "kind": node.kind.value,
                "refs": [
                    {"name": ref.name, "type": ref.type.value}
                    for ref in sorted(node.refs, key=lambda r: (r.type.value, r.name))
                ],
            }
            for node in graph.nodes
        ],
        "edges": [
            {
                "ancestor": edge.ancestor,
                "descendant": edge.descendant,
                "skipped": edge.skipped_count,
            }
            for edge in graph.edges
        ],
    }
