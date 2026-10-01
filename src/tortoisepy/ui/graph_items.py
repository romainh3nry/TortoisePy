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

LABEL_POSITION = 0.5
"""Position de l'étiquette le long de la courbe, en fraction."""

LABEL_STEP = 9.0
"""Pas de décalage vertical quand deux étiquettes se recouvrent."""

LABEL_MAX_SHIFT = 54.0
"""Décalage maximal : au-delà, l'étiquette s'éloigne trop de son arête."""

LABEL_OFFSET = 14.0
"""Décalage perpendiculaire, pour que l'étiquette ne soit pas sur le trait."""

STRAIGHT_THRESHOLD = 12.0
"""En dessous de ce décalage horizontal, la liaison est droite.

Une courbe entre deux nœuds quasi alignés serpente sans rien apporter — le
défaut était visible à l'œil sur un vrai dépôt."""


class NodeItem(QGraphicsRectItem):
    """Un nœud : rectangle arrondi, une ligne par ref (§4.4)."""

    def __init__(
        self,
        node: DisplayNode,
        placement: Placement,
        scene_y: float,
        unpushed: bool = False,
        current_branch: str | None = None,
    ):
        super().__init__(0.0, 0.0, placement.size.width, placement.size.height)
        self.node = node
        self.unpushed = unpushed
        # Nécessaire pour colorer la ligne de la branche courante en rouge
        # (§4.1) et pour savoir si HEAD est détachée (§4.2).
        self.current_branch = current_branch
        self.setPos(placement.x, scene_y)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self._paint_labels()
        self.refresh_colors()

    def has_unpushed_marker(self) -> bool:
        return self.unpushed

    def _paint_labels(self) -> None:
        """Une ligne par ref, centrée dans sa bande.

        Centré plutôt qu'aligné à gauche : c'est ce que montre la capture
        de référence de TortoiseGit, et les bandes colorées rendent le
        décalage à gauche d'autant plus visible.

        Le pas vertical est celui des bandes — `rect().height()` divisée
        par le nombre de lignes — et non la zone réduite du padding :
        sans cela, texte et couleurs ne coïncideraient pas.
        """
        font = theme.node_font()
        # **La même source que les bandes de couleur.** Lire
        # `node_labels` ici en donnait quatre alors que `ref_rows` n'en
        # colorait que trois : le nœud `develop` de vti affichait une
        # ligne `HEAD` sans bande (signalé par l'utilisateur). Deux
        # sources de vérité pour un même nœud finissent toujours par
        # diverger.
        rows = theme.ref_rows(self.node, self.current_branch)
        labels = [row.label for row in rows]
        rect = self.rect()
        bande = rect.height() / max(len(labels), 1)

        for index, label in enumerate(labels):
            item = QGraphicsSimpleTextItem(label, self)
            item.setFont(font)

            mesure = item.boundingRect()
            x = rect.left() + (rect.width() - mesure.width()) / 2.0
            y = rect.top() + index * bande + (bande - mesure.height()) / 2.0
            item.setPos(x, y)

    def refresh_colors(self) -> None:
        """Applique la couleur correspondant à l'état de sélection (§4.3)."""
        selected = self.isSelected()
        self.setBrush(QBrush(theme.node_color(self.node, selected)))
        self.setPen(QPen(theme.PALETTE.border, theme.NODE_BORDER_WIDTH))

        colour = theme.text_color(selected)
        for child in self.childItems():
            if isinstance(child, QGraphicsSimpleTextItem):
                child.setBrush(QBrush(colour))

    def _paint_bands(self, painter, rows) -> None:
        """Une bande par ref, empilées, arrondies en haut et en bas.

        Le contour du nœud est redessiné par-dessus pour que les coins
        restent nets : les bandes intermédiaires sont des rectangles
        droits, et seul l'ensemble est arrondi.
        """
        rect = self.rect()
        hauteur = rect.height() / len(rows)

        painter.save()
        chemin = QPainterPath()
        chemin.addRoundedRect(rect, theme.NODE_RADIUS, theme.NODE_RADIUS)
        # Découper au contour arrondi : sans cela, les bandes du haut et
        # du bas déborderaient des coins.
        painter.setClipPath(chemin)
        painter.setPen(Qt.PenStyle.NoPen)
        for index, row in enumerate(rows):
            bande = QRectF(
                rect.left(), rect.top() + index * hauteur,
                rect.width(), hauteur,
            )
            painter.setBrush(QBrush(row.colour))
            painter.drawRect(bande)
        painter.restore()

        # Le contour, par-dessus les bandes.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(self.pen())
        painter.drawRoundedRect(rect, theme.NODE_RADIUS, theme.NODE_RADIUS)

    def paint(self, painter, option, widget=None) -> None:
        """Dessine un rectangle arrondi plutôt que l'angle droit par défaut.

        `option` est neutralisé : sans cela, Qt surimprime son propre cadre
        de sélection en pointillés, qui jure avec le style TortoiseGit.
        """
        self.refresh_colors()

        rows = theme.ref_rows(self.node, self.current_branch)
        painter.setPen(self.pen())

        if self.isSelected() or len(rows) <= 1:
            # Un nœud sélectionné garde sa couleur unique (§4.3), et une
            # seule ligne n'a pas besoin d'être découpée.
            painter.setBrush(self.brush())
            painter.drawRoundedRect(
                self.rect(), theme.NODE_RADIUS, theme.NODE_RADIUS
            )
        else:
            self._paint_bands(painter, rows)

        if self.unpushed:
            # Dessinée par-dessus, après coup : le rectangle, sa couleur et
            # ses étiquettes restent exactement ce qu'ils étaient (règle
            # utilisateur : ne pas dégrader le rendu validé).
            radius = theme.UNPUSHED_MARKER_RADIUS
            centre = self.rect().topRight() + QPointF(-radius - 2.0, radius + 2.0)
            painter.setBrush(QBrush(theme.UNPUSHED_MARKER))
            painter.setPen(QPen(theme.PALETTE.border, 1.0))
            painter.drawEllipse(centre, radius, radius)


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

        self._label_item: QGraphicsRectItem | None = None
        if label is not None:
            self._place_label(label)

    def label_rect(self) -> QRectF | None:
        """Emprise de l'étiquette en coordonnées de scène, si elle existe."""
        if self._label_item is None:
            return None
        return self._label_item.sceneBoundingRect()

    def shift_label(self, dy: float) -> None:
        """Décale l'étiquette verticalement, pour éviter une voisine."""
        if self._label_item is not None:
            self._label_item.moveBy(0.0, dy)

    def _place_label(self, label: str) -> None:
        """Pose l'étiquette SUR la courbe, décalée perpendiculairement.

        La placer au milieu du segment start→end alignait les étiquettes de
        toutes les arêtes partant d'un même nœud : elles se chevauchaient
        et les courbes leur passaient au travers.

        Ancrée sur la courbe et poussée du côté extérieur, chaque étiquette
        suit son arête. Un fond opaque la détache des traits qui passent
        derrière.
        """
        path = self.path()
        anchor = path.pointAtPercent(LABEL_POSITION)
        before = path.pointAtPercent(max(0.0, LABEL_POSITION - 0.08))

        text = QGraphicsSimpleTextItem(label, self)
        text.setFont(theme.node_font())
        text.setBrush(QBrush(theme.PALETTE.edge))

        # Normale à la courbe, orientée vers l'extérieur du virage.
        dx = anchor.x() - before.x()
        dy = anchor.y() - before.y()
        length = math.hypot(dx, dy) or 1.0
        normal_x = -dy / length
        normal_y = dx / length

        bounds = text.boundingRect()
        offset_x = normal_x * LABEL_OFFSET - bounds.width() / 2.0
        offset_y = normal_y * LABEL_OFFSET - bounds.height() / 2.0

        # Un fond opaque sous le texte : sans lui, les arêtes voisines le
        # traversent et le rendent illisible.
        backdrop = QGraphicsRectItem(bounds.adjusted(-3.0, -1.0, 3.0, 1.0), self)
        backdrop.setBrush(QBrush(theme.PALETTE.background))
        backdrop.setPen(QPen(Qt.PenStyle.NoPen))
        backdrop.setPos(anchor.x() + offset_x, anchor.y() + offset_y)
        backdrop.setZValue(-0.5)

        text.setParentItem(backdrop)
        text.setPos(0.0, 0.0)
        self._label_item = backdrop

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


def build_scene(
    graph: DisplayGraph,
    layout: LayoutResult,
    unpushed: frozenset[str] = frozenset(),
    current_branch: str | None = None,
) -> QGraphicsScene:
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
        item = NodeItem(
            node,
            placement,
            _to_scene_y(placement, layout.height),
            unpushed=_node_has_unpushed(node, unpushed),
            current_branch=current_branch,
        )
        # Qt ne garde pas la scène en vie via ses enfants ; côté Python,
        # rien ne référence plus la scène une fois `build_scene` retourné
        # si l'appelant ne conserve que les items (cas des tests). Sans ce
        # renvoi, le ramasse-miettes détruit la scène — et donc l'item C++
        # — dès la fin de l'expression qui a appelé `build_scene`.
        scene.addItem(item)
        items[placement.oid] = item

    for edge in graph.edges:
        ancestor = items.get(edge.ancestor)
        descendant = items.get(edge.descendant)
        if ancestor is None or descendant is None:
            continue

        # Aucune étiquette : le décompte de commits surchargeait l'UI
        # (demandé par l'utilisateur). Le nombre reste accessible au clic,
        # dans le panneau latéral, qui liste les commits eux-mêmes plutôt
        # que de les résumer par un nombre. `EdgeItem` accepte `label=None`
        # et la courbe comme la flèche sont construites sans lui.
        scene.addItem(
            EdgeItem(edge, _top_center(ancestor), _bottom_center(descendant))
        )

    _spread_labels(scene)

    rect = scene.itemsBoundingRect()
    scene.setSceneRect(rect.adjusted(-SCENE_MARGIN, -SCENE_MARGIN,
                                     SCENE_MARGIN, SCENE_MARGIN))
    return scene


def _node_has_unpushed(node: DisplayNode, unpushed: frozenset[str]) -> bool:
    """Le nœud porte-t-il un commit non poussé ?

    Un nœud représente une ref, pas un commit isolé : la pastille dit
    « cette branche a des choses à pousser ». Le détail par commit est dans
    le panneau latéral.
    """
    if not unpushed:
        return False
    return node.oid in unpushed


def _spread_labels(scene: QGraphicsScene) -> None:
    """Écarte les étiquettes qui se recouvrent.

    Ancrer chaque étiquette sur sa courbe ne suffit pas là où beaucoup
    d'arêtes se croisent : mesuré sur un dépôt réel, une dizaine se
    superposaient encore, devenant illisibles.

    Chaque étiquette est décalée vers le haut jusqu'à ne plus toucher une
    voisine. Le décalage est borné : au-delà, l'étiquette s'éloignerait
    trop de son arête pour qu'on sache à laquelle elle appartient.
    """
    edges = [i for i in scene.items() if isinstance(i, EdgeItem)]
    placed: list[QRectF] = []

    # Du haut vers le bas : l'ordre rend le résultat stable d'une
    # construction à l'autre (§10.4).
    for item in sorted(
        edges,
        key=lambda e: (
            (e.label_rect().top(), e.label_rect().left())
            if e.label_rect() is not None
            else (0.0, 0.0)
        ),
    ):
        rect = item.label_rect()
        if rect is None:
            continue

        shift = 0.0
        while shift < LABEL_MAX_SHIFT:
            moved = rect.translated(0.0, -shift)
            if not any(moved.intersects(other) for other in placed):
                break
            shift += LABEL_STEP

        item.shift_label(-shift)
        placed.append(rect.translated(0.0, -shift))


def _skipped_label(count: int) -> str:
    """Étiquette d'une arête, accordée en nombre.

    `count` inclut le commit du nœud d'arrivée : c'est le nombre de commits
    que la branche a ajoutés depuis le nœud précédent, celui-là même que
    le panneau latéral encadre au clic.
    """
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
