import os
import subprocess

import pygit2
import pytest

from tortoisepy.core.operations import push_branch


def run_git(path, *args):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
    }
    return subprocess.run(
        ["git", *args], cwd=path, env=env, capture_output=True, text=True
    )


@pytest.fixture
def pair(tmp_path):
    """Un dépôt nu servant de serveur, et un clone de travail."""
    bare = tmp_path / "serveur.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", str(bare)], capture_output=True
    )
    work = tmp_path / "travail"
    subprocess.run(
        ["git", "clone", "-q", str(bare), str(work)], capture_output=True
    )
    (work / "f.txt").write_text("base\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "base")
    run_git(work, "push", "-q", "origin", "HEAD")
    return bare, pygit2.Repository(str(work))


def server_log(bare) -> str:
    return subprocess.run(
        ["git", "log", "--oneline"], cwd=bare, capture_output=True, text=True
    ).stdout


def test_push_sends_the_commit(pair):
    bare, repo = pair
    (repo.workdir and None)
    from pathlib import Path
    Path(repo.workdir, "f.txt").write_text("suite\n")
    run_git(repo.workdir, "add", ".")
    run_git(repo.workdir, "commit", "-q", "-m", "à pousser")

    result = push_branch(repo)
    assert result.success is True, result.git_error
    assert "à pousser" in server_log(bare)


def test_push_uses_the_current_branch(pair):
    """Vérifié : un clone récent est sur `main`, pas `master`."""
    bare, repo = pair
    run_git(repo.workdir, "checkout", "-q", "-b", "une-autre-branche")
    from pathlib import Path
    Path(repo.workdir, "g.txt").write_text("x\n")
    run_git(repo.workdir, "add", ".")
    run_git(repo.workdir, "commit", "-q", "-m", "sur une autre branche")

    result = push_branch(repo)
    assert result.success is True, result.git_error

    refs = subprocess.run(
        ["git", "branch"], cwd=bare, capture_output=True, text=True
    ).stdout
    assert "une-autre-branche" in refs


def test_rejected_push_reports_the_server_message(pair, tmp_path):
    """Review Focus 5 : le serveur a avancé entre-temps."""
    bare, repo = pair

    other = tmp_path / "concurrent"
    subprocess.run(
        ["git", "clone", "-q", str(bare), str(other)], capture_output=True
    )
    (other / "concurrent.txt").write_text("x\n")
    run_git(other, "add", ".")
    run_git(other, "commit", "-q", "-m", "concurrent")
    run_git(other, "push", "-q")

    from pathlib import Path
    Path(repo.workdir, "local.txt").write_text("y\n")
    run_git(repo.workdir, "add", ".")
    run_git(repo.workdir, "commit", "-q", "-m", "local")

    result = push_branch(repo)
    assert result.success is False
    assert result.git_error


def test_push_without_remote_fails_cleanly(tmp_path):
    path = tmp_path / "sans-remote"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "f.txt").write_text("a\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "base")

    result = push_branch(pygit2.Repository(str(path)))
    assert result.success is False
    assert "remote" in (result.git_error or "").lower()


def test_push_from_detached_head_fails_cleanly(pair):
    """Sans branche, il n'y a rien à pousser."""
    bare, repo = pair
    head = str(repo.head.target)
    run_git(repo.workdir, "checkout", "-q", "--detach", head)

    result = push_branch(pygit2.Repository(repo.path))
    assert result.success is False


def test_push_does_not_change_the_local_graph(pair):
    """Pousser n'ajoute ni ne déplace de ref locale."""
    bare, repo = pair
    before = {r for r in repo.references}
    push_branch(repo)
    assert {r for r in repo.references} == before


def test_push_reports_progress(pair):
    """Le rappel de progression doit être celui du push, pas du fetch."""
    bare, repo = pair
    from pathlib import Path
    Path(repo.workdir, "f.txt").write_text("suite\n")
    run_git(repo.workdir, "add", ".")
    run_git(repo.workdir, "commit", "-q", "-m", "à pousser")

    seen = []
    result = push_branch(repo, on_progress=lambda a, b: seen.append((a, b)))
    assert result.success is True, result.git_error
    assert seen, (
        "push_transfer_progress n'a pas été appelé — FetchCallbacks utilise "
        "transfer_progress, qui est la progression du fetch"
    )


def test_progress_callback_takes_three_arguments():
    """Vérifié : la signature du push a un argument de plus que le fetch.

    `push_transfer_progress(objects_pushed, total_objects, bytes_pushed)`.
    Une méthode à deux paramètres lèverait TypeError pendant le push.
    """
    import inspect

    from tortoisepy.core.operations import PushCallbacks

    signature = inspect.signature(PushCallbacks.push_transfer_progress)
    assert len(signature.parameters) == 4  # self + 3


def test_rejection_message_is_not_reported_as_success(pair, monkeypatch):
    """Un refus annoncé par le serveur ne doit pas passer pour un succès.

    `remote.push()` ne lève pas dans ce cas : le refus arrive par
    `push_update_reference`. Sans cette vérification, l'utilisateur lit
    « Pushed main to origin » alors que rien n'est arrivé.
    """
    import pygit2

    from tortoisepy.core import operations

    bare, repo = pair

    def refuse(self, refspecs, callbacks=None):
        callbacks.push_update_reference(
            "refs/heads/main", "pre-receive hook declined"
        )

    monkeypatch.setattr(pygit2.Remote, "push", refuse)

    result = operations.push_branch(repo)
    assert result.success is False
    assert "declined" in (result.git_error or "")


def test_push_follows_the_configured_upstream_not_alphabetical_order(pair, tmp_path):
    """Review Finding 1 : `remotes.names()` est alphabétique, pas l'intention.

    Un second remote nommé `aaa-upstream` trierait avant `origin` ; sans
    suivre le suivi configuré de la branche, le push partirait vers le
    mauvais dépôt — le scénario classique du fork.
    """
    bare, repo = pair

    other_bare = tmp_path / "aaa-upstream.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", str(other_bare)], capture_output=True
    )
    run_git(repo.workdir, "remote", "add", "aaa-upstream", str(other_bare))
    run_git(repo.workdir, "push", "-q", "aaa-upstream", "HEAD")
    run_git(
        repo.workdir,
        "branch",
        "--set-upstream-to=origin/main",
        "main",
    )

    from pathlib import Path
    Path(repo.workdir, "f.txt").write_text("suite\n")
    run_git(repo.workdir, "add", ".")
    run_git(repo.workdir, "commit", "-q", "-m", "à pousser vers origin")

    result = push_branch(repo)
    assert result.success is True, result.git_error
    assert "à pousser vers origin" in server_log(bare)
    assert "à pousser vers origin" not in server_log(other_bare)


def test_push_prefers_origin_when_no_upstream_is_configured(pair, tmp_path):
    """Sans suivi configuré, `origin` gagne sur l'ordre alphabétique."""
    bare, repo = pair

    other_bare = tmp_path / "aaa-upstream.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", str(other_bare)], capture_output=True
    )
    run_git(repo.workdir, "remote", "add", "aaa-upstream", str(other_bare))
    # Pas de `branch --set-upstream-to` : aucun suivi configuré.

    from pathlib import Path
    Path(repo.workdir, "f.txt").write_text("suite\n")
    run_git(repo.workdir, "add", ".")
    run_git(repo.workdir, "commit", "-q", "-m", "à pousser vers origin aussi")

    result = push_branch(repo)
    assert result.success is True, result.git_error
    assert "à pousser vers origin aussi" in server_log(bare)
    assert "à pousser vers origin aussi" not in server_log(other_bare)


def test_push_with_pushurl_only_remote_does_not_raise_attributeerror(pair):
    """Review Finding 2 : un remote sans `url` (seulement `pushurl`) ne doit
    pas faire planter `_credentials` avec un `AttributeError` brut.

    `remote.url` vaut alors `None`. Vérifié séparément (hors suite, car
    le crash n'est pas rattrapable par pytest) : passer ce remote tel quel
    à `remote.push()` fait planter le **processus entier** par segfault
    dans libgit2 1.20 — un bug de la bibliothèque, pas de tortoisePy, que
    `git` en CLI n'a pas dans cette même configuration. Comme aucun
    `try/except` Python ne protège d'un segfault, `push_branch` doit
    détecter `remote.url is None` et refuser *avant* d'appeler
    `remote.push()`, plutôt que de risquer soit l'`AttributeError` (ancien
    comportement, via `_credentials`), soit le crash.
    """
    bare, repo = pair

    config = repo.config
    config["remote.origin.pushurl"] = str(bare)
    del config["remote.origin.url"]

    from pathlib import Path
    Path(repo.workdir, "f.txt").write_text("suite\n")
    run_git(repo.workdir, "add", ".")
    run_git(repo.workdir, "commit", "-q", "-m", "via pushurl")

    result = push_branch(repo)
    assert result.success is False
    assert "AttributeError" not in (result.git_error or "")
    assert "origin" in (result.git_error or "")
