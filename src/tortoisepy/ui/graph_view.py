"""Vue du graphe : zoom, panoramique, sélection — §7.1, §7.2."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView

from tortoisepy.core.model import DisplayGraph, Oid
from tortoisepy.layout.metrics import LayoutResult
from tortoisepy.ui.graph_items import NodeItem, build_scene


class GraphView(QGraphicsView):
    """Affiche le Revision Graph et porte la navigation."""

    MIN_ZOOM = 0.1
    MAX_ZOOM = 5.0
    ZOOM_STEP = 1.15

    selection_changed = Signal()
    node_double_clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._zoom = 1.0

        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        # Zoom centré sur le curseur : sans cela, la vue saute (§7.1).
        self.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse
        )
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)

    def show_graph(self, graph: DisplayGraph, layout: LayoutResult) -> None:
        """Remplace le contenu par un nouveau graphe."""
        scene = build_scene(graph, layout)
        scene.selectionChanged.connect(self.selection_changed.emit)

        previous = self.scene()
        self.setScene(scene)
        if previous is not None:
            previous.deleteLater()

        self._apply_zoom()

    def center_on_node(self, oid: Oid) -> bool:
        """Amène un nœud au centre de la vue. Faux s'il est absent.

        Sur un gros dépôt, le graphe dépasse les 20 000 px de haut :
        s'ouvrir en haut place l'utilisateur loin de sa branche courante.
        """
        scene = self.scene()
        if scene is None:
            return False

        for item in scene.items():
            if isinstance(item, NodeItem) and item.node.oid == oid:
                self.centerOn(item)
                return True

        return False

    def selected_oids(self) -> tuple[Oid, ...]:
        """OID des nœuds sélectionnés, triés pour rester déterministes."""
        scene = self.scene()
        if scene is None:
            return ()
        return tuple(
            sorted(
                item.node.oid
                for item in scene.selectedItems()
                if isinstance(item, NodeItem)
            )
        )

    def current_zoom(self) -> float:
        return self._zoom

    def zoom_in(self) -> None:
        self._set_zoom(self._zoom * self.ZOOM_STEP)

    def zoom_out(self) -> None:
        self._set_zoom(self._zoom / self.ZOOM_STEP)

    def reset_zoom(self) -> None:
        """⌘0 : retour à 100 % (§7.1)."""
        self._set_zoom(1.0)

    def fit_to_window(self) -> None:
        """⌘9 : ajuste le graphe entier à la fenêtre (§7.1)."""
        scene = self.scene()
        if scene is None or scene.sceneRect().isEmpty():
            return

        self.fitInView(scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self._zoom = self.transform().m11()

    def wheelEvent(self, event) -> None:
        """⌘ + molette zoome ; molette seule défile (§7.1)."""
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            # Qt mappe ⌘ sur ControlModifier sur macOS.
            if event.angleDelta().y() > 0:
                self.zoom_in()
            else:
                self.zoom_out()
            event.accept()
            return

        super().wheelEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        item = self.itemAt(event.position().toPoint())
        while item is not None and not isinstance(item, NodeItem):
            item = item.parentItem()

        if isinstance(item, NodeItem):
            self.node_double_clicked.emit(item.node.oid)
            event.accept()
            return

        super().mouseDoubleClickEvent(event)

    def _set_zoom(self, value: float) -> None:
        self._zoom = max(self.MIN_ZOOM, min(self.MAX_ZOOM, value))
        self._apply_zoom()

    def _apply_zoom(self) -> None:
        self.resetTransform()
        self.scale(self._zoom, self._zoom)
