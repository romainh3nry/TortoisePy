from tortoisepy.core.model import (
    DisplayGraph,
    DisplayNode,
    GraphEdge,
    NodeKind,
)
from tortoisepy.layout.ranking import compute_ranks


def n(oid: str) -> DisplayNode:
    return DisplayNode(oid=oid, kind=NodeKind.JUNCTION, refs=())


def e(a: str, d: str) -> GraphEdge:
    return GraphEdge(ancestor=a, descendant=d, skipped=())


def graph(oids: list[str], edges: list[GraphEdge]) -> DisplayGraph:
    return DisplayGraph(nodes=tuple(n(o) for o in oids), edges=tuple(edges))


def test_single_node_is_rank_zero():
    assert compute_ranks(graph(["a"], [])) == {"a": 0}


def test_chain_increments_rank():
    ranks = compute_ranks(graph(["a", "b", "c"], [e("a", "b"), e("b", "c")]))
    assert ranks == {"a": 0, "b": 1, "c": 2}


def test_diverged_branches_share_a_rank():
    """Deux branches issues du même point sont au même niveau."""
    ranks = compute_ranks(graph(["base", "x", "y"], [e("base", "x"), e("base", "y")]))
    assert ranks["x"] == ranks["y"] == 1


def test_longest_path_wins_not_shortest():
    """a→d directement ET a→b→c→d : d doit être au rang 3, pas 1."""
    edges = [e("a", "b"), e("b", "c"), e("c", "d"), e("a", "d")]
    ranks = compute_ranks(graph(["a", "b", "c", "d"], edges))
    assert ranks["d"] == 3


def test_merge_sits_above_both_parents():
    edges = [e("base", "l"), e("base", "r"), e("l", "m"), e("r", "m")]
    ranks = compute_ranks(graph(["base", "l", "r", "m"], edges))
    assert ranks["m"] > ranks["l"]
    assert ranks["m"] > ranks["r"]


def test_every_edge_goes_up():
    """L'invariant central de §10.4."""
    edges = [e("a", "b"), e("a", "c"), e("b", "d"), e("c", "d"), e("d", "x")]
    g = graph(["a", "b", "c", "d", "x"], edges)
    ranks = compute_ranks(g)
    for edge in g.edges:
        assert ranks[edge.ancestor] < ranks[edge.descendant]


def test_disconnected_components_both_start_at_zero():
    edges = [e("a1", "a2"), e("b1", "b2")]
    ranks = compute_ranks(graph(["a1", "a2", "b1", "b2"], edges))
    assert ranks["a1"] == 0
    assert ranks["b1"] == 0


def test_isolated_node_is_rank_zero():
    ranks = compute_ranks(graph(["a", "b", "lone"], [e("a", "b")]))
    assert ranks["lone"] == 0


def test_empty_graph():
    assert compute_ranks(DisplayGraph(nodes=(), edges=())) == {}


def test_is_deterministic():
    edges = [e("a", "b"), e("a", "c"), e("b", "d"), e("c", "d")]
    g = graph(["a", "b", "c", "d"], edges)
    assert compute_ranks(g) == compute_ranks(g)
