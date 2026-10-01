"""Déplacer le graphe à la souris, et revenir sur la branche courante.

Demandé par l'utilisateur. `ScrollHandDrag` était déjà posé sur la vue,
mais il ne s'enclenche pas quand le glisser démarre SUR un nœud : les
nœuds portent `ItemIsSelectable`, et Qt donne alors la priorité à l'item.
Sur un dépôt dense, c'est presque toujours le cas — d'où l'impression que
le déplacement ne marche pas.

Les événements de souris SYNTHÉTIQUES ne déclenchent pas `ScrollHandDrag`
(vérifié sur une `QGraphicsView` nue : les barres ne bougent pas). Ces
tests vérifient donc la configuration et le déplacement programmatique,
pas le geste lui-même — qui relève de l'essai manuel.
"""

from __future__ import annotations

import subprocess

import pygit2
import pytest
from PySide6.QtWidgets import QGraphicsView

from tortoisepy.ui.graph_items import NodeItem
from tortoisepy.ui.main_window import MainWindow


def _git(chemin, *args):
    subprocess.run(
        ["git", "-C", str(chemin), *args], check=True, capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
            "PATH": "/usr/bin:/bin:/usr/local/bin",
        },
    )


@pytest.fixture
def fenetre(qtbot, tmp_path):
    """Un graphe plus grand que la fenêtre, pour qu'il y ait à défiler."""
    w = tmp_path / "w"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    for i in range(12):
        (w / f"f{i}.txt").write_text("x")
        _git(w, "add", ".")
        _git(w, "commit", "-q", "-m", f"c{i}")
        _git(w, "branch", f"b{i}")
    _git(w, "checkout", "-q", "b5")

    fenetre = MainWindow(pygit2.Repository(str(w)))
    qtbot.addWidget(fenetre)
    fenetre.resize(400, 300)
    fenetre.show()
    return fenetre


def test_the_view_pans_with_the_left_button(fenetre):
    """Le mode doit rester `ScrollHandDrag` : c'est lui qui déplace."""
    assert fenetre.view.dragMode() is QGraphicsView.DragMode.ScrollHandDrag


def test_nodes_do_not_capture_the_drag(fenetre):
    """La cause du bug : un nœud sous le curseur bloquait le déplacement.

    `ItemIsMovable` n'est pas posé — les nœuds ne se déplacent pas — mais
    `ItemIsSelectable` suffit à ce que Qt donne la priorité à l'item au
    lieu de laisser la vue défiler.
    """
    from PySide6.QtWidgets import QGraphicsItem

    noeuds = [
        item for item in fenetre.view.scene().items()
        if isinstance(item, NodeItem)
    ]
    assert noeuds, "le graphe doit contenir des nœuds"
    for noeud in noeuds:
        assert not noeud.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsMovable


def test_panning_programmatically_moves_the_view(fenetre):
    """Le déplacement lui-même fonctionne : les barres suivent."""
    barre = fenetre.view.verticalScrollBar()
    if barre.maximum() == barre.minimum():
        pytest.skip("rien à faire défiler dans cette fenêtre")

    avant = barre.value()
    fenetre.view.pan_by(0, 50)
    assert barre.value() != avant, "la vue n'a pas défilé"


# --- Recentrage sur la branche courante ----------------------------------


def test_the_recenter_action_exists(fenetre):
    """Demandé par l'utilisateur : un bouton pour revenir sur HEAD."""
    assert hasattr(fenetre, "recenter_action")
    assert fenetre.recenter_action.isEnabled()


def test_recentering_brings_head_into_view(fenetre):
    """L'assertion qui compte : le nœud courant redevient visible."""
    repo = fenetre.repository
    oid_head = str(repo.head.target)

    # On s'éloigne franchement.
    fenetre.view.verticalScrollBar().setValue(
        fenetre.view.verticalScrollBar().maximum()
    )
    fenetre.view.horizontalScrollBar().setValue(
        fenetre.view.horizontalScrollBar().maximum()
    )

    fenetre.recenter_action.trigger()

    noeud = next(
        item for item in fenetre.view.scene().items()
        if isinstance(item, NodeItem) and item.node.oid == oid_head
    )
    visible = fenetre.view.mapToScene(
        fenetre.view.viewport().rect()
    ).boundingRect()
    assert visible.intersects(noeud.sceneBoundingRect()), (
        "le nœud courant n'est pas revenu dans la vue"
    )


def test_recentering_does_not_change_the_zoom(fenetre):
    """Recentrer n'est pas « ajuster à la fenêtre » : le zoom est à toi."""
    fenetre.view.set_zoom(1.8)
    fenetre.recenter_action.trigger()
    assert fenetre.view.current_zoom() == pytest.approx(1.8, abs=0.01)


def test_recentering_is_safe_on_an_empty_graph(qtbot, tmp_path):
    """Un dépôt sans commit ne doit pas faire planter le bouton."""
    w = tmp_path / "vide"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    fenetre = MainWindow(pygit2.Repository(str(w)))
    qtbot.addWidget(fenetre)
    fenetre.recenter_action.trigger()   # ne doit pas lever
