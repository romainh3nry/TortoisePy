"""Placement final — §6.2 étape 3.

Assemble rangs, ordre et composantes en coordonnées réelles, en tenant
compte de la taille propre à chaque nœud : un nœud à trois refs est plus
haut, un nom de branche long est plus large.
"""

from __future__ import annotations

from collections import defaultdict

from tortoisepy.core.model import DisplayGraph, DisplayNode, Oid
from tortoisepy.layout.metrics import (
    LayoutResult,
    MonospaceMeasurer,
    NodeMeasurer,
    Placement,
    Size,
)
from tortoisepy.layout.ordering import find_components, order_within_ranks
from tortoisepy.layout.ranking import compute_ranks

GAP_X = 60.0
"""Espace horizontal minimal entre deux nœuds d'un même rang.

Relevé de 40 à 60 px : le graphe paraissait comprimé à l'usage."""

GAP_Y = 90.0
"""Espace vertical entre deux rangs, mesuré entre leurs bases.

Relevé de 60 à 90 px pour la même raison. C'est aussi ce qui laisse la
place aux étiquettes « N commits » sans qu'elles chevauchent les nœuds."""

COMPONENT_GAP = 120.0
"""Écart entre deux historiques indépendants, plus large pour les distinguer."""


def layout_graph(
    graph: DisplayGraph, measurer: NodeMeasurer | None = None
) -> LayoutResult:
    """Place chaque nœud du graphe.

    `measurer` permet à `ui/` d'injecter les métriques réelles de sa police ;
    à défaut, une mesure monospace cohérente est utilisée.
    """
    if not graph.nodes:
        return LayoutResult(placements=(), width=0.0, height=0.0)

    measure = measurer or MonospaceMeasurer()
    sizes = {node.oid: measure.measure(node) for node in graph.nodes}

    ranks = compute_ranks(graph)
    orders = order_within_ranks(graph, ranks)
    components = find_components(graph)

    row_heights = _row_heights(orders, sizes)
    row_bottoms = _row_bottoms(orders, row_heights)

    ancestors: dict[Oid, list[Oid]] = defaultdict(list)
    for edge in graph.edges:
        ancestors[edge.descendant].append(edge.ancestor)

    placements: list[Placement] = []
    offset_x = 0.0

    for component in components:
        members = set(component)
        width = _place_component(
            members, orders, sizes, row_bottoms, offset_x, placements,
            ancestors,
        )
        offset_x += width + COMPONENT_GAP

    total_width = max((p.right for p in placements), default=0.0)
    total_height = max((p.top for p in placements), default=0.0)

    # Tri final : deux exécutions doivent produire la même séquence (§10.4).
    return LayoutResult(
        placements=tuple(sorted(placements, key=lambda p: p.oid)),
        width=total_width,
        height=total_height,
    )


def _row_heights(
    orders: dict[int, tuple[Oid, ...]], sizes: dict[Oid, Size]
) -> dict[int, float]:
    """Hauteur de chaque rang : celle de son nœud le plus haut."""
    return {
        rank: max((sizes[oid].height for oid in oids), default=0.0)
        for rank, oids in orders.items()
    }


def _row_bottoms(
    orders: dict[int, tuple[Oid, ...]], heights: dict[int, float]
) -> dict[int, float]:
    """Ordonnée de la base de chaque rang, du bas vers le haut."""
    bottoms: dict[int, float] = {}
    y = 0.0
    for rank in sorted(orders):
        bottoms[rank] = y
        y += heights[rank] + GAP_Y
    return bottoms


def _place_component(
    members: set[Oid],
    orders: dict[int, tuple[Oid, ...]],
    sizes: dict[Oid, Size],
    row_bottoms: dict[int, float],
    offset_x: float,
    out: list[Placement],
    ancestors: dict[Oid, list[Oid]],
) -> float:
    """Pose les nœuds d'une composante, chacun aligné sur ses ancêtres.

    Poser les nœuds de gauche à droite, comme le faisait la version
    précédente, décalait les centres dès que deux nœuds successifs avaient
    des largeurs différentes : les liaisons serpentaient alors qu'elles
    auraient dû être verticales.

    Chaque nœud vise ici le centre de ses ancêtres déjà placés, et n'est
    poussé vers la droite que s'il chevaucherait son voisin. Mesuré sur un
    dépôt réel de 336 nœuds : 204 arêtes verticales avant, 272 après.

    Les arêtes restantes sont géométriquement inévitables — un merge a deux
    ancêtres à des abscisses différentes, ses deux liaisons ne peuvent pas
    être verticales toutes les deux. C'est le tracé orthogonal de `ui/` qui
    les rend droites malgré tout.
    """
    centers: dict[Oid, float] = {}
    for placement in out:  # composantes déjà posées
        centers[placement.oid] = placement.x + placement.size.width / 2.0

    width = 0.0

    for rank in sorted(orders):
        row = [oid for oid in orders[rank] if oid in members]
        if not row:
            continue

        targets = {
            oid: _target(oid, ancestors, centers, offset_x) for oid in row
        }
        # Trier par cible garde l'ordre horizontal cohérent avec le rang
        # précédent, donc réduit les croisements sans calcul supplémentaire.
        row.sort(key=lambda oid: (targets[oid], oid))

        # Poser d'abord, replacer ensuite : le rang entier est ramené
        # contre le bord de sa composante s'il a dérivé.
        laid: list[tuple[Oid, float, Size]] = []
        cursor: float | None = None
        for oid in row:
            size = sizes[oid]
            x = targets[oid] - size.width / 2.0
            if cursor is not None and x < cursor:
                x = cursor
            laid.append((oid, x, size))
            cursor = x + size.width + GAP_X

        # Sans ce recalage, chaque rang poussé vers la droite décale tous
        # les suivants : le graphe part en escalier et sa largeur explose —
        # mesuré sur un dépôt réel, le bord gauche dérivait de -50 px à
        # 6094 px. La colonne doit rester verticale.
        drift = min(x for _, x, _ in laid) - offset_x
        shift = -drift if drift > 0.0 else 0.0

        for oid, x, size in laid:
            placed = x + shift
            out.append(
                Placement(oid=oid, x=placed, y=row_bottoms[rank], size=size)
            )
            centers[oid] = placed + size.width / 2.0

        right = max(x + size.width for _, x, size in laid) + shift
        width = max(width, right - offset_x)

    return max(width, 0.0)


def _target(
    oid: Oid,
    ancestors: dict[Oid, list[Oid]],
    centers: dict[Oid, float],
    offset_x: float,
) -> float:
    """Abscisse visée : le centre des ancêtres déjà placés.

    Un nœud sans ancêtre placé — une racine — vise l'origine de SA
    composante, pas celle du canevas : sinon deux historiques indépendants
    se superposent (§10.4).
    """
    known = [centers[a] for a in ancestors.get(oid, ()) if a in centers]
    return sum(known) / len(known) if known else offset_x
