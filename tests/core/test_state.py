import os
import subprocess

import pygit2
import pytest

from tortoisepy.core.state import RepositoryState, read_state


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
def worktree(tmp_path):
    """Dépôt avec arbre de travail, un commit initial."""
    path = tmp_path / "wt"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "master")
    (path / "f.txt").write_text("base\n")
    run_git(path, "add", "f.txt")
    run_git(path, "commit", "-q", "-m", "base")
    return path


def test_clean_repository(worktree):
    state = read_state(pygit2.Repository(str(worktree)))
    assert state.head_branch == "master"
    assert state.detached is False
    assert state.has_unstaged_changes is False
    assert state.has_staged_changes is False
    assert state.has_conflicts is False
    assert state.operation_in_progress is None
    assert state.head_oid is not None


def test_is_frozen(worktree):
    state = read_state(pygit2.Repository(str(worktree)))
    with pytest.raises(AttributeError):
        state.detached = True


def test_unstaged_change_is_detected(worktree):
    (worktree / "f.txt").write_text("modifié\n")
    state = read_state(pygit2.Repository(str(worktree)))
    assert state.has_unstaged_changes is True
    assert state.has_staged_changes is False


def test_staged_change_is_detected(worktree):
    (worktree / "f.txt").write_text("modifié\n")
    run_git(worktree, "add", "f.txt")
    state = read_state(pygit2.Repository(str(worktree)))
    assert state.has_staged_changes is True


def test_untracked_file_counts_as_unstaged(worktree):
    (worktree / "nouveau.txt").write_text("x\n")
    state = read_state(pygit2.Repository(str(worktree)))
    assert state.has_unstaged_changes is True


def test_detached_head(worktree):
    oid = run_git(worktree, "rev-parse", "HEAD").stdout.strip()
    run_git(worktree, "checkout", "-q", "--detach", oid)
    state = read_state(pygit2.Repository(str(worktree)))
    assert state.detached is True
    assert state.head_branch is None
    assert state.head_oid == oid


def test_empty_repository_has_no_head(tmp_path):
    """Dépôt sans aucun commit : ni HEAD, ni branche."""
    path = tmp_path / "vide"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "master")
    state = read_state(pygit2.Repository(str(path)))
    assert state.head_oid is None
    assert state.head_branch is None
    assert state.detached is False


def test_merge_conflict_is_detected(worktree):
    """Vérifié : state() vaut MERGE et index.conflicts n'est pas None."""
    run_git(worktree, "checkout", "-q", "-b", "other")
    (worktree / "f.txt").write_text("leur version\n")
    run_git(worktree, "add", "f.txt")
    run_git(worktree, "commit", "-q", "-m", "other")

    run_git(worktree, "checkout", "-q", "master")
    (worktree / "f.txt").write_text("notre version\n")
    run_git(worktree, "add", "f.txt")
    run_git(worktree, "commit", "-q", "-m", "master")

    run_git(worktree, "merge", "other")

    state = read_state(pygit2.Repository(str(worktree)))
    assert state.has_conflicts is True
    assert state.operation_in_progress == "merge"


def test_conflicted_files_are_listed(worktree):
    run_git(worktree, "checkout", "-q", "-b", "other")
    (worktree / "f.txt").write_text("leur\n")
    run_git(worktree, "add", "f.txt")
    run_git(worktree, "commit", "-q", "-m", "other")
    run_git(worktree, "checkout", "-q", "master")
    (worktree / "f.txt").write_text("notre\n")
    run_git(worktree, "add", "f.txt")
    run_git(worktree, "commit", "-q", "-m", "master")
    run_git(worktree, "merge", "other")

    state = read_state(pygit2.Repository(str(worktree)))
    assert "f.txt" in state.conflicted_paths


def test_no_conflicted_paths_when_clean(worktree):
    state = read_state(pygit2.Repository(str(worktree)))
    assert state.conflicted_paths == ()


def test_reading_state_does_not_modify_the_repository(worktree):
    """Le module est en lecture seule : deux lectures donnent le même état."""
    repo = pygit2.Repository(str(worktree))
    first = read_state(repo)
    second = read_state(repo)
    assert first == second
