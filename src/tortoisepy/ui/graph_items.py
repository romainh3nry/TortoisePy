"""Éléments graphiques du Revision Graph — §4.4.

C'est ici, et uniquement ici, que la convention d'axes bascule : `layout/`
produit un `y` croissant vers le haut, Qt le fait croître vers le bas.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
)

from tortoisepy.core.model import DisplayGraph, DisplayNode, GraphEdge
from tortoisepy.layout.metrics import LayoutResult, Placement
from tortoisepy.ui import theme

SCENE_MARGIN = 40.0

TANGENT_SAMPLE = 0.06
"""Fraction de courbe échantillonnée pour trouver la tangente finale.

Trop petite, l'échantillon devient sensible aux arrondis ; trop grande,
il lisse la courbure réelle de l'arrivée."""

STRAIGHT_THRESHOLD = 12.0
"""En dessous de ce décalage horizontal, la liaison est droite.

Une courbe entre deux nœuds quasi alignés serpente sans rien apporter — le
défaut était visible à l'œil sur un vrai dépôt."""


class NodeItem(QGraphicsRectItem):
    """Un nœud : rectangle arrondi, une ligne par ref (§4.4)."""

    def __init__(self, node: DisplayNode, placement: Placement, scene_y: float):
        super().__init__(0.0, 0.0, placement.size.width, placement.size.height)
        self.node = node
        self.setPos(placement.x, scene_y)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self._paint_labels()
        self.refresh_colors()

    def _paint_labels(self) -> None:
        font = theme.node_font()
        labels = theme.node_labels(self.node)
        line = self.rect().height() - 2 * theme.PADDING_Y
        line = line / max(len(labels), 1)

        for index, label in enumerate(labels):
            item = QGraphicsSimpleTextItem(label, self)
            item.setFont(font)
            item.setPos(theme.PADDING_X, theme.PADDING_Y + index * line)

    def refresh_colors(self) -> None:
        """Applique la couleur correspondant à l'état de sélection (§4.3)."""
        selected = self.isSelected()
        self.setBrush(QBrush(theme.node_color(self.node, selected)))
        self.setPen(QPen(theme.PALETTE.border, theme.NODE_BORDER_WIDTH))

        colour = theme.text_color(selected)
        for child in self.childItems():
            if isinstance(child, QGraphicsSimpleTextItem):
                child.setBrush(QBrush(colour))

    def paint(self, painter, option, widget=None) -> None:
        """Dessine un rectangle arrondi plutôt que l'angle droit par défaut.

        `option` est neutralisé : sans cela, Qt surimprime son propre cadre
        de sélection en pointillés, qui jure avec le style TortoiseGit.
        """
        self.refresh_colors()
        painter.setBrush(self.brush())
        painter.setPen(self.pen())
        painter.drawRoundedRect(self.rect(), theme.NODE_RADIUS, theme.NODE_RADIUS)


class EdgeItem(QGraphicsPathItem):
    """Une arête : courbe terminée par une flèche pleine (§4.4)."""

    def __init__(
        self,
        edge: GraphEdge,
        start: QPointF,
        end: QPointF,
        label: str | None = None,
    ):
        super().__init__()
        self.edge = edge
        self.label = label
        self.setPen(QPen(theme.PALETTE.edge, theme.EDGE_WIDTH))
        self.setZValue(-1.0)  # sous les nœuds
        self._build(start, end)

        if label is not None:
            text = QGraphicsSimpleTextItem(label, self)
            text.setFont(theme.node_font())
            text.setBrush(QBrush(theme.PALETTE.edge))
            middle = (start + end) / 2.0
            text.setPos(middle.x() + 4.0, middle.y() - 16.0)

    def _build(self, start: QPointF, end: QPointF) -> None:
        """Trace la liaison, puis la flèche comme élément SÉPARÉ.

        Deux pièges évités ici :

        - Ajouter le triangle au même `QPainterPath` fait tracer son contour
          par le stylo de la ligne : le segment de retour se superpose à la
          courbe et produit un **double trait**. La flèche est donc un item
          distinct, rempli sans contour.
        - Une courbe entre deux nœuds presque alignés **serpente** sans
          raison. En dessous d'un décalage horizontal perceptible, on trace
          une droite.

        Le tracé courbe a été préféré au tracé orthogonal, essayé puis
        écarté : les angles droits rendaient moins bien à l'usage.
        """
        path = QPainterPath(start)

        if abs(end.x() - start.x()) < STRAIGHT_THRESHOLD:
            path.lineTo(end)
        else:
            # Points de contrôle décalés verticalement : la liaison quitte
            # le nœud par le haut et arrive par le bas, comme sur la capture.
            dy = (end.y() - start.y()) * 0.5
            path.cubicTo(
                QPointF(start.x(), start.y() + dy),
                QPointF(end.x(), end.y() - dy),
                end,
            )

        self.setPath(path)

        # La flèche suit la tangente RÉELLE de la courbe à son extrémité.
        # L'orienter sur la corde start→end la faisait pointer de travers
        # dès que la liaison s'incurvait : mesuré sur un dépôt réel,
        # 164 flèches sur 467 déviaient, jusqu'à 62°.
        approach = path.pointAtPercent(max(0.0, 1.0 - TANGENT_SAMPLE))
        head = QGraphicsPolygonItem(_arrow_head(approach, end), self)
        head.setBrush(QBrush(theme.PALETTE.edge))
        head.setPen(QPen(Qt.PenStyle.NoPen))


def _arrow_head(start: QPointF, end: QPointF) -> QPolygonF:
    """Triangle plein à l'extrémité, orienté selon la direction."""
    angle = math.atan2(end.y() - start.y(), end.x() - start.x())
    size = theme.ARROW_SIZE
    spread = math.pi / 7.0

    left = QPointF(
        end.x() - size * math.cos(angle - spread),
        end.y() - size * math.sin(angle - spread),
    )
    right = QPointF(
        end.x() - size * math.cos(angle + spread),
        end.y() - size * math.sin(angle + spread),
    )
    return QPolygonF([end, left, right, end])


def build_scene(graph: DisplayGraph, layout: LayoutResult) -> QGraphicsScene:
    """Construit la scène complète à partir du graphe et de son placement."""
    scene = QGraphicsScene()
    scene.setBackgroundBrush(QBrush(theme.PALETTE.background))

    if not layout.placements:
        return scene

    items: dict[str, NodeItem] = {}

    for placement in layout.placements:
        node = graph.node(placement.oid)
        if node is None:
            continue
        item = NodeItem(node, placement, _to_scene_y(placement, layout.height))
        scene.addItem(item)
        items[placement.oid] = item

    for edge in graph.edges:
        ancestor = items.get(edge.ancestor)
        descendant = items.get(edge.descendant)
        if ancestor is None or descendant is None:
            continue

        label = (
            _skipped_label(edge.skipped_count) if edge.skipped_count else None
        )
        scene.addItem(
            EdgeItem(edge, _top_center(ancestor), _bottom_center(descendant), label)
        )

    rect = scene.itemsBoundingRect()
    scene.setSceneRect(rect.adjusted(-SCENE_MARGIN, -SCENE_MARGIN,
                                     SCENE_MARGIN, SCENE_MARGIN))
    return scene


def _skipped_label(count: int) -> str:
    """Étiquette d'une arête compressée, accordée en nombre."""
    return f"{count} commit" if count == 1 else f"{count} commits"


def _to_scene_y(placement: Placement, total_height: float) -> float:
    """Bascule l'axe vertical : layout monte, Qt descend.

    La seule conversion d'axes du projet. Tout le reste de `ui/` travaille
    en coordonnées Qt.
    """
    return total_height - placement.y - placement.size.height


def _top_center(item: NodeItem) -> QPointF:
    rect = item.sceneBoundingRect()
    return QPointF(rect.center().x(), rect.top())


def _bottom_center(item: NodeItem) -> QPointF:
    rect = item.sceneBoundingRect()
    return QPointF(rect.center().x(), rect.bottom())
