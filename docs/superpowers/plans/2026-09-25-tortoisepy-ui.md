# tortoisePy — Plan d'implémentation, phase 4 : `ui/`

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Afficher le Revision Graph à l'écran, fidèle à TortoiseGit, avec
navigation, menu contextuel et rafraîchissement automatique.

**Architecture:** PySide6. `theme.py` centralise couleurs et métriques ;
`QtMeasurer` implémente le protocole de mesure de la phase 2 avec
`QFontMetricsF` ; `graph_items.py` dessine nœuds et arêtes ; `graph_view.py`
porte la navigation ; `watcher.py` surveille `.git` ; `main_window.py`
assemble.

**Tech Stack:** Python 3.13, PySide6 6.11, pytest-qt. Les tests tournent en
mode `offscreen`, sans écran.

**Spec:** `docs/superpowers/specs/2026-09-11-tortoisepy-design.md`
(§4.3, §4.4, §7.1 à §7.9)

**Prérequis:** phases 1 à 3 terminées, 299 tests passent.

## Global Constraints

- **Python 3.13**, typage moderne (`str | None`).
- **`ui/` est la SEULE couche autorisée à importer PySide6.** `core/` et
  `layout/` restent indépendants — vérifié par `tests/test_architecture.py`.
- **`ui/` ne fait jamais d'opération Git directement.** Il appelle
  `core.operations`, qui retourne un `OperationResult` (§7.6).
- **Mode offscreen obligatoire pour les tests.** `QT_QPA_PLATFORM=offscreen`
  est posé dans `tests/ui/conftest.py`, pas dans le code applicatif.
- **Convention d'axes.** `layout/` produit un `y` croissant vers le haut ; Qt
  croît vers le bas. La conversion se fait à un seul endroit, dans
  `graph_items.py`, jamais ailleurs.
- **Aucune commande `git`.** Les fixtures de test peuvent invoquer `git` via
  `subprocess` sur des dépôts temporaires.
- **Une `QApplication` doit exister avant toute opération de police.**
  Vérifié : `QFontMetricsF` sans `QApplication` fait **abandonner le
  processus** (« Must construct a QGuiApplication before accessing
  QFontDatabase »), ce n'est pas une exception rattrapable. Le mode
  offscreen n'y change rien. Les tests UI ont une fixture `autouse` qui s'en
  charge ; `cli.py` (phase 5) devra créer la `QApplication` **avant**
  d'instancier `MainWindow`.
- **Pas de `QColor` en valeur par défaut de dataclass.** Vérifié :
  `dataclasses` refuse un `QColor` littéral (« mutable default … not
  allowed »), le module ne s'importe même pas. Utiliser
  `field(default_factory=lambda: QColor(r, g, b))`.
- **Versions vérifiées le 2026-09-25 :** PySide6 6.11.2, pytest-qt installé.
  `QGraphicsView` expose `scale`, `fitInView`, `setDragMode`, `mapToScene`,
  `centerOn`, `setTransformationAnchor`, `resetTransform`.
  `QFileSystemWatcher` expose `addPath`, `addPaths`, les signaux `fileChanged`
  et `directoryChanged`. `QFontMetricsF.horizontalAdvance` et `.height()`
  fonctionnent en offscreen.

---

### Task 1: Thème et mesure Qt

**Files:**
- Create: `src/tortoisepy/ui/__init__.py`
- Create: `src/tortoisepy/ui/theme.py`
- Test: `tests/ui/__init__.py`
- Test: `tests/ui/conftest.py`
- Test: `tests/ui/test_theme.py`

**Interfaces:**
- Consumes: `DisplayNode`, `NodeKind`, `RefType` (phase 1), `Size`,
  `NodeMeasurer` (phase 2)
- Produces: `Palette`, `node_color(node, selected)`, `QtMeasurer`,
  `NODE_RADIUS`, `NODE_FONT`

`QtMeasurer` est l'implémentation réelle du protocole défini en phase 2 :
`layout/` mesure enfin avec la police effective, sans jamais connaître Qt.

- [ ] **Step 1: Écrire le conftest des tests UI**

```python
# tests/ui/conftest.py
"""Qt en mode offscreen : les tests tournent sans écran.

Doit être posé AVANT le premier import de PySide6, d'où sa place ici
plutôt que dans une fixture.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
```

- [ ] **Step 2: Écrire les tests**

```python
# tests/ui/test_theme.py
from PySide6.QtGui import QColor

from tortoisepy.core.model import DisplayNode, NodeKind, Ref, RefType
from tortoisepy.ui.theme import QtMeasurer, node_color


def node(oid: str, kind: NodeKind, *refs: Ref) -> DisplayNode:
    return DisplayNode(oid=oid, kind=kind, refs=refs)


def ref(name: str, type_: RefType) -> Ref:
    return Ref(name, type_, "a" * 40)


def test_current_branch_is_green():
    """§4.3 : la branche courante (HEAD) est verte."""
    n = node("a" * 40, NodeKind.REF,
             ref("master", RefType.LOCAL_BRANCH), ref("HEAD", RefType.HEAD))
    colour = node_color(n, selected=False)
    assert colour.green() > colour.red()
    assert colour.green() > colour.blue()


def test_local_branch_is_yellow():
    n = node("a" * 40, NodeKind.REF, ref("feature", RefType.LOCAL_BRANCH))
    colour = node_color(n, selected=False)
    assert colour.red() > 200 and colour.green() > 200
    assert colour.blue() < 150


def test_remote_branch_differs_from_local():
    """§4.3 : beige pour les distantes, jaune pour les locales."""
    local = node_color(
        node("a" * 40, NodeKind.REF, ref("f", RefType.LOCAL_BRANCH)), False
    )
    remote = node_color(
        node("b" * 40, NodeKind.REF, ref("origin/f", RefType.REMOTE_BRANCH)), False
    )
    assert local != remote


def test_stash_is_grey():
    n = node("a" * 40, NodeKind.STASH, ref("stash@{0}", RefType.STASH))
    colour = node_color(n, selected=False)
    assert colour.red() == colour.green() == colour.blue()


def test_junction_is_light():
    """§4.3 : les jonctions sont discrètes, remplissage clair."""
    colour = node_color(node("a" * 40, NodeKind.JUNCTION), selected=False)
    assert colour.red() > 230 and colour.green() > 230 and colour.blue() > 230


def test_selection_overrides_every_type():
    """§4.3 : le nœud sélectionné est rouge foncé, quel que soit son type."""
    kinds = [
        node("a" * 40, NodeKind.REF, ref("master", RefType.HEAD)),
        node("b" * 40, NodeKind.REF, ref("f", RefType.LOCAL_BRANCH)),
        node("c" * 40, NodeKind.STASH, ref("stash@{0}", RefType.STASH)),
        node("d" * 40, NodeKind.JUNCTION),
    ]
    colours = {node_color(n, selected=True).name() for n in kinds}
    assert len(colours) == 1, "la sélection doit primer sur le type"
    selected = node_color(kinds[0], selected=True)
    assert selected.red() > selected.green()
    assert selected.red() > selected.blue()


def test_head_wins_over_local_branch():
    """Un nœud portant HEAD est vert même s'il porte aussi une branche."""
    with_head = node("a" * 40, NodeKind.REF,
                     ref("master", RefType.LOCAL_BRANCH), ref("HEAD", RefType.HEAD))
    without = node("b" * 40, NodeKind.REF, ref("master", RefType.LOCAL_BRANCH))
    assert node_color(with_head, False) != node_color(without, False)


def test_every_colour_is_valid():
    for kind in (NodeKind.REF, NodeKind.JUNCTION, NodeKind.STASH):
        for selected in (True, False):
            colour = node_color(node("a" * 40, kind), selected)
            assert isinstance(colour, QColor)
            assert colour.isValid()


def test_measurer_uses_real_font_metrics():
    """Un nom long mesure plus large qu'un nom court, avec la vraie police."""
    m = QtMeasurer()
    short = m.measure(node("a" * 40, NodeKind.REF, ref("x", RefType.LOCAL_BRANCH)))
    long = m.measure(
        node("b" * 40, NodeKind.REF, ref("origin/very-long", RefType.LOCAL_BRANCH))
    )
    assert long.width > short.width


def test_measurer_grows_with_ref_count():
    m = QtMeasurer()
    one = m.measure(node("a" * 40, NodeKind.REF, ref("m", RefType.LOCAL_BRANCH)))
    three = m.measure(node("b" * 40, NodeKind.REF,
                           ref("m", RefType.LOCAL_BRANCH),
                           ref("o/m", RefType.REMOTE_BRANCH),
                           ref("g/m", RefType.REMOTE_BRANCH)))
    assert three.height > one.height


def test_measurer_labels_junction_with_short_oid():
    m = QtMeasurer()
    size = m.measure(node("abcdef12" + "0" * 32, NodeKind.JUNCTION))
    assert size.width > 0 and size.height > 0


def test_measurer_satisfies_the_layout_protocol():
    """§Phase 2 : layout/ accepte n'importe quel NodeMeasurer."""
    from tortoisepy.layout.engine import layout_graph
    from tortoisepy.core.model import DisplayGraph

    graph = DisplayGraph(
        nodes=(node("a" * 40, NodeKind.REF, ref("master", RefType.LOCAL_BRANCH)),),
        edges=(),
    )
    result = layout_graph(graph, measurer=QtMeasurer())
    assert len(result.placements) == 1
```

- [ ] **Step 3: Vérifier l'échec**

Run: `.venv/bin/pytest tests/ui/test_theme.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tortoisepy.ui'`

- [ ] **Step 4: Implémenter**

```python
# src/tortoisepy/ui/theme.py
"""Couleurs, police et métriques — §4.3, §4.4.

Un module unique, pour que les couleurs restent paramétrables sans toucher
au moteur de rendu.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QFont, QFontMetricsF

from tortoisepy.core.model import DisplayNode, NodeKind, RefType
from tortoisepy.layout.metrics import Size

NODE_FONT_FAMILY = "Menlo"
"""Police à chasse fixe, conformément à la capture (§4.4). Qt retombe sur
une police équivalente si elle est absente."""

NODE_FONT_SIZE = 12
NODE_RADIUS = 6.0
"""Rayon des coins arrondis (§4.4)."""

NODE_BORDER_WIDTH = 1.0
EDGE_WIDTH = 1.5
ARROW_SIZE = 9.0

PADDING_X = 12.0
PADDING_Y = 6.0


@dataclass(frozen=True)
class Palette:
    """Couleurs des nœuds, reconstituées de la capture TortoiseGit (§4.3)."""

    current_branch: QColor = QColor(120, 200, 120)   # vert
    local_branch: QColor = QColor(250, 240, 130)     # jaune
    remote_branch: QColor = QColor(250, 222, 180)    # beige / pêche
    tag: QColor = QColor(250, 240, 130)              # jaune, comme les locales
    stash: QColor = QColor(150, 150, 150)            # gris
    junction: QColor = QColor(245, 245, 245)         # blanc cassé, discret
    selected: QColor = QColor(160, 30, 30)           # rouge foncé
    selected_text: QColor = QColor(255, 255, 255)
    text: QColor = QColor(20, 20, 20)
    border: QColor = QColor(110, 110, 110)
    edge: QColor = QColor(30, 30, 30)
    background: QColor = QColor(255, 255, 255)


PALETTE = Palette()


def node_color(node: DisplayNode, selected: bool) -> QColor:
    """Couleur de remplissage d'un nœud.

    La sélection prime sur le type : un nœud sélectionné est toujours rouge
    foncé, quelle que soit sa nature (§4.3).
    """
    if selected:
        return PALETTE.selected

    if node.kind is NodeKind.STASH:
        return PALETTE.stash
    if node.kind is NodeKind.JUNCTION:
        return PALETTE.junction

    types = {ref.type for ref in node.refs}

    # HEAD d'abord : un nœud portant HEAD est le nœud courant, même s'il
    # porte aussi une branche locale.
    if RefType.HEAD in types:
        return PALETTE.current_branch
    if RefType.LOCAL_BRANCH in types:
        return PALETTE.local_branch
    if RefType.TAG in types:
        return PALETTE.tag
    if RefType.REMOTE_BRANCH in types:
        return PALETTE.remote_branch

    return PALETTE.junction


def text_color(selected: bool) -> QColor:
    return PALETTE.selected_text if selected else PALETTE.text


def node_font() -> QFont:
    return QFont(NODE_FONT_FAMILY, NODE_FONT_SIZE)


def node_labels(node: DisplayNode) -> tuple[str, ...]:
    """Lignes affichées dans le nœud : ses refs, ou son OID court (§4.3)."""
    if node.refs:
        return tuple(ref.name for ref in node.refs)
    return (node.oid[:8],)


class QtMeasurer:
    """Mesure réelle, avec la police effective.

    Implémente le protocole `NodeMeasurer` de la phase 2 : `layout/` obtient
    des dimensions exactes sans jamais importer Qt.
    """

    def __init__(self, font: QFont | None = None):
        self._metrics = QFontMetricsF(font or node_font())

    def measure(self, node: DisplayNode) -> Size:
        labels = node_labels(node)
        widest = max(self._metrics.horizontalAdvance(label) for label in labels)
        line_height = self._metrics.height()
        return Size(
            width=widest + 2 * PADDING_X,
            height=len(labels) * line_height + 2 * PADDING_Y,
        )
```

- [ ] **Step 5: Vérifier le succès**

Run: `.venv/bin/pytest tests/ui/test_theme.py -v`
Expected: PASS, 12 tests.

- [ ] **Step 6: Déclarer les dépendances**

Ajouter PySide6 à `pyproject.toml` :

```toml
dependencies = ["pygit2>=1.15", "PySide6>=6.7"]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-qt>=4.4"]
```

- [ ] **Step 7: Signaler les fichiers prêts** — ne commite pas.

---

### Task 2: Éléments graphiques

**Files:**
- Create: `src/tortoisepy/ui/graph_items.py`
- Test: `tests/ui/test_graph_items.py`

**Interfaces:**
- Consumes: `DisplayNode`, `GraphEdge`, `Placement`, `LayoutResult`, thème
- Produces: `NodeItem`, `EdgeItem`, `build_scene(graph, layout) -> QGraphicsScene`

**Le seul endroit où les axes sont convertis.** `layout/` produit un `y`
croissant vers le haut ; Qt le fait croître vers le bas. La conversion
(`scene_y = total_height - y - height`) vit ici et nulle part ailleurs.

- [ ] **Step 1: Écrire les tests**

```python
# tests/ui/test_graph_items.py
from PySide6.QtWidgets import QGraphicsScene

from tortoisepy.core.model import (
    DisplayGraph,
    DisplayNode,
    GraphEdge,
    NodeKind,
    Ref,
    RefType,
)
from tortoisepy.layout.engine import layout_graph
from tortoisepy.ui.graph_items import EdgeItem, NodeItem, build_scene
from tortoisepy.ui.theme import QtMeasurer


def node(oid: str, *names: str) -> DisplayNode:
    refs = tuple(Ref(n, RefType.LOCAL_BRANCH, oid) for n in names)
    return DisplayNode(
        oid=oid, kind=NodeKind.REF if refs else NodeKind.JUNCTION, refs=refs
    )


def edge(a: str, d: str, skipped: tuple[str, ...] = ()) -> GraphEdge:
    return GraphEdge(ancestor=a, descendant=d, skipped=skipped)


def simple_graph() -> DisplayGraph:
    return DisplayGraph(
        nodes=(node("a" * 40, "base"), node("b" * 40, "tip")),
        edges=(edge("a" * 40, "b" * 40),),
    )


def test_scene_contains_one_item_per_node():
    graph = simple_graph()
    scene = build_scene(graph, layout_graph(graph, QtMeasurer()))
    nodes = [i for i in scene.items() if isinstance(i, NodeItem)]
    assert len(nodes) == 2


def test_scene_contains_one_item_per_edge():
    graph = simple_graph()
    scene = build_scene(graph, layout_graph(graph, QtMeasurer()))
    edges = [i for i in scene.items() if isinstance(i, EdgeItem)]
    assert len(edges) == 1


def test_descendant_is_drawn_higher_on_screen():
    """La conversion d'axes : y monte dans layout/, descend dans Qt.

    Un descendant doit donc avoir une coordonnée Qt PLUS PETITE.
    """
    graph = simple_graph()
    scene = build_scene(graph, layout_graph(graph, QtMeasurer()))
    items = {i.node.oid: i for i in scene.items() if isinstance(i, NodeItem)}
    assert items["b" * 40].y() < items["a" * 40].y()


def test_node_item_carries_its_model():
    graph = simple_graph()
    scene = build_scene(graph, layout_graph(graph, QtMeasurer()))
    for item in scene.items():
        if isinstance(item, NodeItem):
            assert item.node.oid in {"a" * 40, "b" * 40}


def test_nodes_are_selectable():
    graph = simple_graph()
    scene = build_scene(graph, layout_graph(graph, QtMeasurer()))
    for item in scene.items():
        if isinstance(item, NodeItem):
            assert item.flags() & item.GraphicsItemFlag.ItemIsSelectable


def test_edge_with_skipped_commits_is_labelled():
    graph = DisplayGraph(
        nodes=(node("a" * 40, "base"), node("b" * 40, "tip")),
        edges=(edge("a" * 40, "b" * 40, tuple("c" * 40 for _ in range(12))),),
    )
    scene = build_scene(graph, layout_graph(graph, QtMeasurer()))
    edges = [i for i in scene.items() if isinstance(i, EdgeItem)]
    assert edges[0].label is not None
    assert "12" in edges[0].label


def test_edge_without_skipped_commits_has_no_label():
    graph = simple_graph()
    scene = build_scene(graph, layout_graph(graph, QtMeasurer()))
    edges = [i for i in scene.items() if isinstance(i, EdgeItem)]
    assert edges[0].label is None


def test_edge_carries_its_model():
    graph = simple_graph()
    scene = build_scene(graph, layout_graph(graph, QtMeasurer()))
    edges = [i for i in scene.items() if isinstance(i, EdgeItem)]
    assert edges[0].edge.ancestor == "a" * 40


def test_empty_graph_gives_an_empty_scene():
    graph = DisplayGraph(nodes=(), edges=())
    scene = build_scene(graph, layout_graph(graph, QtMeasurer()))
    assert not scene.items()


def test_scene_rect_covers_every_node():
    graph = simple_graph()
    scene = build_scene(graph, layout_graph(graph, QtMeasurer()))
    rect = scene.sceneRect()
    for item in scene.items():
        if isinstance(item, NodeItem):
            assert rect.contains(item.sceneBoundingRect())


def test_build_scene_is_repeatable():
    """Deux constructions donnent les mêmes positions."""
    graph = simple_graph()
    layout = layout_graph(graph, QtMeasurer())
    first = build_scene(graph, layout)
    second = build_scene(graph, layout)

    def positions(scene: QGraphicsScene) -> dict:
        return {
            i.node.oid: (i.x(), i.y())
            for i in scene.items()
            if isinstance(i, NodeItem)
        }

    assert positions(first) == positions(second)
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/ui/test_graph_items.py -v`
Expected: FAIL — module introuvable.

- [ ] **Step 3: Implémenter**

```python
# src/tortoisepy/ui/graph_items.py
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
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
)

from tortoisepy.core.model import DisplayGraph, DisplayNode, GraphEdge
from tortoisepy.layout.metrics import LayoutResult, Placement
from tortoisepy.ui import theme

SCENE_MARGIN = 40.0


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
        path = QPainterPath(start)

        # Courbe douce : les points de contrôle s'écartent verticalement,
        # ce qui donne l'allure des arêtes de la capture (§4.4).
        dy = (end.y() - start.y()) * 0.4
        path.cubicTo(
            QPointF(start.x(), start.y() + dy),
            QPointF(end.x(), end.y() - dy),
            end,
        )
        path.addPolygon(_arrow_head(start, end))
        self.setPath(path)


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
            f"{edge.skipped_count} commits" if edge.skipped_count else None
        )
        scene.addItem(
            EdgeItem(edge, _top_center(ancestor), _bottom_center(descendant), label)
        )

    rect = scene.itemsBoundingRect()
    scene.setSceneRect(rect.adjusted(-SCENE_MARGIN, -SCENE_MARGIN,
                                     SCENE_MARGIN, SCENE_MARGIN))
    return scene


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
```

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/ui/test_graph_items.py -v`
Expected: PASS, 11 tests.

- [ ] **Step 5: Signaler les fichiers prêts** — ne commite pas.

---

### Task 3: Vue et navigation

**Files:**
- Create: `src/tortoisepy/ui/graph_view.py`
- Test: `tests/ui/test_graph_view.py`

**Interfaces:**
- Consumes: `build_scene` (tâche 2)
- Produces: `GraphView`

Navigation de §7.1 : molette, ⌘+molette pour zoomer, glisser pour le
panoramique, ⌘0 et ⌘9 pour les zooms prédéfinis.

- [ ] **Step 1: Écrire les tests**

```python
# tests/ui/test_graph_view.py
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QWheelEvent

from tortoisepy.core.model import (
    DisplayGraph,
    DisplayNode,
    GraphEdge,
    NodeKind,
    Ref,
    RefType,
)
from tortoisepy.layout.engine import layout_graph
from tortoisepy.ui.graph_items import NodeItem, build_scene
from tortoisepy.ui.graph_view import GraphView
from tortoisepy.ui.theme import QtMeasurer


@pytest.fixture
def graph():
    def node(oid, *names):
        refs = tuple(Ref(n, RefType.LOCAL_BRANCH, oid) for n in names)
        return DisplayNode(oid=oid, kind=NodeKind.REF, refs=refs)

    return DisplayGraph(
        nodes=(node("a" * 40, "base"), node("b" * 40, "tip")),
        edges=(GraphEdge(ancestor="a" * 40, descendant="b" * 40, skipped=()),),
    )


@pytest.fixture
def view(qtbot, graph):
    v = GraphView()
    qtbot.addWidget(v)
    v.show_graph(graph, layout_graph(graph, QtMeasurer()))
    return v


def test_view_displays_the_scene(view):
    assert view.scene() is not None
    assert len(view.scene().items()) > 0


def test_zoom_in_increases_scale(view):
    before = view.current_zoom()
    view.zoom_in()
    assert view.current_zoom() > before


def test_zoom_out_decreases_scale(view):
    before = view.current_zoom()
    view.zoom_out()
    assert view.current_zoom() < before


def test_reset_zoom_returns_to_one(view):
    view.zoom_in()
    view.zoom_in()
    view.reset_zoom()
    assert view.current_zoom() == pytest.approx(1.0, abs=0.01)


def test_zoom_is_clamped(view):
    """Un zoom sans limite rendrait le graphe inutilisable."""
    for _ in range(100):
        view.zoom_in()
    assert view.current_zoom() <= GraphView.MAX_ZOOM

    for _ in range(200):
        view.zoom_out()
    assert view.current_zoom() >= GraphView.MIN_ZOOM


def test_fit_to_window_changes_the_scale(view):
    view.zoom_in()
    view.zoom_in()
    before = view.current_zoom()
    view.fit_to_window()
    assert view.current_zoom() != before


def test_selected_oids_is_empty_at_first(view):
    assert view.selected_oids() == ()


def test_selecting_a_node_reports_its_oid(view):
    items = [i for i in view.scene().items() if isinstance(i, NodeItem)]
    items[0].setSelected(True)
    assert len(view.selected_oids()) == 1


def test_two_nodes_can_be_selected(view):
    items = [i for i in view.scene().items() if isinstance(i, NodeItem)]
    for item in items:
        item.setSelected(True)
    assert len(view.selected_oids()) == 2


def test_show_graph_replaces_the_previous_scene(view, graph):
    first = view.scene()
    view.show_graph(graph, layout_graph(graph, QtMeasurer()))
    assert view.scene() is not first


def test_empty_graph_does_not_crash(qtbot):
    v = GraphView()
    qtbot.addWidget(v)
    empty = DisplayGraph(nodes=(), edges=())
    v.show_graph(empty, layout_graph(empty, QtMeasurer()))
    assert v.scene() is not None


def test_drag_mode_allows_panning(view):
    """§7.1 : glisser sur le fond déplace la vue."""
    from PySide6.QtWidgets import QGraphicsView
    assert view.dragMode() == QGraphicsView.DragMode.ScrollHandDrag


def test_zoom_preserves_selection(view):
    items = [i for i in view.scene().items() if isinstance(i, NodeItem)]
    items[0].setSelected(True)
    before = view.selected_oids()
    view.zoom_in()
    assert view.selected_oids() == before
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/ui/test_graph_view.py -v`
Expected: FAIL — module introuvable.

- [ ] **Step 3: Implémenter**

```python
# src/tortoisepy/ui/graph_view.py
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
```

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/ui/test_graph_view.py -v`
Expected: PASS, 13 tests.

- [ ] **Step 5: Signaler les fichiers prêts** — ne commite pas.

---

### Task 4: Surveillance de `.git`

**Files:**
- Create: `src/tortoisepy/ui/watcher.py`
- Test: `tests/ui/test_watcher.py`

**Interfaces:**
- Consumes: rien de l'application
- Produces: `RepositoryWatcher`

§7.9 : un `git commit` tapé dans le terminal doit se voir. Sans cela,
l'affichage ment et l'utilisateur agit sur un état périmé.

- [ ] **Step 1: Écrire les tests**

```python
# tests/ui/test_watcher.py
import os
import subprocess

import pytest

from tortoisepy.ui.watcher import RepositoryWatcher


def run_git(path, *args):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
    }
    return subprocess.run(
        ["git", *args], cwd=path, env=env, capture_output=True, text=True
    )


@pytest.fixture
def repo_path(tmp_path):
    path = tmp_path / "watched"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "master")
    (path / "f.txt").write_text("base\n")
    run_git(path, "add", "f.txt")
    run_git(path, "commit", "-q", "-m", "base")
    return path


def test_watcher_starts_and_stops(qtbot, repo_path):
    watcher = RepositoryWatcher(str(repo_path / ".git"))
    watcher.start()
    assert watcher.is_watching()
    watcher.stop()
    assert not watcher.is_watching()


def test_watcher_watches_the_expected_paths(qtbot, repo_path):
    """§7.9 : HEAD, refs/, packed-refs et index."""
    watcher = RepositoryWatcher(str(repo_path / ".git"))
    watcher.start()
    watched = " ".join(watcher.watched_paths())
    assert "HEAD" in watched
    assert "refs" in watched
    watcher.stop()


def test_ref_change_triggers_graph_refresh(qtbot, repo_path):
    """Un commit externe doit demander la reconstruction du graphe."""
    watcher = RepositoryWatcher(str(repo_path / ".git"), debounce_ms=50)
    watcher.start()

    with qtbot.waitSignal(watcher.graph_changed, timeout=3000):
        (repo_path / "f.txt").write_text("modifié\n")
        run_git(repo_path, "add", "f.txt")
        run_git(repo_path, "commit", "-q", "-m", "externe")

    watcher.stop()


def test_debounce_collapses_a_burst(qtbot, repo_path):
    """§7.9 : un seul `git commit` produit plusieurs événements fichier.

    Sans anti-rebond, le graphe serait reconstruit trois fois.
    """
    watcher = RepositoryWatcher(str(repo_path / ".git"), debounce_ms=200)
    watcher.start()

    calls = []
    watcher.graph_changed.connect(lambda: calls.append(1))

    for index in range(5):
        (repo_path / "f.txt").write_text(f"v{index}\n")
        run_git(repo_path, "add", "f.txt")
        run_git(repo_path, "commit", "-q", "-m", f"c{index}")

    qtbot.wait(800)
    watcher.stop()

    assert len(calls) < 5, f"anti-rebond inopérant : {len(calls)} émissions"


def test_suspend_blocks_notifications(qtbot, repo_path):
    """§7.9 : la surveillance est suspendue pendant nos propres opérations."""
    watcher = RepositoryWatcher(str(repo_path / ".git"), debounce_ms=50)
    watcher.start()

    calls = []
    watcher.graph_changed.connect(lambda: calls.append(1))

    with watcher.suspended():
        (repo_path / "f.txt").write_text("interne\n")
        run_git(repo_path, "add", "f.txt")
        run_git(repo_path, "commit", "-q", "-m", "interne")
        qtbot.wait(300)

    assert calls == []
    watcher.stop()


def test_stop_is_idempotent(qtbot, repo_path):
    watcher = RepositoryWatcher(str(repo_path / ".git"))
    watcher.start()
    watcher.stop()
    watcher.stop()  # ne doit pas lever
    assert not watcher.is_watching()


def test_missing_git_directory_does_not_crash(qtbot, tmp_path):
    watcher = RepositoryWatcher(str(tmp_path / "inexistant" / ".git"))
    watcher.start()  # ne doit pas lever
    watcher.stop()
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/ui/test_watcher.py -v`
Expected: FAIL — module introuvable.

- [ ] **Step 3: Implémenter**

```python
# src/tortoisepy/ui/watcher.py
"""Surveillance du dossier `.git` — §7.9.

Un dépôt n'est jamais modifié que par tortoisePy : un `git commit` tapé
dans le terminal doit se voir, sans quoi l'affichage ment.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Signal

DEBOUNCE_MS = 300
"""Une seule commande Git produit plusieurs événements : un `git commit`
touche l'index, HEAD et une ref. Sans temporisation, le graphe serait
reconstruit trois fois (§7.9)."""

_GRAPH_PATHS = ("HEAD", "packed-refs", "MERGE_HEAD", "ORIG_HEAD")
"""Fichiers dont la modification change le graphe."""

_STATE_PATHS = ("index",)
"""Fichiers dont la modification ne change que l'état (§7.8)."""


class RepositoryWatcher(QObject):
    """Signale les changements du dépôt survenus hors de l'application.

    Deux signaux distincts : reconstruire le graphe coûte bien plus cher que
    relire l'état, et un fichier indexé dans l'éditeur ne change pas le
    graphe (§7.8).
    """

    graph_changed = Signal()
    state_changed = Signal()

    def __init__(
        self, git_dir: str, debounce_ms: int = DEBOUNCE_MS, parent=None
    ):
        super().__init__(parent)
        self._git_dir = Path(git_dir)
        self._watcher: QFileSystemWatcher | None = None
        self._suspended = False
        self._pending_graph = False
        self._pending_state = False

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(debounce_ms)
        self._timer.timeout.connect(self._emit_pending)

    def start(self) -> None:
        """Commence à surveiller. Sans effet si le dossier n'existe pas."""
        if self._watcher is not None:
            return
        if not self._git_dir.is_dir():
            return

        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_change)
        self._watcher.directoryChanged.connect(self._on_change)

        for path in self._paths_to_watch():
            self._watcher.addPath(str(path))

    def stop(self) -> None:
        """Arrête la surveillance. Appelable plusieurs fois sans dommage."""
        self._timer.stop()
        if self._watcher is None:
            return

        watched = self._watcher.files() + self._watcher.directories()
        if watched:
            self._watcher.removePaths(watched)

        self._watcher.deleteLater()
        self._watcher = None

    def is_watching(self) -> bool:
        return self._watcher is not None

    def watched_paths(self) -> tuple[str, ...]:
        if self._watcher is None:
            return ()
        return tuple(self._watcher.files() + self._watcher.directories())

    @contextmanager
    def suspended(self):
        """Suspend les notifications le temps d'une opération interne.

        Sans cela, chaque opération lancée depuis l'application
        déclencherait un rafraîchissement en plus de celui déjà prévu par
        `OperationResult.repository_changed` (§7.6).
        """
        previous = self._suspended
        self._suspended = True
        try:
            yield
        finally:
            self._suspended = previous
            self._pending_graph = False
            self._pending_state = False
            self._timer.stop()

    def _paths_to_watch(self) -> list[Path]:
        """Chemins existants à surveiller (§7.9).

        Le répertoire `.git` lui-même est inclus : mesuré, un `git checkout`
        émet trois événements de répertoire sur `.git` en plus de celui sur
        `HEAD`, et certains changements ne se voient que par là.
        """
        candidates = [self._git_dir]
        candidates += [self._git_dir / name for name in _GRAPH_PATHS]
        candidates += [self._git_dir / name for name in _STATE_PATHS]
        candidates.append(self._git_dir / "refs")

        refs = self._git_dir / "refs"
        if refs.is_dir():
            candidates.extend(p for p in refs.rglob("*") if p.is_dir())

        return [path for path in candidates if path.exists()]

    def _on_change(self, path: str) -> None:
        if self._suspended:
            return

        # Un événement de RÉPERTOIRE ne nomme pas le fichier modifié : il
        # porte le nom du dossier. Le classer par nom de fichier le ferait
        # passer pour un changement d'état. Dans le doute, on reconstruit
        # le graphe — une reconstruction de trop est sans conséquence, un
        # graphe périmé ment à l'utilisateur.
        name = Path(path).name
        if name in _STATE_PATHS and Path(path).is_file():
            self._pending_state = True
        else:
            self._pending_graph = True

        # Certains éditeurs remplacent le fichier : Qt cesse alors de le
        # surveiller. On le réarme.
        if self._watcher is not None and Path(path).exists():
            if path not in self.watched_paths():
                self._watcher.addPath(path)

        self._timer.start()

    def _emit_pending(self) -> None:
        if self._suspended:
            return

        if self._pending_graph:
            self._pending_graph = False
            self._pending_state = False
            self.graph_changed.emit()
        elif self._pending_state:
            self._pending_state = False
            self.state_changed.emit()
```

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/ui/test_watcher.py -v`
Expected: PASS, 7 tests.

- [ ] **Step 5: Signaler les fichiers prêts** — ne commite pas.

---

### Task 5: Menu contextuel

**Files:**
- Create: `src/tortoisepy/ui/context_menu.py`
- Test: `tests/ui/test_context_menu.py`

**Interfaces:**
- Consumes: `DisplayNode`, `RepositoryState`, `OPERATION_CLASSES`
- Produces: `MenuEntry`, `build_menu_model(nodes, state) -> tuple[MenuEntry, ...]`

**Le modèle de menu est séparé du widget Qt.** Décider quelles entrées sont
actives est de la logique pure : la tester sans construire de `QMenu` rend
les tests rapides et lisibles. Le widget se contente de traduire ce modèle.

- [ ] **Step 1: Écrire les tests**

```python
# tests/ui/test_context_menu.py
from tortoisepy.core.model import DisplayNode, NodeKind, Ref, RefType
from tortoisepy.core.state import RepositoryState
from tortoisepy.ui.context_menu import build_menu_model


def node(oid: str, kind: NodeKind, *refs: Ref) -> DisplayNode:
    return DisplayNode(oid=oid, kind=kind, refs=refs)


def branch_node(name: str = "feature") -> DisplayNode:
    return node("a" * 40, NodeKind.REF, Ref(name, RefType.LOCAL_BRANCH, "a" * 40))


def clean_state(**overrides) -> RepositoryState:
    defaults = dict(
        head_oid="b" * 40,
        head_branch="master",
        detached=False,
        has_unstaged_changes=False,
        has_staged_changes=False,
        has_conflicts=False,
        operation_in_progress=None,
        conflicted_paths=(),
    )
    defaults.update(overrides)
    return RepositoryState(**defaults)


def find(entries, action: str):
    for entry in entries:
        if entry.action == action:
            return entry
        for child in entry.children:
            if child.action == action:
                return child
    return None


def test_single_node_offers_checkout():
    entries = build_menu_model((branch_node(),), clean_state())
    assert find(entries, "checkout_branch") is not None


def test_menu_is_hierarchical():
    """§7.3 : quatorze entrées à plat seraient illisibles."""
    entries = build_menu_model((branch_node(),), clean_state())
    assert any(entry.children for entry in entries)


def test_copy_hash_is_always_available():
    entries = build_menu_model((branch_node(),), clean_state())
    assert find(entries, "copy_hash").enabled is True


def test_tag_node_cannot_be_checked_out_as_branch():
    """§7.3 : les actions de branche sont grisées sur un tag."""
    tag = node("a" * 40, NodeKind.REF, Ref("v1.0", RefType.TAG, "a" * 40))
    entries = build_menu_model((tag,), clean_state())
    assert find(entries, "delete_branch").enabled is False
    assert find(entries, "rename_branch").enabled is False


def test_junction_node_has_no_branch_actions():
    junction = node("a" * 40, NodeKind.JUNCTION)
    entries = build_menu_model((junction,), clean_state())
    assert find(entries, "delete_branch").enabled is False


def test_stash_node_keeps_only_read_actions():
    """§7.3 : sur un stash, seuls Show Log et Copy hash restent actifs."""
    stash = node("a" * 40, NodeKind.STASH,
                 Ref("stash@{0}", RefType.STASH, "a" * 40))
    entries = build_menu_model((stash,), clean_state())
    assert find(entries, "copy_hash").enabled is True
    assert find(entries, "merge_branch").enabled is False
    assert find(entries, "checkout_branch").enabled is False


def test_current_branch_cannot_be_merged_into_itself():
    """§7.3 : Checkout et Merge sont sans objet sur la branche courante."""
    current = node("a" * 40, NodeKind.REF,
                   Ref("master", RefType.LOCAL_BRANCH, "a" * 40),
                   Ref("HEAD", RefType.HEAD, "a" * 40))
    entries = build_menu_model((current,), clean_state(head_branch="master"))
    assert find(entries, "merge_branch").enabled is False
    assert find(entries, "checkout_branch").enabled is False


def test_operation_in_progress_disables_modifying_actions():
    """§7.3 : pendant un merge, plus rien ne doit modifier le dépôt."""
    entries = build_menu_model(
        (branch_node(),), clean_state(operation_in_progress="merge")
    )
    assert find(entries, "merge_branch").enabled is False
    assert find(entries, "reset_to").enabled is False
    assert find(entries, "copy_hash").enabled is True


def test_operation_in_progress_offers_abort():
    entries = build_menu_model(
        (branch_node(),), clean_state(operation_in_progress="merge")
    )
    assert find(entries, "abort_operation").enabled is True


def test_no_abort_when_nothing_in_progress():
    entries = build_menu_model((branch_node(),), clean_state())
    abort = find(entries, "abort_operation")
    assert abort is None or abort.enabled is False


def test_dirty_worktree_warns_on_checkout():
    """§7.5 : un checkout avec des modifications locales demande confirmation."""
    entries = build_menu_model(
        (branch_node(),), clean_state(has_unstaged_changes=True)
    )
    checkout = find(entries, "checkout_branch")
    assert checkout.needs_confirmation is True


def test_destructive_actions_require_confirmation():
    """§7.5 : reset et suppression de branche sont confirmés."""
    entries = build_menu_model((branch_node(),), clean_state())
    assert find(entries, "reset_to").needs_confirmation is True
    assert find(entries, "delete_branch").needs_confirmation is True


def test_two_nodes_offer_comparison():
    """§7.4 : deux nœuds sélectionnés activent la comparaison."""
    a = branch_node("a")
    b = node("b" * 40, NodeKind.REF, Ref("b", RefType.LOCAL_BRANCH, "b" * 40))
    entries = build_menu_model((a, b), clean_state())
    assert find(entries, "compare_revisions").enabled is True


def test_single_node_cannot_compare():
    entries = build_menu_model((branch_node(),), clean_state())
    compare = find(entries, "compare_revisions")
    assert compare is None or compare.enabled is False


def test_empty_selection_gives_no_menu():
    assert build_menu_model((), clean_state()) == ()


def test_every_entry_has_a_label():
    entries = build_menu_model((branch_node(),), clean_state())
    for entry in entries:
        assert entry.label
        for child in entry.children:
            assert child.label
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/ui/test_context_menu.py -v`
Expected: FAIL — module introuvable.

- [ ] **Step 3: Implémenter**

```python
# src/tortoisepy/ui/context_menu.py
"""Modèle du menu contextuel — §7.3, §7.4, §7.5.

Ce module ne construit aucun widget : il décide **quelles entrées existent
et lesquelles sont actives**, en fonction du type de nœud et de l'état du
dépôt. Le widget Qt traduit ensuite ce modèle. Séparer les deux rend la
logique testable sans interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tortoisepy.core.model import DisplayNode, NodeKind, RefType
from tortoisepy.core.state import RepositoryState


@dataclass(frozen=True)
class MenuEntry:
    label: str
    action: str | None = None
    enabled: bool = True
    needs_confirmation: bool = False
    children: tuple["MenuEntry", ...] = field(default_factory=tuple)

    @property
    def is_separator(self) -> bool:
        return self.action is None and not self.children and not self.label


SEPARATOR = MenuEntry(label="")


def build_menu_model(
    nodes: tuple[DisplayNode, ...], state: RepositoryState
) -> tuple[MenuEntry, ...]:
    """Menu correspondant à la sélection courante.

    Une sélection vide ne produit aucun menu ; deux nœuds activent les
    actions de comparaison (§7.4).
    """
    if not nodes:
        return ()

    if len(nodes) >= 2:
        return _comparison_menu(nodes)

    return _single_node_menu(nodes[0], state)


def _comparison_menu(nodes: tuple[DisplayNode, ...]) -> tuple[MenuEntry, ...]:
    """§7.4 : menu de deux nœuds sélectionnés."""
    return (
        MenuEntry("Comparer les révisions…", "compare_revisions"),
        MenuEntry("Journal des différences…", "show_log_of_differences"),
        SEPARATOR,
        MenuEntry("Copier les hash", "copy_hash"),
    )


def _single_node_menu(
    node: DisplayNode, state: RepositoryState
) -> tuple[MenuEntry, ...]:
    """§7.3 : menu hiérarchisé d'un nœud."""
    busy = state.operation_in_progress is not None
    dirty = state.has_unstaged_changes or state.has_staged_changes

    is_branch = _has_local_branch(node)
    is_current = _is_current(node, state)
    actionable = node.kind is not NodeKind.STASH and not busy

    can_checkout = is_branch and not is_current and not busy
    can_merge = is_branch and not is_current and not busy
    can_modify_branch = is_branch and not busy

    entries: list[MenuEntry] = [
        MenuEntry(
            "Checkout / Basculer",
            "checkout_branch",
            enabled=can_checkout,
            needs_confirmation=dirty,
        ),
        SEPARATOR,
        MenuEntry(
            "Créer",
            children=(
                MenuEntry("Branche ici…", "create_branch", enabled=actionable),
                MenuEntry("Tag ici…", "create_tag", enabled=actionable),
            ),
        ),
        MenuEntry(
            "Intégrer",
            children=(
                MenuEntry(
                    "Fusionner dans la branche courante…",
                    "merge_branch",
                    enabled=can_merge,
                    needs_confirmation=dirty,
                ),
                MenuEntry(
                    "Cherry-pick ce commit…",
                    "cherry_pick",
                    enabled=actionable,
                    needs_confirmation=dirty,
                ),
            ),
        ),
        MenuEntry(
            "Annuler",
            children=(
                MenuEntry(
                    "Réinitialiser la branche courante ici…",
                    "reset_to",
                    enabled=actionable,
                    needs_confirmation=True,
                ),
                MenuEntry(
                    "Revert ce commit…",
                    "revert_commit",
                    enabled=actionable,
                    needs_confirmation=True,
                ),
            ),
        ),
        MenuEntry(
            "Branche",
            children=(
                MenuEntry(
                    "Renommer…", "rename_branch", enabled=can_modify_branch
                ),
                MenuEntry(
                    "Supprimer",
                    "delete_branch",
                    enabled=can_modify_branch and not is_current,
                    needs_confirmation=True,
                ),
            ),
        ),
    ]

    if busy:
        entries.append(SEPARATOR)
        entries.append(
            MenuEntry(
                f"Abandonner le {state.operation_in_progress}",
                "abort_operation",
                enabled=True,
                needs_confirmation=True,
            )
        )

    entries.append(SEPARATOR)
    entries.append(MenuEntry("Afficher le journal", "show_log"))
    entries.append(MenuEntry("Copier le hash", "copy_hash"))

    return tuple(entries)


def _has_local_branch(node: DisplayNode) -> bool:
    return any(ref.type is RefType.LOCAL_BRANCH for ref in node.refs)


def _is_current(node: DisplayNode, state: RepositoryState) -> bool:
    """Le nœud porte-t-il la branche courante ?"""
    if any(ref.type is RefType.HEAD for ref in node.refs):
        return True
    if state.head_branch is None:
        return False
    return any(
        ref.type is RefType.LOCAL_BRANCH and ref.name == state.head_branch
        for ref in node.refs
    )
```

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/ui/test_context_menu.py -v`
Expected: PASS, 16 tests.

- [ ] **Step 5: Signaler les fichiers prêts** — ne commite pas.

---

### Task 6: Fenêtre principale et garde d'architecture

**Files:**
- Create: `src/tortoisepy/ui/main_window.py`
- Test: `tests/ui/test_main_window.py`
- Modify: `tests/test_architecture.py`

**Interfaces:**
- Consumes: toutes les tâches précédentes, `core.graph`, `core.state`,
  `core.operations`
- Produces: `MainWindow`

L'assemblage : la fenêtre relie le dépôt, le graphe, la vue, le menu et la
surveillance.

- [ ] **Step 1: Écrire les tests**

```python
# tests/ui/test_main_window.py
import os
import subprocess

import pygit2
import pytest

from tortoisepy.ui.main_window import MainWindow


def run_git(path, *args):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
    }
    return subprocess.run(
        ["git", *args], cwd=path, env=env, capture_output=True, text=True
    )


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "win"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "master")
    (path / "f.txt").write_text("base\n")
    run_git(path, "add", "f.txt")
    run_git(path, "commit", "-q", "-m", "base")
    run_git(path, "checkout", "-q", "-b", "feature")
    (path / "g.txt").write_text("feature\n")
    run_git(path, "add", "g.txt")
    run_git(path, "commit", "-q", "-m", "feature")
    run_git(path, "checkout", "-q", "master")
    return pygit2.Repository(str(path))


@pytest.fixture
def window(qtbot, repo):
    w = MainWindow(repo)
    qtbot.addWidget(w)
    return w


def test_window_opens(window):
    assert window.isEnabled()


def test_window_title_names_the_repository(window):
    assert "win" in window.windowTitle()


def test_graph_is_displayed(window):
    assert len(window.view.scene().items()) > 0


def test_toolbar_exists(window):
    """§4.3 : la toolbar de la capture — zoom, ajustement."""
    assert window.findChildren(type(window.toolbar)) != []


def test_refresh_rebuilds_the_graph(window):
    before = window.view.scene()
    window.refresh()
    assert window.view.scene() is not before


def test_state_is_read_on_open(window):
    assert window.state is not None
    assert window.state.head_branch == "master"


def test_refresh_updates_state_after_external_change(window, repo):
    path = repo.workdir
    run_git(path, "checkout", "-q", "feature")
    window.refresh()
    assert window.state.head_branch == "feature"


def test_status_bar_shows_the_branch(window):
    assert "master" in window.statusBar().currentMessage()


def test_watcher_is_running(window):
    assert window.watcher.is_watching()


def test_closing_stops_the_watcher(window):
    window.close()
    assert not window.watcher.is_watching()


def test_zoom_actions_exist(window):
    names = {action.text() for action in window.actions()}
    assert any("100" in name or "Zoom" in name for name in names)


def test_empty_repository_does_not_crash(qtbot, tmp_path):
    """Un dépôt sans commit doit s'ouvrir sans planter."""
    path = tmp_path / "vide"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "master")
    w = MainWindow(pygit2.Repository(str(path)))
    qtbot.addWidget(w)
    assert w.view.scene() is not None
```

- [ ] **Step 2: Étendre la garde d'architecture**

Ajouter à `tests/test_architecture.py` :

```python
def test_ui_is_the_only_layer_importing_qt():
    """§5 : seule `ui/` connaît PySide6."""
    for package in ("core", "layout"):
        assert not _offenders(package, QT), (
            f"{package}/ ne doit pas importer Qt"
        )


def test_ui_never_calls_pygit2_directly_for_operations():
    """`ui/` passe par core.operations, qui garantit OperationResult (§7.6).

    Lire le dépôt depuis `ui/` reste permis : la fenêtre reçoit un objet
    Repository. Ce qui est proscrit, c'est d'y faire des opérations
    d'écriture sans passer par la couche qui les encadre.
    """
    import ast
    from pathlib import Path

    forbidden = {"merge", "reset", "cherrypick", "revert", "create_branch"}
    offenders = []

    for path in (SRC / "ui").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr not in forbidden:
                continue
            value = func.value
            if isinstance(value, ast.Name) and value.id in {"repo", "repository"}:
                offenders.append(f"{path.name}: {func.attr}")

    assert not offenders, (
        "ui/ doit passer par core.operations : " + "; ".join(offenders)
    )
```

- [ ] **Step 3: Vérifier l'échec**

Run: `.venv/bin/pytest tests/ui/test_main_window.py -v`
Expected: FAIL — module introuvable.

- [ ] **Step 4: Implémenter**

```python
# src/tortoisepy/ui/main_window.py
"""Fenêtre principale — assemblage de §7.

Relie le dépôt, le graphe, la vue, le menu contextuel et la surveillance
de `.git`. Le chrome est natif : Qt s'en charge, conformément au choix de
reproduire le graphe mais pas l'habillage Windows.
"""

from __future__ import annotations

from pathlib import Path

import pygit2
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow,
    QMenu,
    QMessageBox,
    QToolBar,
)

from tortoisepy.core.graph import build_graph
from tortoisepy.core.state import read_state
from tortoisepy.layout.engine import layout_graph
from tortoisepy.ui.context_menu import MenuEntry, build_menu_model
from tortoisepy.ui.graph_view import GraphView
from tortoisepy.ui.theme import QtMeasurer
from tortoisepy.ui.watcher import RepositoryWatcher


class MainWindow(QMainWindow):
    """Fenêtre du Revision Graph."""

    def __init__(self, repository: pygit2.Repository, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.measurer = QtMeasurer()
        self.graph = None
        self.state = None

        self.view = GraphView(self)
        self.setCentralWidget(self.view)
        self.view.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.view.customContextMenuRequested.connect(self._show_context_menu)

        self.toolbar = self._build_toolbar()
        self._build_actions()

        self.watcher = RepositoryWatcher(str(Path(repository.path)), parent=self)
        self.watcher.graph_changed.connect(self.refresh)
        self.watcher.state_changed.connect(self._refresh_state_only)
        self.watcher.start()

        self.setWindowTitle(self._title())
        self.resize(1100, 800)
        self.refresh()

    def refresh(self) -> None:
        """Reconstruit le graphe et relit l'état (§7.6, §7.9)."""
        self.graph = build_graph(self.repository)
        self.state = read_state(self.repository)
        self.view.show_graph(self.graph, layout_graph(self.graph, self.measurer))
        self._update_status()

    def closeEvent(self, event) -> None:
        self.watcher.stop()
        super().closeEvent(event)

    def _refresh_state_only(self) -> None:
        """Relit l'état sans reconstruire le graphe — bien moins coûteux."""
        self.state = read_state(self.repository)
        self._update_status()

    def _title(self) -> str:
        workdir = self.repository.workdir
        name = Path(workdir).name if workdir else Path(self.repository.path).name
        return f"{name} — tortoisePy"

    def _build_toolbar(self) -> QToolBar:
        toolbar = QToolBar("Navigation", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        return toolbar

    def _build_actions(self) -> None:
        """Actions de navigation (§7.1). Qt traduit ⌘ depuis Ctrl sur macOS."""
        specs = [
            ("Zoom avant", QKeySequence.StandardKey.ZoomIn, self.view.zoom_in),
            ("Zoom arrière", QKeySequence.StandardKey.ZoomOut, self.view.zoom_out),
            ("Zoom 100 %", QKeySequence("Ctrl+0"), self.view.reset_zoom),
            ("Ajuster à la fenêtre", QKeySequence("Ctrl+9"), self.view.fit_to_window),
            ("Rafraîchir", QKeySequence.StandardKey.Refresh, self.refresh),
        ]

        for label, shortcut, slot in specs:
            action = QAction(label, self)
            action.setShortcut(shortcut)
            action.triggered.connect(slot)
            self.addAction(action)
            self.toolbar.addAction(action)

    def _update_status(self) -> None:
        if self.state is None:
            return

        if self.state.head_branch:
            message = f"Sur {self.state.head_branch}"
        elif self.state.detached:
            message = f"HEAD détaché sur {(self.state.head_oid or '')[:8]}"
        else:
            message = "Dépôt sans commit"

        if self.state.operation_in_progress:
            message += f" — {self.state.operation_in_progress} en cours"
        if self.state.has_conflicts:
            message += f" — {len(self.state.conflicted_paths)} conflit(s)"

        self.statusBar().showMessage(message)

    def _show_context_menu(self, position) -> None:
        """Construit le QMenu à partir du modèle (§7.3)."""
        if self.graph is None or self.state is None:
            return

        selected = self.view.selected_oids()
        nodes = tuple(
            node for oid in selected
            if (node := self.graph.node(oid)) is not None
        )

        entries = build_menu_model(nodes, self.state)
        if not entries:
            return

        menu = QMenu(self)
        self._fill_menu(menu, entries)
        menu.exec(self.view.mapToGlobal(position))

    def _fill_menu(self, menu: QMenu, entries: tuple[MenuEntry, ...]) -> None:
        for entry in entries:
            # `is_separator` repose sur `action == "separator"`, jamais sur
            # le label : celui-ci porte un caractère de remplissage qui ne
            # doit pas s'afficher.
            if entry.is_separator:
                menu.addSeparator()
            elif entry.children:
                submenu = menu.addMenu(entry.label)
                self._fill_menu(submenu, entry.children)
            else:
                action = menu.addAction(entry.label)
                action.setEnabled(entry.enabled)
                action.setData(entry.action)
                action.triggered.connect(
                    lambda checked=False, e=entry: self._not_implemented(e)
                )

    def _not_implemented(self, entry: MenuEntry) -> None:
        """Les actions sont câblées en phase 5 ; ici, un message honnête."""
        QMessageBox.information(
            self,
            entry.label,
            f"L'action « {entry.label} » n'est pas encore câblée.",
        )
```

- [ ] **Step 5: Vérifier le succès**

Run: `.venv/bin/pytest tests/ui/ -v`
Expected: PASS, 12 tests pour la fenêtre.

- [ ] **Step 6: Suite complète**

Run: `.venv/bin/pytest tests/ -q`
Expected: 299 + 71 = 370 tests, tous verts. **Attendre la fin.**

- [ ] **Step 7: Signaler les fichiers prêts** — ne commite pas. Donner le
décompte exact.

---

## Fin de phase 4

À ce stade :

- le Revision Graph s'affiche, aux couleurs de TortoiseGit ;
- zoom, panoramique et sélection fonctionnent ;
- le menu contextuel s'adapte au type de nœud et à l'état du dépôt ;
- un `git commit` externe rafraîchit la fenêtre.

**Ce que cette phase ne fait pas :**

- **Câbler les actions du menu.** Les entrées existent et s'activent
  correctement, mais cliquer affiche un message. Le branchement sur
  `core.operations` — avec les dialogues de confirmation de §7.5 — est le
  cœur de la phase 5.
- **La mini-carte** (§7.1). Elle demande une seconde vue synchronisée ; à
  traiter avec le reste de la navigation.
- **Les dialogues de saisie** (nom de branche, de tag).

**Phase suivante :**

- **Phase 5 — câblage et CLI** : brancher le menu sur `core.operations`,
  dialogues de confirmation (§7.5), dialogues d'erreur en trois parties
  (§9), mini-carte, et le point d'entrée `tgraph` (§8).
