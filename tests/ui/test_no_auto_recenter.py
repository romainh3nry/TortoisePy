"""La vue ne doit se recentrer qu'à l'ouverture et sur demande.

Signalé par l'utilisateur : « après certaines actions, la fenêtre se
recentrait automatiquement, il ne faut pas ».

Cause : `refresh()` appelait `_center_on_head()`, et `refresh()` est
appelé après CHAQUE action — fetch, commit, checkout, bascule du filtre
de tags. L'utilisateur qui s'était déplacé dans le graphe était ramené
de force sur sa branche courante.

Le centrage reste à deux endroits : l'ouverture de la fenêtre, et le
bouton « Recenter ».
"""

from __future__ import annotations

import subprocess

import pygit2
import pytest

from tortoisepy.ui.main_window import MainWindow


def _git(chemin, *args):
    subprocess.run(
        ["git", "-C", str(chemin), *args], check=False, capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
            "PATH": "/usr/bin:/bin:/usr/local/bin",
        },
    )


@pytest.fixture
def fenetre(qtbot, tmp_path):
    """Un graphe assez haut pour qu'il y ait matière à défiler."""
    w = tmp_path / "w"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    for i in range(12):
        (w / f"f{i}.txt").write_text("x\n")
        _git(w, "add", ".")
        _git(w, "commit", "-q", "-m", f"c{i}")
        _git(w, "branch", f"b{i}")

    fenetre = MainWindow(pygit2.Repository(str(w)))
    qtbot.addWidget(fenetre)
    fenetre.resize(400, 300)
    fenetre.show()
    return fenetre


def _position(fenetre) -> tuple[int, int]:
    return (
        fenetre.view.horizontalScrollBar().value(),
        fenetre.view.verticalScrollBar().value(),
    )


def test_refreshing_keeps_the_view_where_it_was(fenetre):
    """L'assertion centrale : un rafraîchissement ne déplace pas la vue."""
    barre = fenetre.view.verticalScrollBar()
    if barre.maximum() == barre.minimum():
        pytest.skip("rien à faire défiler dans cette fenêtre")

    fenetre.view.pan_by(0, barre.maximum() // 2)
    avant = _position(fenetre)

    fenetre.refresh()

    assert _position(fenetre) == avant, (
        "le rafraîchissement a déplacé la vue"
    )


def test_the_recenter_button_still_works(fenetre):
    """Le centrage reste accessible, à la demande."""
    barre = fenetre.view.verticalScrollBar()
    if barre.maximum() == barre.minimum():
        pytest.skip("rien à faire défiler")

    fenetre.view.pan_by(0, barre.maximum())
    loin = _position(fenetre)

    fenetre.recenter_action.trigger()

    assert _position(fenetre) != loin, "le bouton n'a pas recentré"


def test_opening_centres_on_the_current_branch(qtbot, tmp_path):
    """À l'ouverture, le nœud courant doit être visible.

    Sur un dépôt dont le graphe fait plusieurs milliers de pixels de
    haut, s'ouvrir ailleurs oblige à chercher où l'on se trouve.
    """
    from tortoisepy.ui.graph_items import NodeItem

    w = tmp_path / "w"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    for i in range(12):
        (w / f"f{i}.txt").write_text("x\n")
        _git(w, "add", ".")
        _git(w, "commit", "-q", "-m", f"c{i}")
        _git(w, "branch", f"b{i}")

    fenetre = MainWindow(pygit2.Repository(str(w)))
    qtbot.addWidget(fenetre)
    fenetre.resize(400, 300)
    fenetre.show()

    courant = str(fenetre.repository.head.target)
    noeud = next(
        i for i in fenetre.view.scene().items()
        if isinstance(i, NodeItem) and i.node.oid == courant
    )
    visible = fenetre.view.mapToScene(
        fenetre.view.viewport().rect()
    ).boundingRect()
    assert visible.intersects(noeud.sceneBoundingRect()), (
        "le nœud courant n'est pas visible à l'ouverture"
    )


def test_the_current_node_stays_selected_after_a_refresh(fenetre):
    """Le panneau latéral ne doit pas se vider sans raison.

    Le centrage sélectionnait AUSSI le nœud courant : après un checkout,
    la vue se déplaçait et le panneau se remplissait. Retirer le
    recentrage ne doit pas emporter cette sélection.
    """
    courant = str(fenetre.repository.head.target)
    fenetre.view.select_node(courant)
    assert fenetre.view.selected_oids() == (courant,)

    fenetre.refresh()

    assert fenetre.view.selected_oids() == (courant,), (
        "la sélection a été perdue au rafraîchissement"
    )


def test_refresh_does_not_call_the_centring(fenetre, monkeypatch):
    """Le test qui discrimine vraiment.

    Vérifié par mutation : remettre `_center_on_head()` dans `refresh()`
    ne faisait échouer aucun test, parce que la restauration explicite du
    défilement masquait l'effet. Mesurer la POSITION ne suffit donc pas —
    il faut vérifier que le centrage n'est pas appelé du tout.

    Sans cela, le recentrage pourrait revenir sans que rien ne le
    signale, et l'utilisateur serait de nouveau ramené de force sur sa
    branche à chaque action.
    """
    appels = []
    monkeypatch.setattr(
        fenetre, "_center_on_head", lambda: appels.append(1)
    )

    fenetre.refresh()

    assert appels == [], "`refresh()` a recentré la vue"


def test_the_recenter_action_is_the_only_caller(fenetre, monkeypatch):
    """Le bouton reste branché sur le centrage : c'est sa raison d'être."""
    appels = []
    monkeypatch.setattr(
        fenetre, "_center_on_head", lambda: appels.append(1)
    )

    fenetre.recenter_action.trigger()

    assert appels == [1], "le bouton « Recenter » ne centre plus"
