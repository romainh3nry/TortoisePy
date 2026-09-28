"""Simplification des jonctions sans intérêt visuel.

Défaut trouvé en ouvrant un vrai dépôt : 15 des 17 jonctions étaient des
« pass-through » (un ancêtre, un descendant), chacune créant un rang de
plus. Le graphe formait une colonne de 26 rangs au lieu d'étaler les
branches.
"""

from tortoisepy.core.collapse import collapse_trivial_junctions
from tortoisepy.core.model import (
    DisplayGraph,
    DisplayNode,
    GraphEdge,
    NodeKind,
    Ref,
    RefType,
)


def junction(oid: str) -> DisplayNode:
    return DisplayNode(oid=oid, kind=NodeKind.JUNCTION, refs=())


def ref_node(oid: str, name: str) -> DisplayNode:
    return DisplayNode(
        oid=oid,
        kind=NodeKind.REF,
        refs=(Ref(name, RefType.LOCAL_BRANCH, oid),),
    )


def edge(a: str, d: str, skipped: tuple[str, ...] = ()) -> GraphEdge:
    return GraphEdge(ancestor=a, descendant=d, skipped=skipped)


def test_pass_through_junction_is_removed():
    """a → j → b devient a → b."""
    graph = DisplayGraph(
        nodes=(ref_node("a", "base"), junction("j"), ref_node("b", "tip")),
        edges=(edge("a", "j"), edge("j", "b")),
    )
    result = collapse_trivial_junctions(graph)
    assert {n.oid for n in result.nodes} == {"a", "b"}
    assert len(result.edges) == 1
    assert result.edges[0].ancestor == "a"
    assert result.edges[0].descendant == "b"


def test_removed_junction_stays_reachable_as_skipped():
    """§4.2.1 : la compression est visuelle, rien ne disparaît du modèle."""
    graph = DisplayGraph(
        nodes=(ref_node("a", "base"), junction("j"), ref_node("b", "tip")),
        edges=(edge("a", "j"), edge("j", "b")),
    )
    result = collapse_trivial_junctions(graph)
    assert "j" in result.edges[0].skipped


def test_skipped_commits_are_concatenated():
    graph = DisplayGraph(
        nodes=(ref_node("a", "base"), junction("j"), ref_node("b", "tip")),
        edges=(edge("a", "j", ("x",)), edge("j", "b", ("y",))),
    )
    result = collapse_trivial_junctions(graph)
    assert set(result.edges[0].skipped) == {"x", "j", "y"}


def test_branching_junction_is_kept():
    """Une jonction à deux descendants porte une vraie information."""
    graph = DisplayGraph(
        nodes=(
            ref_node("a", "base"),
            junction("j"),
            ref_node("b", "left"),
            ref_node("c", "right"),
        ),
        edges=(edge("a", "j"), edge("j", "b"), edge("j", "c")),
    )
    result = collapse_trivial_junctions(graph)
    assert "j" in {n.oid for n in result.nodes}


def test_merging_junction_is_kept():
    """Une jonction à deux ancêtres aussi."""
    graph = DisplayGraph(
        nodes=(
            ref_node("a", "left"),
            ref_node("b", "right"),
            junction("j"),
            ref_node("c", "tip"),
        ),
        edges=(edge("a", "j"), edge("b", "j"), edge("j", "c")),
    )
    result = collapse_trivial_junctions(graph)
    assert "j" in {n.oid for n in result.nodes}


def test_node_with_refs_is_never_removed():
    """Un nœud portant une ref reste, même en pass-through."""
    graph = DisplayGraph(
        nodes=(ref_node("a", "base"), ref_node("m", "middle"), ref_node("b", "tip")),
        edges=(edge("a", "m"), edge("m", "b")),
    )
    result = collapse_trivial_junctions(graph)
    assert {n.oid for n in result.nodes} == {"a", "m", "b"}


def test_stash_node_is_never_removed():
    stash = DisplayNode(
        oid="s", kind=NodeKind.STASH,
        refs=(Ref("stash@{0}", RefType.STASH, "s"),),
    )
    graph = DisplayGraph(
        nodes=(ref_node("a", "base"), stash),
        edges=(edge("a", "s"),),
    )
    result = collapse_trivial_junctions(graph)
    assert "s" in {n.oid for n in result.nodes}


def test_chain_of_junctions_collapses_entirely():
    graph = DisplayGraph(
        nodes=(
            ref_node("a", "base"),
            junction("j1"), junction("j2"), junction("j3"),
            ref_node("b", "tip"),
        ),
        edges=(edge("a", "j1"), edge("j1", "j2"), edge("j2", "j3"), edge("j3", "b")),
    )
    result = collapse_trivial_junctions(graph)
    assert {n.oid for n in result.nodes} == {"a", "b"}
    assert set(result.edges[0].skipped) == {"j1", "j2", "j3"}


def test_every_edge_still_connects_existing_nodes():
    graph = DisplayGraph(
        nodes=(ref_node("a", "base"), junction("j"), ref_node("b", "tip")),
        edges=(edge("a", "j"), edge("j", "b")),
    )
    result = collapse_trivial_junctions(graph)
    known = {n.oid for n in result.nodes}
    for e in result.edges:
        assert e.ancestor in known
        assert e.descendant in known


def test_empty_graph_is_unchanged():
    graph = DisplayGraph(nodes=(), edges=())
    assert collapse_trivial_junctions(graph) == graph


def test_graph_without_junctions_is_unchanged():
    graph = DisplayGraph(
        nodes=(ref_node("a", "base"), ref_node("b", "tip")),
        edges=(edge("a", "b"),),
    )
    assert collapse_trivial_junctions(graph) is graph
