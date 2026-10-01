"""Un clic droit doit désigner le nœud qu'il vise.

Bug signalé par l'utilisateur : créer un tag depuis le menu contextuel
d'une autre branche posait le tag sur la branche COURANTE.

Cause mesurée : Qt ne sélectionne pas sur un clic droit. Le menu était
bien construit pour le bon nœud, mais `_run_action` relisait la sélection
au moment du déclenchement — et celle-ci portait encore le nœud HEAD,
sélectionné au démarrage par le centrage automatique.

    selection initiale : (ec76f397…)        <- HEAD
    apres clic DROIT   : []                  <- rien !
    apres clic GAUCHE  : [287a18e8]          <- le noeud vise
"""

from __future__ import annotations

import subprocess

import pygit2
import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QMouseEvent

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
    """`main` (courante) et `autre`, sur deux commits distincts."""
    w = tmp_path / "w"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "a.txt").write_text("a")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "sur main")
    _git(w, "checkout", "-q", "-b", "autre")
    (w / "b.txt").write_text("b")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "sur autre")
    _git(w, "checkout", "-q", "main")

    fenetre = MainWindow(pygit2.Repository(str(w)))
    qtbot.addWidget(fenetre)
    fenetre.resize(900, 700)
    fenetre.show()
    return fenetre


def _clic(qtbot, fenetre, oid, bouton):
    """Envoie un vrai clic sur le nœud portant `oid`.

    `qtbot.mouseClick` plutôt qu'un `QMouseEvent` fabriqué à la main :
    vérifié, la position doit être exprimée dans les coordonnées du
    viewport, et un décalage d'un pixel atteint le nœud voisin.
    """
    items = {
        item.node.oid: item
        for item in fenetre.view.scene().items()
        if isinstance(item, NodeItem)
    }
    centre = items[oid].sceneBoundingRect().center()
    position = fenetre.view.viewport().mapFrom(
        fenetre.view, fenetre.view.mapFromScene(centre)
    )
    qtbot.mouseClick(fenetre.view.viewport(), bouton, pos=position)


def test_right_clicking_a_node_selects_it(qtbot, fenetre):
    """Le test qui reproduit le bug : sans cela, le tag part ailleurs."""
    autre = str(fenetre.repository.branches.local["autre"].target)
    assert fenetre.view.selected_oids() != (autre,), "pré-sélectionné"

    _clic(qtbot, fenetre, autre, Qt.MouseButton.RightButton)

    assert fenetre.view.selected_oids() == (autre,), (
        "le clic droit n'a pas sélectionné le nœud visé"
    )


def test_the_action_targets_the_right_clicked_node(qtbot, fenetre):
    """L'assertion qui compte : c'est `_selected_node` que lit l'action."""
    autre = str(fenetre.repository.branches.local["autre"].target)

    _clic(qtbot, fenetre, autre, Qt.MouseButton.RightButton)

    noeud = fenetre._selected_node()
    assert noeud is not None, "aucun nœud désigné après un clic droit"
    assert noeud.oid == autre


def test_right_clicking_does_not_clear_a_multiple_selection(qtbot, fenetre):
    """Comparer deux révisions se fait sur une sélection multiple.

    Un clic droit DANS cette sélection ne doit pas la réduire à un nœud,
    sinon « Compare revisions » deviendrait inatteignable.
    """
    oids = sorted(
        item.node.oid
        for item in fenetre.view.scene().items()
        if isinstance(item, NodeItem)
    )
    for item in fenetre.view.scene().items():
        if isinstance(item, NodeItem):
            item.setSelected(True)
    assert len(fenetre.view.selected_oids()) == len(oids)

    _clic(qtbot, fenetre, oids[0], Qt.MouseButton.RightButton)

    assert len(fenetre.view.selected_oids()) == len(oids), (
        "la sélection multiple a été perdue"
    )


def test_left_click_still_selects(qtbot, fenetre):
    """Le comportement existant ne régresse pas."""
    autre = str(fenetre.repository.branches.local["autre"].target)
    _clic(qtbot, fenetre, autre, Qt.MouseButton.LeftButton)
    assert fenetre.view.selected_oids() == (autre,)
