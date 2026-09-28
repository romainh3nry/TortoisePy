import pytest

from tortoisepy.core.model import (
    DisplayGraph,
    DisplayNode,
    GraphEdge,
    NodeKind,
    Ref,
    RefType,
)


def test_ref_is_frozen():
    ref = Ref(name="master", type=RefType.LOCAL_BRANCH, target="abc123")
    with pytest.raises(AttributeError):
        ref.name = "autre"


def test_edge_uses_ancestor_descendant_naming():
    """La spec §4.2 impose ces noms : ni from/to, ni source/target."""
    edge = GraphEdge(ancestor="old", descendant="new", skipped=())
    assert edge.ancestor == "old"
    assert edge.descendant == "new"
    assert not hasattr(edge, "source")
    assert not hasattr(edge, "target")


def test_edge_skipped_holds_ordered_oids():
    """§4.2.1 : la compression est visuelle, les OID sautés sont conservés."""
    edge = GraphEdge(ancestor="a", descendant="d", skipped=("b", "c"))
    assert edge.skipped == ("b", "c")
    assert edge.skipped_count == 2


def test_edge_with_no_skipped_commits():
    edge = GraphEdge(ancestor="a", descendant="b", skipped=())
    assert edge.skipped_count == 0


def test_display_node_groups_several_refs():
    """§4.1 : plusieurs refs sur un même commit forment un seul nœud."""
    node = DisplayNode(
        oid="abc123",
        kind=NodeKind.REF,
        refs=(
            Ref("origin/master", RefType.REMOTE_BRANCH, "abc123"),
            Ref("master", RefType.LOCAL_BRANCH, "abc123"),
        ),
    )
    assert len(node.refs) == 2


def test_junction_node_has_no_refs():
    """§4.1 catégorie 2 : les merge-bases sont des nœuds sans ref."""
    node = DisplayNode(oid="def456", kind=NodeKind.JUNCTION, refs=())
    assert node.refs == ()
    assert node.kind is NodeKind.JUNCTION


def test_graph_lookup_by_oid():
    node = DisplayNode(oid="abc123", kind=NodeKind.JUNCTION, refs=())
    graph = DisplayGraph(nodes=(node,), edges=())
    assert graph.node("abc123") is node
    assert graph.node("inconnu") is None
