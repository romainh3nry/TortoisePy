"""Les deux entrées de comparaison, enfin câblées.

Vérifié avant correction : à la sélection de deux nœuds, le menu
proposait « Compare revisions » et « Show log of differences », toutes
deux **actives** et sans aucun effet — leur gestionnaire était
`_not_available`.

Le défaut allait plus loin que l'absence de gestionnaire :
`_selected_node()` rend `None` dès qu'il y a deux nœuds sélectionnés,
donc `_run_action` sortait avant même de regarder l'action. Ces deux-là
doivent être traitées en amont.

Une entrée qui ne répond pas est pire qu'une entrée absente : elle
apprend à se méfier de l'interface.
"""

from __future__ import annotations

import subprocess

import pygit2
import pytest

ENV = {
    "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
    "PATH": "/usr/bin:/bin:/usr/local/bin",
}


def _git(chemin, *args, check=True):
    return subprocess.run(
        ["git", "-C", str(chemin), *args], check=check,
        capture_output=True, env=ENV, text=True,
    )


@pytest.fixture
def depot(tmp_path):
    """Trois commits sur deux branches, pour avoir deux nœuds à comparer."""
    w = tmp_path / "w"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "a.txt").write_text("version 1\n")
    _git(w, "add", ".")
    _git(w, "commit", "-qm", "base")

    _git(w, "checkout", "-qb", "autre")
    (w / "a.txt").write_text("version 2\n")
    (w / "b.txt").write_text("b\n")
    _git(w, "add", "-A")
    _git(w, "commit", "-qm", "travail")

    _git(w, "checkout", "-q", "main")
    return pygit2.Repository(str(w))


@pytest.fixture
def fenetre(qtbot, depot):
    from tortoisepy.ui.main_window import MainWindow

    f = MainWindow(depot)
    qtbot.addWidget(f)
    return f


def _deux_noeuds(fenetre):
    """Sélectionne les deux extrémités du graphe."""
    oids = [n.oid for n in fenetre.graph.nodes]
    assert len(oids) >= 2, "le dépôt doit avoir deux nœuds"
    scene = fenetre.view.scene()
    from tortoisepy.ui.graph_items import NodeItem

    for item in scene.items():
        if isinstance(item, NodeItem) and item.node.oid in oids[:2]:
            item.setSelected(True)
    return tuple(sorted(oids[:2]))


# --- Compare revisions ---------------------------------------------------


def test_comparing_opens_a_window(qtbot, fenetre):
    """L'entrée ne faisait rien : elle doit maintenant montrer quelque chose."""
    _deux_noeuds(fenetre)
    fenetre.compare_revisions()

    assert fenetre._compare_windows, "aucune fenêtre de comparaison ouverte"


def test_the_comparison_lists_the_differing_files(qtbot, fenetre):
    """Le contenu, pas seulement la fenêtre."""
    _deux_noeuds(fenetre)
    fenetre.compare_revisions()

    comparaison = fenetre._compare_windows[-1]
    assert comparaison.file_count() >= 1, (
        "les fichiers qui diffèrent doivent être listés"
    )


def test_the_comparison_window_is_retained(qtbot, fenetre):
    """Sans référence, le ramasse-miettes la ferme aussitôt ouverte."""
    _deux_noeuds(fenetre)
    fenetre.compare_revisions()

    assert fenetre._compare_windows[-1].isVisible()


def test_comparing_needs_two_nodes(qtbot, fenetre):
    """Avec un seul nœud, il n'y a rien à comparer.

    Ne rien faire vaut mieux qu'ouvrir une fenêtre vide — et surtout
    mieux que de lever.
    """
    fenetre.view.scene().clearSelection()
    fenetre.compare_revisions()

    assert fenetre._compare_windows == []


def test_the_title_names_both_revisions(qtbot, fenetre):
    """Sans les deux abrégés, on ne sait plus ce qu'on compare."""
    oids = _deux_noeuds(fenetre)
    fenetre.compare_revisions()

    titre = fenetre._compare_windows[-1].windowTitle()
    assert oids[0][:8] in titre
    assert oids[1][:8] in titre


# --- Show log of differences --------------------------------------------


def test_the_log_of_differences_opens_a_log_window(qtbot, fenetre):
    """La seconde entrée morte : les commits qui séparent deux points."""
    _deux_noeuds(fenetre)
    fenetre.show_log_of_differences()

    assert fenetre._log_windows, "aucune fenêtre de journal ouverte"


def test_the_log_of_differences_is_bounded(qtbot, fenetre, depot):
    """`git log A..B` : pas tout l'historique.

    Le piège : ouvrir le journal complet, ce que « Show log » fait déjà —
    les deux entrées feraient alors la même chose.
    """
    _deux_noeuds(fenetre)
    fenetre.show_log_of_differences()

    journal = fenetre._log_windows[-1]
    assert journal.until is not None, (
        "le journal doit être borné par la révision de départ"
    )


def test_the_log_of_differences_needs_two_nodes(qtbot, fenetre):
    """Même garde que la comparaison."""
    fenetre.view.scene().clearSelection()
    fenetre.show_log_of_differences()

    assert fenetre._log_windows == []


# --- le menu les déclenche vraiment -------------------------------------


def test_the_menu_action_reaches_the_comparison(qtbot, fenetre):
    """Le chemin complet, depuis l'action du menu.

    `_selected_node()` rend `None` dès qu'il y a deux nœuds, donc
    `_run_action` sortait avant de regarder l'action : ces deux entrées
    doivent être traitées en amont.
    """
    _deux_noeuds(fenetre)
    fenetre._run_action("compare_revisions", None)

    assert fenetre._compare_windows, (
        "l'action du menu n'atteint pas la comparaison"
    )


def test_the_menu_action_reaches_the_log(qtbot, fenetre):
    """Et l'autre entrée, par le même chemin."""
    _deux_noeuds(fenetre)
    fenetre._run_action("show_log_of_differences", None)

    assert fenetre._log_windows


# --- lecture seule -------------------------------------------------------


def test_comparing_writes_nothing(qtbot, fenetre, depot):
    """§7.0 : comparer est une consultation."""
    refs_avant = {r: str(depot.references[r].target) for r in depot.references}

    _deux_noeuds(fenetre)
    fenetre.compare_revisions()
    fenetre.show_log_of_differences()

    assert {
        r: str(depot.references[r].target) for r in depot.references
    } == refs_avant
