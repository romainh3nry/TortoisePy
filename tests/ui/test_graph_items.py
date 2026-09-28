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


def test_single_skipped_commit_label_is_singular():
    """« 1 commit », pas « 1 commits »."""
    graph = DisplayGraph(
        nodes=(node("a" * 40, "base"), node("b" * 40, "tip")),
        edges=(edge("a" * 40, "b" * 40, ("c" * 40,)),),
    )
    scene = build_scene(graph, layout_graph(graph, QtMeasurer()))
    edges = [i for i in scene.items() if isinstance(i, EdgeItem)]
    assert edges[0].label == "1 commit"


def test_several_skipped_commits_label_is_plural():
    graph = DisplayGraph(
        nodes=(node("a" * 40, "base"), node("b" * 40, "tip")),
        edges=(edge("a" * 40, "b" * 40, tuple("c" * 40 for _ in range(3))),),
    )
    scene = build_scene(graph, layout_graph(graph, QtMeasurer()))
    edges = [i for i in scene.items() if isinstance(i, EdgeItem)]
    assert edges[0].label == "3 commits"
