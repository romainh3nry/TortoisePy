"""Une opération en cours doit se voir, et se conclure.

Signalé par l'utilisateur après un rebase : le graphe montrait HEAD
détaché et sa branche inchangée, alors qu'il avait bien résolu ses
conflits. Il manquait le « Continue » — et **rien ne le disait**.

Reproduit : dans cet état, la fenêtre de conflits affiche une liste
VIDE avec un bouton « Continue » actif, sans un mot d'explication. Et si
on la ferme, plus rien dans la fenêtre principale ne signale qu'un rebase
attend d'être conclu.

Deux manques distincts, donc deux remèdes :

  - un **bandeau** permanent dans la fenêtre principale ;
  - un **message** dans la fenêtre de conflits quand la liste est vide.
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
def depot_rebase_resolu(tmp_path):
    """L'état exact de l'utilisateur : conflits résolus, rebase en cours.

    C'est le cas trompeur — il n'y a plus rien à résoudre, mais
    l'opération n'est pas terminée et la branche n'a pas bougé.
    """
    w = tmp_path / "w"
    subprocess.run(
        ["git", "init", "-q", "-b", "develop", str(w)], check=True,
        capture_output=True,
    )
    conf = w / "conf.yml"

    conf.write_text("commun\n")
    _git(w, "add", ".")
    _git(w, "commit", "-qm", "base")

    _git(w, "checkout", "-qb", "cible")
    conf.write_text("commun\nrate-limit:\n  max: 40000\n")
    _git(w, "add", ".")
    _git(w, "commit", "-qm", "rate limit")

    _git(w, "checkout", "-q", "develop")
    _git(w, "checkout", "-qb", "feature")
    conf.write_text("commun\ntwoFactorAuth:\n  enabled: true\n")
    _git(w, "add", ".")
    _git(w, "commit", "-qm", "2fa")

    repo = pygit2.Repository(str(w))

    # Le rebase est lancé par l'APPLICATION, pas par la commande `git` :
    # libgit2 ne sait pas poursuivre un rebase démarré par git lui-même
    # (« does not support the interactive backend »), et l'application le
    # refuse alors avec un message explicite. Un test bâti sur `git
    # rebase` exercerait donc ce refus, pas le chemin réel.
    from tortoisepy.core.conflicts import resolve_with_content
    from tortoisepy.core.rebase import start_rebase

    debut = start_rebase(repo, "cible", branch=None)
    assert not debut.success, "le conflit doit interrompre le rebase"

    resolution = resolve_with_content(
        repo, "conf.yml", "commun\nrate-limit:\n  max: 40000\ntwoFactorAuth:\n"
    )
    assert resolution.success, resolution.git_error
    assert repo.index.conflicts is None, "plus aucun conflit"
    return repo


@pytest.fixture
def depot_propre(tmp_path):
    """Aucune opération en cours : le bandeau doit rester caché."""
    w = tmp_path / "propre"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "a.txt").write_text("a\n")
    _git(w, "add", ".")
    _git(w, "commit", "-qm", "base")
    return pygit2.Repository(str(w))


# --- le bandeau de la fenêtre principale ---------------------------------


def test_the_banner_appears_during_a_rebase(qtbot, depot_rebase_resolu):
    """L'assertion centrale : l'opération en cours doit se voir.

    Sans elle, l'utilisateur ferme la fenêtre de conflits et plus rien ne
    lui dit que son rebase attend d'être conclu — c'est exactement ce
    qui est arrivé.
    """
    from tortoisepy.ui.main_window import MainWindow

    fenetre = MainWindow(depot_rebase_resolu)
    qtbot.addWidget(fenetre)
    fenetre.show()

    assert fenetre.operation_banner.isVisible(), (
        "aucun bandeau alors qu'un rebase est en cours"
    )


def test_the_banner_names_the_operation(qtbot, depot_rebase_resolu):
    """« Une opération » ne dit pas laquelle ni quoi faire."""
    from tortoisepy.ui.main_window import MainWindow

    fenetre = MainWindow(depot_rebase_resolu)
    qtbot.addWidget(fenetre)
    fenetre.show()

    texte = fenetre.operation_banner.text().lower()
    assert "rebase" in texte


def test_the_banner_stays_hidden_on_a_clean_repository(qtbot, depot_propre):
    """Un bandeau toujours visible ne serait plus un signal.

    Le piège : l'afficher en permanence le rendrait invisible à force
    d'être là.
    """
    from tortoisepy.ui.main_window import MainWindow

    fenetre = MainWindow(depot_propre)
    qtbot.addWidget(fenetre)
    fenetre.show()

    assert not fenetre.operation_banner.isVisible()


def test_the_banner_offers_to_continue(qtbot, depot_rebase_resolu):
    """Dire qu'une opération est en cours sans donner la sortie serait
    une moitié de remède : le geste doit être à portée."""
    from tortoisepy.ui.main_window import MainWindow

    fenetre = MainWindow(depot_rebase_resolu)
    qtbot.addWidget(fenetre)
    fenetre.show()

    assert fenetre.banner_continue.isVisible()
    assert fenetre.banner_abort.isVisible()


def test_continuing_from_the_banner_finishes_the_rebase(
    qtbot, depot_rebase_resolu
):
    """Le bouton doit conclure, pas seulement ouvrir une fenêtre."""
    from tortoisepy.core.rebase import rebase_state
    from tortoisepy.ui.main_window import MainWindow

    fenetre = MainWindow(depot_rebase_resolu)
    qtbot.addWidget(fenetre)
    fenetre.show()

    fenetre.continue_operation()

    assert not rebase_state(depot_rebase_resolu).in_progress, (
        "le rebase n'a pas été conclu"
    )


def test_the_banner_disappears_once_finished(qtbot, depot_rebase_resolu):
    """Un bandeau qui resterait ferait croire l'opération toujours en cours."""
    from tortoisepy.ui.main_window import MainWindow

    fenetre = MainWindow(depot_rebase_resolu)
    qtbot.addWidget(fenetre)
    fenetre.show()

    fenetre.continue_operation()
    qtbot.waitUntil(
        lambda: not fenetre.operation_banner.isVisible(), timeout=5000
    )


# --- le message de la fenêtre de conflits --------------------------------


def test_an_empty_conflict_list_explains_itself(qtbot, depot_rebase_resolu):
    """Une liste vide et muette est indiscernable d'un défaut.

    C'est ce que l'utilisateur avait sous les yeux : plus aucun fichier,
    un bouton « Continue » actif, et rien pour relier les deux.
    """
    from tortoisepy.ui.conflict_window import ConflictWindow

    fenetre = ConflictWindow(depot_rebase_resolu)
    qtbot.addWidget(fenetre)
    fenetre.show()

    assert fenetre.file_count() == 0, "le dépôt de test doit être résolu"
    assert fenetre.hint_label.isVisible(), (
        "la liste est vide sans un mot d'explication"
    )
    assert "continue" in fenetre.hint_label.text().lower()


def test_the_hint_is_hidden_while_conflicts_remain(qtbot, tmp_path):
    """Tant qu'il reste à résoudre, le message serait un contresens."""
    from tortoisepy.ui.conflict_window import ConflictWindow

    w = tmp_path / "conflit"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    conf = w / "c.yml"
    conf.write_text("a\n")
    _git(w, "add", ".")
    _git(w, "commit", "-qm", "base")
    _git(w, "checkout", "-qb", "autre")
    conf.write_text("b\n")
    _git(w, "add", ".")
    _git(w, "commit", "-qm", "autre")
    _git(w, "checkout", "-q", "main")
    conf.write_text("c\n")
    _git(w, "add", ".")
    _git(w, "commit", "-qm", "main")
    _git(w, "merge", "autre", check=False)

    fenetre = ConflictWindow(pygit2.Repository(str(w)))
    qtbot.addWidget(fenetre)
    fenetre.show()

    assert fenetre.file_count() > 0
    assert not fenetre.hint_label.isVisible()
