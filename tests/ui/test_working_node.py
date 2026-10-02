"""Un nœud « Uncommitted changes » au-dessus de la branche courante.

Demandé par l'utilisateur, après avoir écarté la pastille : trop de bruit
sur un rendu soigné. Le nœud fantôme est ce que font GitKraken et Fork —
il dit littéralement de quoi il s'agit, et il est **cliquable**, ce qui
règle du même coup l'accès au diff.

Il ne correspond à AUCUN commit : son OID est une valeur sentinelle, et
il ne doit jamais être confondu avec un vrai nœud par le reste du code
(sélection, panneau latéral, actions du menu).
"""

from __future__ import annotations

import subprocess

import pygit2
import pytest

from tortoisepy.core.model import NodeKind
from tortoisepy.ui.graph_items import NodeItem
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
def depot(tmp_path):
    w = tmp_path / "w"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "a.txt").write_text("a\n")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "base")
    _git(w, "checkout", "-q", "-b", "feature")
    (w / "b.txt").write_text("b\n")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "sur feature")
    _git(w, "checkout", "-q", "main")
    return w


def _noeuds(fenetre):
    return [
        item for item in fenetre.view.scene().items()
        if isinstance(item, NodeItem)
    ]


def _working(fenetre):
    trouves = [
        n for n in _noeuds(fenetre) if n.node.kind is NodeKind.WORKING
    ]
    return trouves[0] if trouves else None


def test_no_working_node_when_the_tree_is_clean(qtbot, depot):
    """Le cas le plus fréquent : rien ne doit s'ajouter au graphe."""
    fenetre = MainWindow(pygit2.Repository(str(depot)))
    qtbot.addWidget(fenetre)

    assert _working(fenetre) is None


def test_a_working_node_appears_when_work_is_pending(qtbot, depot):
    """L'assertion centrale : voir d'un coup d'œil qu'il reste du travail."""
    (depot / "a.txt").write_text("modifie sans commit\n")

    fenetre = MainWindow(pygit2.Repository(str(depot)))
    qtbot.addWidget(fenetre)

    noeud = _working(fenetre)
    assert noeud is not None, "aucun nœud « Uncommitted changes »"


def test_it_sits_above_the_current_branch(qtbot, depot):
    """Au-dessus de la branche courante, pas ailleurs : c'est de LÀ que
    partent les modifications."""
    (depot / "a.txt").write_text("modifie\n")

    fenetre = MainWindow(pygit2.Repository(str(depot)))
    qtbot.addWidget(fenetre)

    courant = str(fenetre.repository.head.target)
    noeud_courant = next(
        n for n in _noeuds(fenetre) if n.node.oid == courant
    )
    travail = _working(fenetre)

    # `y` croît vers le BAS en coordonnées Qt : au-dessus = y plus petit.
    assert travail.sceneBoundingRect().center().y() < (
        noeud_courant.sceneBoundingRect().center().y()
    ), "le nœud de travail doit être au-dessus de la branche courante"


def test_it_is_not_mistaken_for_a_commit(qtbot, depot):
    """Il ne correspond à aucun commit : le dépôt ne doit pas le connaître.

    Sans cette garantie, un clic droit proposerait « Cherry Pick » ou
    « Reset to this » sur un OID qui n'existe pas — échec garanti.
    """
    (depot / "a.txt").write_text("modifie\n")

    fenetre = MainWindow(pygit2.Repository(str(depot)))
    qtbot.addWidget(fenetre)

    travail = _working(fenetre)
    repo = fenetre.repository

    # pygit2 REFUSE la sentinelle (`InvalidError`) au lieu de rendre
    # `None` : c'est exactement pourquoi tout chemin qui manipule
    # l'histoire doit l'écarter AVANT d'interroger le dépôt.
    with pytest.raises(Exception):
        repo.get(travail.node.oid)


def test_the_context_menu_offers_nothing_destructive(qtbot, depot):
    """Un nœud sans commit n'a pas d'histoire à manipuler."""
    from tortoisepy.ui.context_menu import build_menu_model

    (depot / "a.txt").write_text("modifie\n")
    fenetre = MainWindow(pygit2.Repository(str(depot)))
    qtbot.addWidget(fenetre)

    travail = _working(fenetre)
    menu = build_menu_model((travail.node,), fenetre.state)

    def actions(entrees):
        trouvees = set()
        for e in entrees:
            if e.action:
                trouvees.add(e.action)
            if e.children:
                trouvees |= actions(e.children)
        return trouvees

    interdites = {
        "cherry_pick", "reset_to", "revert_commit", "create_branch",
        "create_tag", "checkout_branch", "merge_branch",
    }
    assert not (actions(menu) & interdites), actions(menu) & interdites


def test_the_working_node_links_to_the_current_branch(qtbot, depot):
    """Une arête le relie à la branche : sinon il flotterait, orphelin."""
    from tortoisepy.ui.graph_items import EdgeItem

    (depot / "a.txt").write_text("modifie\n")
    fenetre = MainWindow(pygit2.Repository(str(depot)))
    qtbot.addWidget(fenetre)

    travail = _working(fenetre)
    courant = str(fenetre.repository.head.target)
    aretes = [
        e for e in fenetre.view.scene().items() if isinstance(e, EdgeItem)
    ]
    assert any(
        e.edge.ancestor == courant and e.edge.descendant == travail.node.oid
        for e in aretes
    ), "aucune arête entre la branche courante et le nœud de travail"



def test_selecting_it_does_not_open_the_commit_window(qtbot, depot):
    """Signalé par l'utilisateur : l'app gelait au CLIC sur le nœud.

    Un simple clic sélectionne — il passe par `_on_selection_changed`,
    qui appelait `_show_commits`, qui ouvrait la fenêtre de commit.
    Sur un gros dépôt, sa construction scanne tout l'arbre de travail :
    plusieurs secondes de gel pour un geste qui ne demandait rien.

    Seul le DOUBLE-clic doit l'ouvrir.
    """
    from tortoisepy.core.model import WORKING_OID

    (depot / "a.txt").write_text("modifie\n")
    fenetre = MainWindow(pygit2.Repository(str(depot)))
    qtbot.addWidget(fenetre)

    fenetre.view.select_node(WORKING_OID)
    fenetre._on_selection_changed()

    assert fenetre.commit_window is None, (
        "un simple clic ne doit pas ouvrir la fenêtre de commit"
    )


def test_selecting_it_clears_the_side_panel(qtbot, depot):
    """Il n'a aucun commit à lister : le panneau doit se vider,
    pas garder l'historique du nœud précédent."""
    from tortoisepy.core.model import WORKING_OID

    (depot / "a.txt").write_text("modifie\n")
    fenetre = MainWindow(pygit2.Repository(str(depot)))
    qtbot.addWidget(fenetre)

    courant = str(fenetre.repository.head.target)
    fenetre.view.select_node(courant)
    fenetre._on_selection_changed()

    fenetre.view.select_node(WORKING_OID)
    fenetre._on_selection_changed()

    assert fenetre.commit_panel.count() == 0, (
        "le panneau garde l'historique d'un autre nœud"
    )


def test_double_clicking_still_opens_it(qtbot, depot):
    """Le geste explicite, lui, doit continuer de marcher."""
    from tortoisepy.core.model import WORKING_OID

    (depot / "a.txt").write_text("modifie\n")
    fenetre = MainWindow(pygit2.Repository(str(depot)))
    qtbot.addWidget(fenetre)

    ouvertures = []
    fenetre.open_commit_window = lambda: ouvertures.append(1)
    fenetre._on_node_double_clicked(WORKING_OID)

    assert ouvertures, "le double-clic doit ouvrir la fenêtre de commit"


def test_its_label_stays_readable_when_selected(qtbot, depot):
    """Signalé par l'utilisateur, capture à l'appui : le texte disparaissait.

    La sélection passe le texte en blanc, pour le fond rouge foncé des
    nœuds ordinaires. Le nœud de travail garde un fond CLAIR : le blanc
    y devient invisible.
    """
    from PySide6.QtWidgets import QGraphicsSimpleTextItem
    from tortoisepy.core.model import WORKING_OID

    (depot / "a.txt").write_text("modifie\n")
    fenetre = MainWindow(pygit2.Repository(str(depot)))
    qtbot.addWidget(fenetre)

    travail = _working(fenetre)
    travail.setSelected(True)
    travail.refresh_colors()

    fond = travail.brush().color()
    for enfant in travail.childItems():
        if isinstance(enfant, QGraphicsSimpleTextItem):
            texte = enfant.brush().color()
            ecart = abs(texte.lightness() - fond.lightness())
            assert ecart > 60, (
                f"texte {texte.name()} sur fond {fond.name()} : illisible"
            )


def test_its_fill_does_not_turn_red_when_selected(qtbot, depot):
    """Il n'est pas un commit : le rouge de sélection n'a pas de sens ici."""
    from tortoisepy.core.model import WORKING_OID
    from tortoisepy.ui import theme

    (depot / "a.txt").write_text("modifie\n")
    fenetre = MainWindow(pygit2.Repository(str(depot)))
    qtbot.addWidget(fenetre)

    travail = _working(fenetre)
    travail.setSelected(True)
    travail.refresh_colors()

    assert travail.brush().color().name() != theme.PALETTE.selected.name()
