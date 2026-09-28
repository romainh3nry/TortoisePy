import pytest

from tortoisepy.core.model import DisplayNode, NodeKind, Ref, RefType
from tortoisepy.layout.metrics import (
    LayoutResult,
    MonospaceMeasurer,
    Placement,
    Size,
)


def node(oid: str, *names: str) -> DisplayNode:
    refs = tuple(Ref(n, RefType.LOCAL_BRANCH, oid) for n in names)
    return DisplayNode(
        oid=oid,
        kind=NodeKind.REF if refs else NodeKind.JUNCTION,
        refs=refs,
    )


def test_size_is_frozen():
    s = Size(width=10.0, height=4.0)
    with pytest.raises(AttributeError):
        s.width = 99.0


def test_placement_exposes_its_bounds():
    p = Placement(oid="abc", x=10.0, y=20.0, size=Size(30.0, 8.0))
    assert p.left == 10.0
    assert p.right == 40.0
    assert p.bottom == 20.0
    assert p.top == 28.0


def test_single_ref_node_width_follows_name_length():
    m = MonospaceMeasurer()
    short = m.measure(node("a" * 40, "x"))
    long = m.measure(node("b" * 40, "a-very-long-branch-name"))
    assert long.width > short.width


def test_multi_ref_node_is_taller():
    m = MonospaceMeasurer()
    one = m.measure(node("a" * 40, "master"))
    three = m.measure(node("b" * 40, "master", "origin/master", "github/master"))
    assert three.height > one.height
    assert three.width >= one.width


def test_multi_ref_width_follows_longest_name():
    """Un nœud à trois refs est large comme sa ref la plus longue."""
    m = MonospaceMeasurer()
    got = m.measure(node("a" * 40, "x", "a-much-longer-name", "y"))
    expected = m.measure(node("b" * 40, "a-much-longer-name"))
    assert got.width == expected.width


def test_junction_node_is_labelled_by_short_oid():
    """§4.3 : les jonctions affichent leur OID court."""
    m = MonospaceMeasurer()
    size = m.measure(node("abcdef1234567890" + "0" * 24))
    assert size.width > 0
    assert size.height > 0


def test_measurement_is_deterministic():
    m = MonospaceMeasurer()
    n = node("a" * 40, "master", "origin/master")
    assert m.measure(n) == m.measure(n)


def test_layout_result_lookup():
    p = Placement(oid="abc", x=0.0, y=0.0, size=Size(10.0, 5.0))
    result = LayoutResult(placements=(p,), width=10.0, height=5.0)
    assert result.placement("abc") is p
    assert result.placement("inconnu") is None
