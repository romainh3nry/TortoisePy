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


def test_label_counts_the_destination_commit_too():
    """L'étiquette annonce ce que la branche a ajouté, commit du nœud inclus.

    `skipped` ne compte que les commits ENTRE les deux nœuds : s'y fier
    seul annonçait systématiquement un commit de moins que ce que le
    panneau encadre au clic.
    """
    graph = DisplayGraph(
        nodes=(node("a" * 40, "base"), node("b" * 40, "tip")),
        edges=(edge("a" * 40, "b" * 40, ("c" * 40, "d" * 40)),),
    )
    scene = build_scene(graph, layout_graph(graph, QtMeasurer()))
    edges = [i for i in scene.items() if isinstance(i, EdgeItem)]
    # 2 sautés + le commit de « tip » = 3
    assert edges[0].label == "3 commits"


def test_edge_without_skipped_commits_still_counts_one():
    """Deux nœuds voisins : la branche a quand même ajouté un commit."""
    graph = DisplayGraph(
        nodes=(node("a" * 40, "base"), node("b" * 40, "tip")),
        edges=(edge("a" * 40, "b" * 40),),
    )
    scene = build_scene(graph, layout_graph(graph, QtMeasurer()))
    edges = [i for i in scene.items() if isinstance(i, EdgeItem)]
    assert edges[0].label == "1 commit"


def test_edge_with_skipped_commits_is_labelled():
    graph = DisplayGraph(
        nodes=(node("a" * 40, "base"), node("b" * 40, "tip")),
        edges=(edge("a" * 40, "b" * 40, tuple("c" * 40 for _ in range(12))),),
    )
    scene = build_scene(graph, layout_graph(graph, QtMeasurer()))
    edges = [i for i in scene.items() if isinstance(i, EdgeItem)]
    assert edges[0].label is not None
    # 12 sautés + le commit du nœud d'arrivée
    assert "13" in edges[0].label


def test_every_edge_is_labelled():
    """Même sans commit sauté, la branche a ajouté le commit du nœud."""
    graph = simple_graph()
    scene = build_scene(graph, layout_graph(graph, QtMeasurer()))
    edges = [i for i in scene.items() if isinstance(i, EdgeItem)]
    assert edges[0].label == "1 commit"


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


def test_one_skipped_commit_counts_two():
    """« 1 commit », pas « 1 commits »."""
    graph = DisplayGraph(
        nodes=(node("a" * 40, "base"), node("b" * 40, "tip")),
        edges=(edge("a" * 40, "b" * 40, ("c" * 40,)),),
    )
    scene = build_scene(graph, layout_graph(graph, QtMeasurer()))
    edges = [i for i in scene.items() if isinstance(i, EdgeItem)]
    # 1 sauté + le commit du nœud = 2
    assert edges[0].label == "2 commits"


def test_several_skipped_commits_label_is_plural():
    graph = DisplayGraph(
        nodes=(node("a" * 40, "base"), node("b" * 40, "tip")),
        edges=(edge("a" * 40, "b" * 40, tuple("c" * 40 for _ in range(3))),),
    )
    scene = build_scene(graph, layout_graph(graph, QtMeasurer()))
    edges = [i for i in scene.items() if isinstance(i, EdgeItem)]
    # 3 sautés + le commit du nœud = 4
    assert edges[0].label == "4 commits"


def test_labels_do_not_overlap_each_other():
    """Plusieurs arêtes partant d'un même nœud empilaient leurs étiquettes.

    Les ancrer sur leur courbe ne suffit pas là où beaucoup d'arêtes se
    croisent : une passe de désencombrement les écarte.
    """
    base = "a" * 40
    nodes = [node(base, "base")]
    edges = []
    for index in range(6):
        oid = f"{index}" * 40
        nodes.append(node(oid, f"branche-{index}"))
        edges.append(edge(base, oid, tuple("c" * 40 for _ in range(index + 1))))

    graph = DisplayGraph(nodes=tuple(nodes), edges=tuple(edges))
    scene = build_scene(graph, layout_graph(graph, QtMeasurer()))

    rects = [
        i.label_rect()
        for i in scene.items()
        if isinstance(i, EdgeItem) and i.label_rect() is not None
    ]
    assert len(rects) == 6

    overlaps = sum(
        1
        for i, a in enumerate(rects)
        for b in rects[i + 1:]
        if a.intersects(b)
    )
    assert overlaps == 0, f"{overlaps} étiquettes se chevauchent"


def test_label_stays_near_its_edge():
    """Le décalage est borné : au-delà on ne saurait plus à quelle arête
    l'étiquette appartient."""
    from tortoisepy.ui.graph_items import LABEL_MAX_SHIFT

    graph = simple_graph()
    scene = build_scene(graph, layout_graph(graph, QtMeasurer()))
    item = next(i for i in scene.items() if isinstance(i, EdgeItem))

    label = item.label_rect()
    path = item.path()
    middle = path.pointAtPercent(0.5)
    assert abs(label.center().y() - middle.y()) < LABEL_MAX_SHIFT + 40.0


def test_label_placement_is_deterministic():
    """§10.4 : deux constructions donnent le même rendu."""
    graph = simple_graph()
    layout = layout_graph(graph, QtMeasurer())

    def positions(scene):
        return sorted(
            (i.label_rect().x(), i.label_rect().y())
            for i in scene.items()
            if isinstance(i, EdgeItem) and i.label_rect() is not None
        )

    assert positions(build_scene(graph, layout)) == positions(
        build_scene(graph, layout)
    )


def _node_items(scene):
    """Les `NodeItem` d'une scène, par OID.

    L'appelant doit garder une référence sur la scène : sans elle, Python
    la ramasse et shiboken détruit l'objet C++ **et ses items**, ce qui fait
    lever `RuntimeError: Internal C++ object already deleted` au premier
    accès suivant. Les tests plus anciens de ce fichier lient déjà la scène
    à une variable locale pour cette raison.
    """
    from tortoisepy.ui.graph_items import NodeItem

    return {
        item.node.oid: item
        for item in scene.items()
        if isinstance(item, NodeItem)
    }


def test_node_without_unpushed_commits_is_unchanged(qtbot):
    """Review Focus 5 : le rendu validé ne doit pas bouger d'un pixel."""
    from tortoisepy.layout.engine import layout_graph
    from tortoisepy.ui.graph_items import build_scene

    graph = simple_graph()
    layout = layout_graph(graph, QtMeasurer())

    scene_avant = build_scene(graph, layout)
    scene_apres = build_scene(graph, layout, unpushed=frozenset())
    avant = _node_items(scene_avant)
    apres = _node_items(scene_apres)

    for oid, item in apres.items():
        assert item.brush().color() == avant[oid].brush().color()
        assert item.pen().color() == avant[oid].pen().color()
        assert item.rect() == avant[oid].rect()
        assert item.has_unpushed_marker() is False


def test_node_with_unpushed_commits_gets_a_marker(qtbot):
    from tortoisepy.layout.engine import layout_graph
    from tortoisepy.ui.graph_items import build_scene

    graph = simple_graph()
    layout = layout_graph(graph, QtMeasurer())
    cible = layout.placements[0].oid

    scene_avec = build_scene(graph, layout, unpushed=frozenset({cible}))
    items = _node_items(scene_avec)
    assert items[cible].has_unpushed_marker() is True

    # La pastille ne déplace ni n'agrandit le nœud.
    scene_sans = build_scene(graph, layout)
    sans = _node_items(scene_sans)
    assert items[cible].rect() == sans[cible].rect()
    # …ni ne change sa couleur : le remplissage dit le type de ref.
    assert items[cible].brush().color() == sans[cible].brush().color()


def test_build_scene_stays_compatible_without_the_argument(qtbot):
    """Les appels existants, sans le paramètre, doivent continuer à marcher."""
    from tortoisepy.layout.engine import layout_graph
    from tortoisepy.ui.graph_items import build_scene

    graph = simple_graph()
    layout = layout_graph(graph, QtMeasurer())
    assert build_scene(graph, layout) is not None


def _render(scene):
    """Rend une scène hors écran, pour comparer des pixels.

    Comparer `brush`/`pen`/`rect` ne suffit pas : une pastille dessinée à
    tort quand `unpushed=False` ne changerait aucune de ces propriétés et
    passerait inaperçue. Seul le rendu le prouve.
    """
    from PySide6.QtGui import QImage, QPainter

    image = QImage(
        int(scene.width()) + 20,
        int(scene.height()) + 20,
        QImage.Format.Format_ARGB32,
    )
    image.fill(0xFFFFFFFF)
    painter = QPainter(image)
    scene.render(painter)
    painter.end()
    return image


def test_rendering_is_pixel_identical_without_the_marker(qtbot):
    """Règle utilisateur : « il ne faut pas dégrader le rendu actuel ».

    L'appel d'origine, sans le paramètre, et le nouvel appel avec un
    ensemble vide doivent produire exactement la même image — pas seulement
    les mêmes propriétés d'objets.
    """
    from tortoisepy.ui.graph_items import build_scene

    graph = simple_graph()
    layout = layout_graph(graph, QtMeasurer())

    ancien = build_scene(graph, layout)
    nouveau = build_scene(graph, layout, unpushed=frozenset())

    assert _render(ancien) == _render(nouveau)


def test_marker_is_actually_painted(qtbot):
    """La pastille doit se voir — et seulement quand elle doit."""
    from tortoisepy.ui.graph_items import build_scene

    graph = simple_graph()
    layout = layout_graph(graph, QtMeasurer())
    cible = layout.placements[0].oid

    sans = build_scene(graph, layout)
    avec = build_scene(graph, layout, unpushed=frozenset({cible}))

    assert _render(sans) != _render(avec)
