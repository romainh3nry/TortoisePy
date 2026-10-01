"""Phase 21 : checkout d'une branche distante sans locale préexistante.

Vérifié sur git avant d'écrire une ligne : `git checkout test-branch` sur
un dépôt qui ne porte que `origin/test-branch` crée la locale **et**
configure son suivi. Le suivi n'est pas un détail — sans lui, un `push`
ou un `pull` ultérieur ne sait pas quelle branche distante viser.
"""

from __future__ import annotations

import subprocess

import pygit2
import pytest

from tortoisepy.core.operations import checkout_branch, local_commits_ahead


def _git(chemin, *args):
    subprocess.run(
        ["git", "-C", str(chemin), *args],
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
            "PATH": "/usr/bin:/bin:/usr/local/bin",
        },
    )


@pytest.fixture
def depot_avec_distante(tmp_path):
    """Un clone dont `test-branch` n'existe QUE sur le serveur."""
    serveur = tmp_path / "serveur.git"
    _git(tmp_path, "init", "-q", "--bare", str(serveur))

    travail = tmp_path / "travail"
    _git(tmp_path, "clone", "-q", str(serveur), str(travail))

    (travail / "a.txt").write_text("a\n")
    _git(travail, "add", ".")
    _git(travail, "commit", "-q", "-m", "base")
    _git(travail, "push", "-q", "origin", "HEAD:refs/heads/main")
    _git(travail, "branch", "-q", "-M", "main")

    _git(travail, "checkout", "-q", "-b", "test-branch")
    (travail / "b.txt").write_text("b\n")
    _git(travail, "add", ".")
    _git(travail, "commit", "-q", "-m", "feature")
    _git(travail, "push", "-q", "origin", "test-branch")

    # On supprime la locale : il ne reste que `origin/test-branch`.
    _git(travail, "checkout", "-q", "main")
    _git(travail, "branch", "-q", "-D", "test-branch")
    _git(travail, "fetch", "-q", "origin")

    return pygit2.Repository(str(travail))


def test_checking_out_a_remote_creates_the_local_branch(depot_avec_distante):
    """Le geste demandé : un seul clic, plus besoin de créer la branche."""
    repo = depot_avec_distante
    assert "test-branch" not in list(repo.branches.local)

    resultat = checkout_branch(repo, "origin/test-branch")

    assert resultat.success, resultat.git_error
    assert "test-branch" in list(repo.branches.local)
    assert repo.head.shorthand == "test-branch"


def test_the_created_branch_tracks_the_remote(depot_avec_distante):
    """§D54 : l'assertion qui distingue cette phase d'un simple `branch`.

    Sans le suivi, `push` et `pull` ne savent pas quoi viser, et
    l'indicateur d'avance/retard reste muet. C'est ce que fait `git
    checkout` d'une distante — vérifié.
    """
    repo = depot_avec_distante
    checkout_branch(repo, "origin/test-branch")

    locale = repo.branches.local.get("test-branch")
    assert locale.upstream is not None, "aucun suivi configuré"
    assert locale.upstream.branch_name == "origin/test-branch"


def test_the_local_name_drops_only_the_remote_prefix(tmp_path):
    """`origin/feature/x` donne `feature/x`, jamais `x`.

    Couper à la dernière barre oblique casserait toutes les branches à
    préfixe, qui sont la norme dans les équipes.
    """
    from tortoisepy.core.operations import local_name_for

    assert local_name_for("origin/test-branch") == "test-branch"
    assert local_name_for("origin/feature/sous-truc") == "feature/sous-truc"
    assert local_name_for("upstream/release/1.2") == "release/1.2"


def test_a_local_branch_is_still_checked_out_normally(depot_avec_distante):
    """Le comportement existant ne régresse pas."""
    repo = depot_avec_distante
    resultat = checkout_branch(repo, "main")

    assert resultat.success
    assert repo.head.shorthand == "main"


def test_an_unknown_branch_is_refused(depot_avec_distante):
    resultat = checkout_branch(depot_avec_distante, "origin/fantome")
    assert not resultat.success


def test_local_commits_ahead_lists_what_an_overwrite_would_destroy(
    depot_avec_distante,
):
    """§D56 : compter et nommer, pour que l'utilisateur puisse décider.

    « La branche sera écrasée » ne dit pas si l'on perd une semaine de
    travail ou rien du tout.
    """
    repo = depot_avec_distante
    checkout_branch(repo, "origin/test-branch")

    import pathlib

    travail = repo.workdir
    (pathlib.Path(travail) / "c.txt").write_text("c\n")
    _git(travail, "add", ".")
    _git(travail, "commit", "-q", "-m", "travail local non poussé")

    perdus = local_commits_ahead(repo, "test-branch", "origin/test-branch")

    assert len(perdus) == 1
    assert perdus[0][1] == "travail local non poussé"
    assert len(perdus[0][0]) == 8, "l'OID doit être court, pour l'affichage"


def test_local_commits_ahead_is_empty_when_in_sync(depot_avec_distante):
    """§D57 : rien à perdre, donc rien à avertir."""
    repo = depot_avec_distante
    checkout_branch(repo, "origin/test-branch")

    assert local_commits_ahead(repo, "test-branch", "origin/test-branch") == ()


def test_local_commits_ahead_tolerates_an_unknown_branch(depot_avec_distante):
    """Ne doit jamais lever : c'est une fonction d'affichage."""
    repo = depot_avec_distante
    assert local_commits_ahead(repo, "fantome", "origin/test-branch") == ()
    assert local_commits_ahead(repo, "main", "origin/fantome") == ()
