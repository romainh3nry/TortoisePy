from tortoisepy.core.model import GraphEdge
from tortoisepy.core.reduction import reduce_transitive_edges


def edge(a: str, d: str) -> GraphEdge:
    return GraphEdge(ancestor=a, descendant=d, skipped=())


def test_removes_redundant_direct_edge():
    """A→B est redondante puisque A→C→B existe."""
    edges = (edge("A", "B"), edge("A", "C"), edge("C", "B"))
    result = reduce_transitive_edges(edges)
    pairs = {(e.ancestor, e.descendant) for e in result}
    assert ("A", "B") not in pairs
    assert ("A", "C") in pairs
    assert ("C", "B") in pairs


def test_keeps_all_edges_when_no_redundancy():
    edges = (edge("A", "B"), edge("C", "D"))
    assert len(reduce_transitive_edges(edges)) == 2


def test_keeps_diamond_edges():
    """Un losange n'a aucune arête redondante."""
    edges = (edge("A", "B"), edge("A", "C"), edge("B", "D"), edge("C", "D"))
    assert len(reduce_transitive_edges(edges)) == 4


def test_removes_edge_across_long_path():
    edges = (edge("A", "B"), edge("B", "C"), edge("C", "D"), edge("A", "D"))
    pairs = {(e.ancestor, e.descendant) for e in reduce_transitive_edges(edges)}
    assert ("A", "D") not in pairs
    assert len(pairs) == 3


def test_preserves_skipped_oids():
    """La réduction ne doit pas perdre l'information de compression."""
    edges = (GraphEdge("A", "B", ("x", "y")),)
    result = reduce_transitive_edges(edges)
    assert result[0].skipped == ("x", "y")


def test_empty_input():
    assert reduce_transitive_edges(()) == ()
