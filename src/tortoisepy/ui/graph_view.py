"""Vue du graphe : zoom, panoramique, sélection — §7.1, §7.2."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QGraphicsRectItem, QGraphicsScene, QGraphicsView

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
        # Cadres de surlignage (recherche) : superposés à la scène, jamais
        # une sélection — cf. `highlight`.
        self._highlights: list = []

        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        # Zoom centré sur le curseur : sans cela, la vue saute (§7.1).
        self.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse
        )
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)

    def show_graph(
        self,
        graph: DisplayGraph,
        layout: LayoutResult,
        unpushed: frozenset[str] = frozenset(),
        current_branch: str | None = None,
    ) -> None:
        """Remplace le contenu par un nouveau graphe."""
        scene = build_scene(graph, layout, unpushed, current_branch)
        scene.selectionChanged.connect(self.selection_changed.emit)

        previous = self.scene()
        self.setScene(scene)
        if previous is not None:
            previous.deleteLater()
        # La scène précédente est détruite, et les cadres avec elle : garder
        # des références mortes ferait compter des surlignages inexistants.
        self._highlights = []

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

    def select_node(self, oid: Oid) -> bool:
        """Sélectionne un nœud comme si l'utilisateur l'avait cliqué.

        Sert après un checkout : la vue se recentrait sur la branche, mais
        rien n'était sélectionné — le panneau latéral restait vide alors
        que l'utilisateur venait justement de choisir cette branche.

        La sélection précédente est effacée : deux nœuds sélectionnés
        changeraient le menu contextuel (il propose alors des comparaisons).
        """
        scene = self.scene()
        if scene is None:
            return False

        for item in scene.items():
            if isinstance(item, NodeItem) and item.node.oid == oid:
                scene.clearSelection()
                item.setSelected(True)
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

    def highlight(self, oids) -> None:
        """Encadre les nœuds portant ces commits.

        **Pas `setSelected`** : le menu contextuel bascule selon le
        nombre de nœuds sélectionnés, donc une recherche à plusieurs
        résultats le transformerait en menu de comparaison (vérifié).
        On superpose des cadres, qui ne touchent à rien d'autre — et
        `graph_items.py`, dont le rendu est validé, n'est pas modifié.
        """
        for cadre in self._highlights:
            scene = cadre.scene()
            if scene is not None:
                scene.removeItem(cadre)
        self._highlights = []

        scene = self.scene()
        if scene is None or not oids:
            return

        cibles = set(oids)
        for item in scene.items():
            if isinstance(item, NodeItem) and item.node.oid in cibles:
                cadre = QGraphicsRectItem(
                    item.sceneBoundingRect().adjusted(-4, -4, 4, 4)
                )
                cadre.setPen(QPen(QColor(255, 170, 0), 3))
                cadre.setBrush(Qt.BrushStyle.NoBrush)
                cadre.setZValue(100)
                scene.addItem(cadre)
                self._highlights.append(cadre)

    def highlighted_count(self) -> int:
        return len(self._highlights)

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
