from tortoisepy.core.model import (
    DisplayGraph,
    DisplayNode,
    GraphEdge,
    NodeKind,
)
from tortoisepy.layout.ordering import find_components, order_within_ranks
from tortoisepy.layout.ranking import compute_ranks


def n(oid: str) -> DisplayNode:
    return DisplayNode(oid=oid, kind=NodeKind.JUNCTION, refs=())


def e(a: str, d: str) -> GraphEdge:
    return GraphEdge(ancestor=a, descendant=d, skipped=())


def graph(oids: list[str], edges: list[GraphEdge]) -> DisplayGraph:
    return DisplayGraph(nodes=tuple(n(o) for o in oids), edges=tuple(edges))


def test_connected_graph_is_one_component():
    g = graph(["a", "b", "c"], [e("a", "b"), e("b", "c")])
    assert len(find_components(g)) == 1


def test_two_histories_are_two_components():
    """§10.4 : les historiques indépendants restent séparés."""
    g = graph(["a1", "a2", "b1"], [e("a1", "a2")])
    components = find_components(g)
    assert len(components) == 2
    assert {frozenset(c) for c in components} == {
        frozenset({"a1", "a2"}),
        frozenset({"b1"}),
    }


def test_components_are_connected_through_shared_ancestor():
    """Deux branches divergentes partagent leur merge-base : une composante."""
    g = graph(["base", "x", "y"], [e("base", "x"), e("base", "y")])
    assert len(find_components(g)) == 1


def test_component_membership_is_sorted():
    """Déterminisme : l'ordre interne ne dépend pas du parcours."""
    g = graph(["c", "a", "b"], [e("a", "b"), e("b", "c")])
    assert find_components(g)[0] == ("a", "b", "c")


def test_components_are_deterministic():
    g = graph(["a1", "a2", "b1", "b2"], [e("a1", "a2"), e("b1", "b2")])
    assert find_components(g) == find_components(g)


def test_empty_graph_has_no_components():
    assert find_components(DisplayGraph(nodes=(), edges=())) == ()


def test_ordering_groups_by_rank():
    g = graph(["base", "x", "y"], [e("base", "x"), e("base", "y")])
    orders = order_within_ranks(g, compute_ranks(g))
    assert orders[0] == ("base",)
    assert set(orders[1]) == {"x", "y"}


def test_ordering_is_deterministic():
    g = graph(["base", "x", "y", "z"],
              [e("base", "x"), e("base", "y"), e("base", "z")])
    ranks = compute_ranks(g)
    assert order_within_ranks(g, ranks) == order_within_ranks(g, ranks)


def test_every_node_appears_exactly_once():
    g = graph(["a", "b", "c", "d"], [e("a", "b"), e("a", "c"), e("b", "d")])
    orders = order_within_ranks(g, compute_ranks(g))
    placed = [oid for rank in sorted(orders) for oid in orders[rank]]
    assert sorted(placed) == ["a", "b", "c", "d"]


def test_children_follow_their_parents_order():
    """Les enfants s'ordonnent comme leurs parents, pas alphabétiquement.

    Rang 0 trié : ("aaa", "bbb"). Leurs enfants sont nommés à contre-sens —
    "aaa" a pour enfant "zzz", "bbb" a pour enfant "mmm". Un tri
    alphabétique du rang 1 donnerait ("mmm", "zzz") et croiserait les deux
    arêtes ; le barycentre doit produire ("zzz", "mmm").
    """
    g = graph(["aaa", "bbb", "zzz", "mmm"],
              [e("aaa", "zzz"), e("bbb", "mmm")])
    orders = order_within_ranks(g, compute_ranks(g))

    assert list(orders[0]) == ["aaa", "bbb"]
    assert list(orders[1]) == ["zzz", "mmm"], (
        "l'enfant de 'aaa' doit précéder celui de 'bbb' : sinon les arêtes "
        "se croisent inutilement"
    )
