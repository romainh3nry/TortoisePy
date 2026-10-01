"""Le fetch retire les branches distantes disparues du serveur.

Signalé par l'utilisateur : une branche supprimée côté GitLab restait
visible dans le graphe malgré plusieurs `fetch`. Ce n'était pas un défaut
d'affichage — l'app montrait fidèlement le dépôt local, où la ref de
suivi survivait.

Mesuré dans un dépôt jetable :

    avant fetch          : ['origin/ephemere', 'origin/main']
    apres fetch (defaut) : ['origin/ephemere', 'origin/main']   <- reste
    apres fetch(PRUNE)   : ['origin/main']

`git fetch` nu ne supprime rien : une branche absente du serveur n'est
plus annoncée, donc git n'a rien à mettre à jour pour elle et laisse la
ref en place. Le nettoyage est opt-in (`--prune`).

La suppression est **annoncée** dans le résumé : retirer des refs en
silence priverait l'utilisateur de l'information qui lui manquait
justement.
"""

from __future__ import annotations

import subprocess

import pygit2
import pytest

from tortoisepy.core.operations import fetch_remote


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
def clone_avec_branche_disparue(tmp_path):
    """Un clone dont une branche a été supprimée côté serveur."""
    serveur = tmp_path / "s.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", str(serveur)], check=True,
        capture_output=True,
    )
    travail = tmp_path / "w"
    subprocess.run(
        ["git", "clone", "-q", str(serveur), str(travail)], check=True,
        capture_output=True,
    )

    (travail / "a.txt").write_text("a")
    _git(travail, "add", ".")
    _git(travail, "commit", "-q", "-m", "base")
    _git(travail, "push", "-q", "origin", "HEAD:refs/heads/main")

    _git(travail, "checkout", "-q", "-b", "ephemere")
    (travail / "b.txt").write_text("b")
    _git(travail, "add", ".")
    _git(travail, "commit", "-q", "-m", "travail")
    _git(travail, "push", "-q", "origin", "ephemere")
    _git(travail, "checkout", "-q", "main")
    _git(travail, "branch", "-q", "-D", "ephemere")

    # Le serveur supprime la branche, comme GitLab le ferait.
    subprocess.run(
        ["git", "-C", str(serveur), "branch", "-D", "ephemere"],
        check=True, capture_output=True,
    )
    return travail


def _refs_distantes(chemin) -> list[str]:
    repo = pygit2.Repository(str(chemin))
    return sorted(
        r for r in repo.references if r.startswith("refs/remotes/")
    )


def test_fetch_removes_a_branch_deleted_on_the_server(
    clone_avec_branche_disparue,
):
    """Le cœur de la demande : plus de branche fantôme dans le graphe."""
    chemin = clone_avec_branche_disparue
    assert "refs/remotes/origin/ephemere" in _refs_distantes(chemin)

    fetch_remote(pygit2.Repository(str(chemin)))

    assert "refs/remotes/origin/ephemere" not in _refs_distantes(chemin), (
        "la ref de suivi obsolète survit au fetch"
    )


def test_fetch_keeps_the_branches_that_still_exist(
    clone_avec_branche_disparue,
):
    """Le prune ne doit emporter que ce qui a disparu du serveur."""
    chemin = clone_avec_branche_disparue
    fetch_remote(pygit2.Repository(str(chemin)))

    assert "refs/remotes/origin/main" in _refs_distantes(chemin)


def test_the_summary_names_what_was_pruned(clone_avec_branche_disparue):
    """Supprimer des refs en silence priverait l'utilisateur de la
    réponse qu'il cherchait."""
    chemin = clone_avec_branche_disparue
    resultat = fetch_remote(pygit2.Repository(str(chemin)))

    assert resultat.success
    assert "ephemere" in resultat.summary, resultat.summary
    assert "gone" in resultat.summary.lower(), resultat.summary


def test_fetch_reports_a_change_when_only_pruning(
    clone_avec_branche_disparue,
):
    """Le graphe doit se rafraîchir : des refs ont disparu.

    Sans cela, le fetch répondrait « already up to date » et l'interface
    continuerait d'afficher la branche fantôme — exactement le symptôme
    signalé.
    """
    chemin = clone_avec_branche_disparue
    resultat = fetch_remote(pygit2.Repository(str(chemin)))

    assert resultat.needs_refresh, (
        "un prune change le graphe : l'affichage doit être reconstruit"
    )


def test_a_fetch_without_changes_stays_quiet(clone_avec_branche_disparue):
    """Deux fetchs de suite : le second n'a plus rien à annoncer."""
    chemin = clone_avec_branche_disparue
    fetch_remote(pygit2.Repository(str(chemin)))
    second = fetch_remote(pygit2.Repository(str(chemin)))

    assert second.success
    assert "up to date" in second.summary
    assert not second.needs_refresh
