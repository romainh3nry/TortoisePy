"""Phase 21, côté UI : l'avertissement avant d'écraser une locale.

Le projet a déjà payé cher un garde-fou qui n'en était pas un : en phase
11, « Drop stash » portait un drapeau `needs_confirmation`, un test
l'affirmait, et le stash était pourtant détruit même sur un refus. La
porte réelle est `ctx.confirm` — c'est elle que ces tests éprouvent.
"""

from __future__ import annotations

import pathlib
import subprocess

import pygit2
import pytest

from tortoisepy.core.model import DisplayNode, NodeKind, Ref, RefType
from tortoisepy.core.state import RepositoryState
from tortoisepy.ui.actions import ActionContext, execute_action


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
def depot(tmp_path):
    """Un clone où `test-branch` existe sur le serveur ET en local,
    les deux ayant divergé."""
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
    _git(travail, "commit", "-q", "-m", "cote serveur")
    _git(travail, "push", "-q", "origin", "test-branch")

    # La locale diverge : un commit que le serveur n'a pas.
    (travail / "c.txt").write_text("c\n")
    _git(travail, "add", ".")
    _git(travail, "commit", "-q", "-m", "travail local non pousse")
    _git(travail, "checkout", "-q", "main")
    _git(travail, "fetch", "-q", "origin")

    return pygit2.Repository(str(travail))


def _etat(repo) -> RepositoryState:
    return RepositoryState(
        head_oid=str(repo.head.target),
        head_branch=repo.head.shorthand,
        detached=False,
        has_unstaged_changes=False,
        has_staged_changes=False,
        has_conflicts=False,
        operation_in_progress=None,
        conflicted_paths=(),
    )


def _noeud(nom: str) -> DisplayNode:
    return DisplayNode(
        oid="a" * 40,
        kind=NodeKind.REF,
        refs=(Ref(nom, RefType.REMOTE_BRANCH, "a" * 40),),
    )


def _contexte(repo, branche, reponse):
    """`reponse` est ce que l'utilisateur répond à la confirmation."""
    vues = []

    def confirm(parent, demande):
        vues.append(demande)
        return reponse

    ctx = ActionContext(
        repository=repo,
        node=_noeud(branche),
        state=_etat(repo),
        confirm=confirm,
        chosen_branch=branche,
    )
    return ctx, vues


def test_refusing_the_warning_changes_nothing(depot):
    """L'assertion centrale : « Annuler » doit tout laisser intact.

    C'est exactement la régression de la phase 11 — un refus qui
    détruisait quand même.
    """
    avant_head = depot.head.shorthand
    avant_locale = str(depot.branches.local.get("test-branch").target)

    ctx, vues = _contexte(depot, "origin/test-branch", reponse=False)
    resultat = execute_action("checkout_branch", ctx)

    assert resultat is None, "une action annulée ne rend aucun résultat"
    assert len(vues) == 1, "l'utilisateur doit avoir été averti"
    assert depot.head.shorthand == avant_head, "HEAD a bougé malgré le refus"
    assert str(depot.branches.local.get("test-branch").target) == avant_locale, (
        "la branche locale a été écrasée malgré le refus"
    )


def test_accepting_the_warning_overwrites_and_switches(depot):
    distante = str(depot.branches.remote.get("origin/test-branch").target)

    ctx, vues = _contexte(depot, "origin/test-branch", reponse=True)
    resultat = execute_action("checkout_branch", ctx)

    assert resultat is not None and resultat.success, resultat
    assert len(vues) == 1
    assert depot.head.shorthand == "test-branch"
    assert str(depot.branches.local.get("test-branch").target) == distante


def test_the_warning_names_the_commits_that_would_be_lost(depot):
    """§D56 : compter ne suffit pas, il faut nommer."""
    ctx, vues = _contexte(depot, "origin/test-branch", reponse=False)
    execute_action("checkout_branch", ctx)

    message = vues[0].message
    assert "1 local commit" in message, message
    assert "travail local non pousse" in message, message
    assert vues[0].destructive is True


def test_no_warning_when_there_is_nothing_to_lose(depot):
    """§D57 : une alerte qui ne protège rien finit validée sans être lue."""
    # On aligne la locale sur la distante : plus rien à perdre.
    _git(depot.workdir, "branch", "-f", "test-branch", "origin/test-branch")

    ctx, vues = _contexte(depot, "origin/test-branch", reponse=False)
    resultat = execute_action("checkout_branch", ctx)

    assert vues == [], "aucune confirmation ne devait être demandée"
    assert resultat is not None and resultat.success
    assert depot.head.shorthand == "test-branch"


def test_no_warning_when_the_local_branch_does_not_exist(depot):
    """Créer une branche ne détruit rien."""
    _git(depot.workdir, "branch", "-q", "-D", "test-branch")

    ctx, vues = _contexte(depot, "origin/test-branch", reponse=False)
    resultat = execute_action("checkout_branch", ctx)

    assert vues == []
    assert resultat is not None and resultat.success
    assert depot.head.shorthand == "test-branch"
