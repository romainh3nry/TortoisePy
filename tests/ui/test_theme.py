from PySide6.QtGui import QColor

from tortoisepy.core.model import DisplayNode, NodeKind, Ref, RefType
from tortoisepy.ui.theme import QtMeasurer, node_color


def node(oid: str, kind: NodeKind, *refs: Ref) -> DisplayNode:
    return DisplayNode(oid=oid, kind=kind, refs=refs)


def ref(name: str, type_: RefType) -> Ref:
    return Ref(name, type_, "a" * 40)


def test_current_branch_is_red():
    """Phase 18 : la branche courante passe du vert au **rouge**.

    Demandé par l'utilisateur, capture de TortoiseGit à l'appui. Le vert
    désigne désormais les branches locales ordinaires.
    """
    n = node("a" * 40, NodeKind.REF,
             ref("master", RefType.LOCAL_BRANCH), ref("HEAD", RefType.HEAD))
    colour = node_color(n, selected=False)
    assert colour.red() > colour.green()
    assert colour.red() > colour.blue()


def test_local_branch_is_green():
    """Phase 18 : le vert, autrefois réservé à la courante."""
    n = node("a" * 40, NodeKind.REF, ref("feature", RefType.LOCAL_BRANCH))
    colour = node_color(n, selected=False)
    assert colour.green() > colour.red()
    assert colour.green() > colour.blue()


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


# --- Phase 18 : une couleur par type de ref -------------------------------


def _lignes(n, courante=None):
    """Les lignes d'un nœud. `courante` = nom de la branche courante.

    Sans ce nom, `develop`+`HEAD` (attaché) et `main`+`HEAD` (détaché)
    seraient indiscernables — vérifié sur de vrais dépôts.
    """
    from tortoisepy.ui.theme import ref_rows

    return ref_rows(n, courante)


def test_each_ref_gets_its_own_row():
    """D41 : le nœud ne porte plus une seule couleur mais une par ligne."""
    n = node(
        "a" * 40,
        NodeKind.REF,
        ref("feature", RefType.LOCAL_BRANCH),
        ref("origin/feature", RefType.REMOTE_BRANCH),
        ref("v1.0", RefType.TAG),
    )
    assert [l.label for l in _lignes(n)] == [
        "feature", "origin/feature", "v1.0"
    ]


def test_the_four_colours_are_distinct():
    """Vert local, rouge courant, beige distant, jaune tag."""
    from tortoisepy.ui.theme import PALETTE

    couleurs = {
        PALETTE.local_branch.name(),
        PALETTE.current_branch.name(),
        PALETTE.remote_branch.name(),
        PALETTE.tag.name(),
    }
    assert len(couleurs) == 4, couleurs


def test_only_the_current_branch_row_is_red():
    """D42 : sa jumelle distante reste beige, ses tags restent jaunes.

    C'est ce que montre la capture de référence : `MYMT-1243` est rouge
    tandis que `origin/MYMT-1243` reste beige sur le même nœud.
    """
    from tortoisepy.ui.theme import PALETTE

    n = node(
        "a" * 40,
        NodeKind.REF,
        ref("feature", RefType.LOCAL_BRANCH),
        ref("origin/feature", RefType.REMOTE_BRANCH),
        ref("v1.0", RefType.TAG),
        ref("HEAD", RefType.HEAD),
    )
    par_nom = {l.label: l.colour.name() for l in _lignes(n, "feature")}

    assert par_nom["feature"] == PALETTE.current_branch.name()
    assert par_nom["origin/feature"] == PALETTE.remote_branch.name()
    assert par_nom["v1.0"] == PALETTE.tag.name()


def test_a_local_branch_elsewhere_is_green():
    """Une locale sur un autre nœud n'est pas la courante."""
    from tortoisepy.ui.theme import PALETTE

    n = node("b" * 40, NodeKind.REF, ref("autre", RefType.LOCAL_BRANCH))
    assert _lignes(n, "feature")[0].colour.name() == PALETTE.local_branch.name()


def test_head_is_hidden_when_a_local_branch_carries_it():
    """D43 : la ligne HEAD n'apprend rien de plus, et la capture l'ignore."""
    n = node(
        "a" * 40,
        NodeKind.REF,
        ref("develop", RefType.LOCAL_BRANCH),
        ref("HEAD", RefType.HEAD),
    )
    assert [l.label for l in _lignes(n, "develop")] == ["develop"]


def test_head_is_kept_and_red_when_detached():
    """Le test qui distingue cette phase d'une simplification naïve.

    Vérifié sur un vrai dépôt : en HEAD détachée le nœud ne porte que
    `main` et `HEAD`, exactement comme en attaché. Masquer `HEAD`
    afficherait `main` en vert comme une branche ordinaire, alors qu'on
    n'est **pas** dessus — le repère serait perdu.
    """
    from tortoisepy.ui.theme import PALETTE

    n = node(
        "a" * 40,
        NodeKind.REF,
        ref("main", RefType.LOCAL_BRANCH),
        ref("HEAD", RefType.HEAD),
    )
    lignes = _lignes(n, None)          # détaché : aucune branche courante
    par_nom = {l.label: l.colour.name() for l in lignes}

    assert "HEAD" in par_nom, "en détaché, HEAD est le seul repère"
    assert par_nom["HEAD"] == PALETTE.current_branch.name()
    assert par_nom["main"] == PALETTE.local_branch.name(), (
        "`main` n'est pas la branche courante : on est détaché dessus"
    )


def test_a_node_without_refs_shows_its_oid():
    n = node("c" * 40, NodeKind.JUNCTION)
    assert [l.label for l in _lignes(n)] == ["cccccccc"]
