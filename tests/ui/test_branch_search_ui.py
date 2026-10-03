"""Le champ de recherche de branches et la navigation entre résultats.

Demandé par l'utilisateur : « rechercher une branche et centrer dessus
rapidement ; si plusieurs branches ont le même mot-clé, on navigue entre
elles à chaque appui sur Entrée ».

Champ SÉPARÉ de celui des commits (choix de l'utilisateur) : sans
résultat, il le dit et ne retombe pas sur la recherche de commits.
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
    """Trois branches contenant « login », sur des commits distincts."""
    w = tmp_path / "w"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "a.txt").write_text("a\n")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "base")

    for nom in ("feature-login", "fix-login-bug", "autre-chose"):
        _git(w, "checkout", "-q", "-b", nom, "main")
        (w / f"{nom}.txt").write_text("x\n")
        _git(w, "add", ".")
        _git(w, "commit", "-q", "-m", nom)
    _git(w, "checkout", "-q", "main")

    fenetre = MainWindow(pygit2.Repository(str(w)))
    qtbot.addWidget(fenetre)
    fenetre.resize(600, 500)
    fenetre.show()
    return fenetre


def test_the_field_exists(fenetre):
    """Un champ séparé de celui des commits (choix de l'utilisateur)."""
    assert hasattr(fenetre, "branch_search_field")
    assert fenetre.branch_search_field is not fenetre.search_field


def test_searching_centres_on_the_branch(fenetre):
    """L'assertion centrale : trouver une branche et s'y rendre."""
    from tortoisepy.ui.graph_items import NodeItem

    fenetre.branch_search_field.setText("autre-chose")
    fenetre.find_branch()

    cible = str(fenetre.repository.branches.local["autre-chose"].target)
    noeud = next(
        i for i in fenetre.view.scene().items()
        if isinstance(i, NodeItem) and i.node.oid == cible
    )
    visible = fenetre.view.mapToScene(
        fenetre.view.viewport().rect()
    ).boundingRect()
    assert visible.intersects(noeud.sceneBoundingRect()), (
        "la branche trouvée n'est pas visible"
    )


def test_the_found_branch_is_selected(fenetre):
    """La sélection remplit le panneau : on voit ce qu'on a trouvé."""
    fenetre.branch_search_field.setText("autre-chose")
    fenetre.find_branch()

    cible = str(fenetre.repository.branches.local["autre-chose"].target)
    assert fenetre.view.selected_oids() == (cible,)


def test_pressing_enter_cycles_through_matches(fenetre):
    """Demandé explicitement : naviguer entre les résultats."""
    fenetre.branch_search_field.setText("login")

    fenetre.find_branch()
    premier = fenetre.view.selected_oids()
    fenetre.find_branch()
    second = fenetre.view.selected_oids()

    assert premier and second
    assert premier != second, "Entrée n'a pas changé de résultat"


def test_the_cycle_wraps_around(fenetre):
    """Après le dernier, on revient au premier — sinon la touche
    semblerait cassée une fois au bout."""
    fenetre.branch_search_field.setText("login")

    fenetre.find_branch()
    premier = fenetre.view.selected_oids()
    fenetre.find_branch()
    fenetre.find_branch()          # deux résultats : retour au premier

    assert fenetre.view.selected_oids() == premier


def test_changing_the_pattern_restarts_the_cycle(fenetre):
    """Un nouveau motif ne doit pas hériter de la position précédente."""
    fenetre.branch_search_field.setText("login")
    fenetre.find_branch()
    fenetre.find_branch()

    fenetre.branch_search_field.setText("autre")
    fenetre.find_branch()

    cible = str(fenetre.repository.branches.local["autre-chose"].target)
    assert fenetre.view.selected_oids() == (cible,)


def test_no_match_says_so(fenetre):
    """Choix de l'utilisateur : le dire, sans retomber sur les commits."""
    avant = fenetre.view.selected_oids()
    fenetre.branch_search_field.setText("inexistante")
    fenetre.find_branch()

    assert "no branch" in fenetre.statusBar().currentMessage().lower()
    assert fenetre.view.selected_oids() == avant, (
        "la vue a bougé alors qu'aucune branche ne correspond"
    )


def test_an_empty_pattern_does_nothing(fenetre):
    avant = fenetre.view.selected_oids()
    fenetre.branch_search_field.setText("   ")
    fenetre.find_branch()
    assert fenetre.view.selected_oids() == avant


def test_the_status_says_how_many_were_found(fenetre):
    """Savoir qu'il y en a plusieurs invite à ré-appuyer sur Entrée."""
    fenetre.branch_search_field.setText("login")
    fenetre.find_branch()

    message = fenetre.statusBar().currentMessage()
    assert "2" in message, message


# --- ⌘F vise la recherche de branches -----------------------------------


def test_the_search_shortcut_focuses_the_branch_field(fenetre):
    """Demandé par l'utilisateur : ⌘F pointe vers la recherche de
    branches, et non plus vers celle des commits.

    Le champ des commits reste atteignable au clic, dans le panneau
    latéral où il vit — il ne devient pas inaccessible.
    """
    fenetre.focus_search()

    assert fenetre.branch_search_field.hasFocus(), (
        "⌘F ne place pas le curseur dans la recherche de branches"
    )


def test_the_shortcut_selects_what_is_already_there(fenetre):
    """Une nouvelle recherche remplace la précédente sans l'effacer
    d'abord — comportement repris du champ des commits."""
    fenetre.branch_search_field.setText("ancien motif")
    fenetre.focus_search()

    assert fenetre.branch_search_field.selectedText() == "ancien motif"


def test_the_commit_field_stays_usable(fenetre):
    """Rediriger le raccourci ne doit pas casser l'autre recherche."""
    fenetre.search_field.setText("un commit")
    fenetre.run_search()      # ne doit pas lever
    assert fenetre.search_field.text() == "un commit"


def test_the_search_action_has_no_toolbar_button(fenetre):
    """Le champ de recherche rend le bouton inutile.

    Chaque entrée du catalogue devient un bouton de barre d'outils. Le
    bouton « Search » existait donc depuis toujours ; le renommer en
    « Find branch » l'a simplement rendu visible à l'utilisateur, qui
    l'a signalé comme un ajout.

    Il reste une ACTION — le raccourci ⌘F continue de marcher — mais il
    ne prend plus de place à côté du champ qu'il met en focus.
    """
    libelles = [a.text() for a in fenetre.toolbar.actions() if a.text()]
    assert "Find branch" not in libelles, libelles

    # L'action elle-même survit : c'est elle que porte le raccourci.
    assert "search" in fenetre.actions_by_id


def test_the_shortcut_still_works_without_the_button(fenetre):
    """Retirer le bouton ne doit pas désactiver ⌘F."""
    fenetre.actions_by_id["search"].trigger()
    assert fenetre.branch_search_field.hasFocus()
