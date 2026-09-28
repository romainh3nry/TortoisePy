import os
import subprocess

import pygit2
import pytest

from tortoisepy.core.operations import (
    checkout_branch,
    checkout_commit,
    create_branch,
    create_tag,
    delete_branch,
    delete_tag,
    rename_branch,
)
from tortoisepy.core.state import read_state


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
def repo(tmp_path):
    path = tmp_path / "ops"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "master")
    (path / "f.txt").write_text("base\n")
    run_git(path, "add", "f.txt")
    run_git(path, "commit", "-q", "-m", "base")
    (path / "f.txt").write_text("deux\n")
    run_git(path, "add", "f.txt")
    run_git(path, "commit", "-q", "-m", "deux")
    return pygit2.Repository(str(path))


def head_oid(repo) -> str:
    return str(repo.head.target)


def test_create_branch(repo):
    result = create_branch(repo, "feature", head_oid(repo))
    assert result.success is True
    assert result.repository_changed is True
    assert "refs/heads/feature" in repo.references


def test_create_branch_refuses_an_existing_name(repo):
    create_branch(repo, "feature", head_oid(repo))
    result = create_branch(repo, "feature", head_oid(repo))
    assert result.success is False
    assert result.git_error is not None


def test_create_branch_refuses_an_unknown_commit(repo):
    result = create_branch(repo, "x", "0" * 40)
    assert result.success is False


def test_delete_branch(repo):
    create_branch(repo, "temp", head_oid(repo))
    result = delete_branch(repo, "temp")
    assert result.success is True
    assert "refs/heads/temp" not in repo.references


def test_delete_branch_refuses_the_current_branch(repo):
    """Supprimer la branche courante laisserait le dépôt sans HEAD valide."""
    result = delete_branch(repo, "master")
    assert result.success is False
    assert result.repository_changed is False
    assert "refs/heads/master" in repo.references


def test_delete_unknown_branch(repo):
    result = delete_branch(repo, "inexistante")
    assert result.success is False


def test_rename_branch(repo):
    create_branch(repo, "ancien", head_oid(repo))
    result = rename_branch(repo, "ancien", "nouveau")
    assert result.success is True
    assert "refs/heads/nouveau" in repo.references
    assert "refs/heads/ancien" not in repo.references


def test_rename_branch_refuses_an_existing_target(repo):
    create_branch(repo, "a", head_oid(repo))
    create_branch(repo, "b", head_oid(repo))
    result = rename_branch(repo, "a", "b")
    assert result.success is False


def test_create_lightweight_tag(repo):
    result = create_tag(repo, "v1.0", head_oid(repo))
    assert result.success is True
    assert "refs/tags/v1.0" in repo.references


def test_create_annotated_tag(repo):
    result = create_tag(repo, "v2.0", head_oid(repo), message="version 2")
    assert result.success is True
    tag = repo.references["refs/tags/v2.0"]
    assert repo.get(tag.target).type_str == "tag"


def test_delete_tag(repo):
    create_tag(repo, "v1.0", head_oid(repo))
    result = delete_tag(repo, "v1.0")
    assert result.success is True
    assert "refs/tags/v1.0" not in repo.references


def test_checkout_branch(repo):
    create_branch(repo, "feature", head_oid(repo))
    result = checkout_branch(repo, "feature")
    assert result.success is True
    assert read_state(repo).head_branch == "feature"


def test_checkout_unknown_branch(repo):
    result = checkout_branch(repo, "inexistante")
    assert result.success is False


def test_checkout_commit_detaches_head(repo):
    first = str(list(repo.walk(repo.head.target))[-1].id)
    result = checkout_commit(repo, first)
    assert result.success is True
    state = read_state(repo)
    assert state.detached is True
    assert state.head_oid == first


def test_every_operation_returns_a_result_never_raises(repo):
    """§7.6 : aucune opération ne laisse remonter d'exception."""
    calls = [
        lambda: create_branch(repo, "", "0" * 40),
        lambda: delete_branch(repo, ""),
        lambda: rename_branch(repo, "", ""),
        lambda: create_tag(repo, "", "0" * 40),
        lambda: delete_tag(repo, ""),
        lambda: checkout_branch(repo, ""),
        lambda: checkout_commit(repo, "pas-un-oid"),
    ]
    for call in calls:
        result = call()  # ne doit jamais lever
        assert result.success is False
