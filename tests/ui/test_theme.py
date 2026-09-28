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
