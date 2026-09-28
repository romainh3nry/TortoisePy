from tortoisepy.core.model import (
    DisplayGraph,
    DisplayNode,
    GraphEdge,
    NodeKind,
    Ref,
    RefType,
)
from tortoisepy.layout.engine import layout_graph


def n(oid: str, *names: str) -> DisplayNode:
    refs = tuple(Ref(x, RefType.LOCAL_BRANCH, oid) for x in names)
    return DisplayNode(
        oid=oid,
        kind=NodeKind.REF if refs else NodeKind.JUNCTION,
        refs=refs,
    )


def e(a: str, d: str) -> GraphEdge:
    return GraphEdge(ancestor=a, descendant=d, skipped=())


def test_empty_graph_yields_empty_layout():
    result = layout_graph(DisplayGraph(nodes=(), edges=()))
    assert result.placements == ()
    assert result.width == 0.0
    assert result.height == 0.0


def test_every_node_is_placed():
    g = DisplayGraph(
        nodes=(n("a", "master"), n("b", "dev"), n("c")),
        edges=(e("a", "b"), e("b", "c")),
    )
    result = layout_graph(g)
    assert {p.oid for p in result.placements} == {"a", "b", "c"}


def test_descendant_sits_above_ancestor():
    """L'invariant central de §10.4, avec y croissant vers le haut."""
    g = DisplayGraph(
        nodes=(n("a", "old"), n("b", "new")),
        edges=(e("a", "b"),),
    )
    result = layout_graph(g)
    assert result.placement("b").y > result.placement("a").y


def test_no_two_nodes_overlap():
    """§10.4 : aucun chevauchement."""
    g = DisplayGraph(
        nodes=(n("base"), n("x", "feature"), n("y", "other"),
               n("z", "third"), n("w", "fourth")),
        edges=(e("base", "x"), e("base", "y"), e("base", "z"), e("base", "w")),
    )
    result = layout_graph(g)
    placements = result.placements
    for i, p in enumerate(placements):
        for q in placements[i + 1:]:
            separated = (
                p.right <= q.left or q.right <= p.left
                or p.top <= q.bottom or q.top <= p.bottom
            )
            assert separated, f"{p.oid} chevauche {q.oid}"


def test_wider_node_gets_more_room():
    """Un nom long ne doit pas déborder sur son voisin."""
    g = DisplayGraph(
        nodes=(n("base"),
               n("x", "a-very-long-branch-name-indeed"),
               n("y", "s")),
        edges=(e("base", "x"), e("base", "y")),
    )
    result = layout_graph(g)
    px, py = result.placement("x"), result.placement("y")
    assert px.right <= py.left or py.right <= px.left


def test_disconnected_components_do_not_overlap():
    """§10.4 : historiques indépendants côte à côte."""
    g = DisplayGraph(
        nodes=(n("a1", "first"), n("a2", "first-tip"),
               n("b1", "second"), n("b2", "second-tip")),
        edges=(e("a1", "a2"), e("b1", "b2")),
    )
    result = layout_graph(g)
    a = [result.placement(o) for o in ("a1", "a2")]
    b = [result.placement(o) for o in ("b1", "b2")]
    a_right = max(p.right for p in a)
    b_left = min(p.left for p in b)
    b_right = max(p.right for p in b)
    a_left = min(p.left for p in a)
    assert a_right <= b_left or b_right <= a_left


def test_bounds_cover_every_placement():
    g = DisplayGraph(
        nodes=(n("a", "x"), n("b", "y")),
        edges=(e("a", "b"),),
    )
    result = layout_graph(g)
    assert result.width >= max(p.right for p in result.placements)
    assert result.height >= max(p.top for p in result.placements)


def test_layout_is_deterministic():
    """§10.4 : même dépôt → même layout."""
    g = DisplayGraph(
        nodes=(n("base"), n("x", "a"), n("y", "b"), n("m", "merge")),
        edges=(e("base", "x"), e("base", "y"), e("x", "m"), e("y", "m")),
    )
    first = layout_graph(g)
    second = layout_graph(g)
    assert first.placements == second.placements
    assert (first.width, first.height) == (second.width, second.height)


def test_all_edges_point_upward():
    g = DisplayGraph(
        nodes=(n("base"), n("l", "left"), n("r", "right"), n("m", "merge")),
        edges=(e("base", "l"), e("base", "r"), e("l", "m"), e("r", "m")),
    )
    result = layout_graph(g)
    for edge in g.edges:
        assert result.placement(edge.descendant).y > result.placement(edge.ancestor).y
