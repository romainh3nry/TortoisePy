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
