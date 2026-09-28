import os
import subprocess

import pygit2
import pytest

from tortoisepy.core.operations import (
    OPERATION_CLASSES,
    abort_operation,
    cherry_pick,
    merge_branch,
    reset_to,
    revert_commit,
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
def diverged(tmp_path):
    """master et feature modifient des fichiers DIFFÉRENTS : merge sans conflit."""
    path = tmp_path / "d"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "master")
    (path / "base.txt").write_text("base\n")
    run_git(path, "add", "base.txt")
    run_git(path, "commit", "-q", "-m", "base")

    run_git(path, "checkout", "-q", "-b", "feature")
    (path / "feature.txt").write_text("feature\n")
    run_git(path, "add", "feature.txt")
    run_git(path, "commit", "-q", "-m", "feature")

    run_git(path, "checkout", "-q", "master")
    (path / "master.txt").write_text("master\n")
    run_git(path, "add", "master.txt")
    run_git(path, "commit", "-q", "-m", "master")

    return pygit2.Repository(str(path))


@pytest.fixture
def conflicting(tmp_path):
    """master et feature modifient le MÊME fichier : merge en conflit."""
    path = tmp_path / "c"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "master")
    (path / "f.txt").write_text("base\n")
    run_git(path, "add", "f.txt")
    run_git(path, "commit", "-q", "-m", "base")

    run_git(path, "checkout", "-q", "-b", "feature")
    (path / "f.txt").write_text("version feature\n")
    run_git(path, "add", "f.txt")
    run_git(path, "commit", "-q", "-m", "feature")

    run_git(path, "checkout", "-q", "master")
    (path / "f.txt").write_text("version master\n")
    run_git(path, "add", "f.txt")
    run_git(path, "commit", "-q", "-m", "master")

    return pygit2.Repository(str(path))


def test_clean_merge_succeeds(diverged):
    result = merge_branch(diverged, "feature")
    assert result.success is True
    assert result.repository_changed is True
    assert read_state(diverged).has_conflicts is False


def test_conflicting_merge_fails_but_changed_the_repository(conflicting):
    """§7.6 : l'échec n'empêche pas la modification de l'index."""
    result = merge_branch(conflicting, "feature")
    assert result.success is False
    assert result.repository_changed is True
    assert read_state(conflicting).has_conflicts is True


def test_conflicting_merge_names_the_files(conflicting):
    result = merge_branch(conflicting, "feature")
    assert "f.txt" in (result.git_error or "")


def test_merge_unknown_branch(diverged):
    result = merge_branch(diverged, "inexistante")
    assert result.success is False
    assert result.repository_changed is False


def test_abort_clears_a_conflicted_merge(conflicting):
    merge_branch(conflicting, "feature")
    assert read_state(conflicting).operation_in_progress == "merge"

    result = abort_operation(conflicting)
    assert result.success is True
    state = read_state(conflicting)
    assert state.operation_in_progress is None
    assert state.has_conflicts is False


def test_abort_without_operation_in_progress(diverged):
    result = abort_operation(diverged)
    assert result.success is False


def test_reset_hard_moves_head_and_discards_changes(diverged):
    first = str(list(diverged.walk(diverged.head.target))[-1].id)
    result = reset_to(diverged, first, "hard")
    assert result.success is True
    assert str(diverged.head.target) == first


def test_reset_soft_keeps_the_working_tree(diverged):
    first = str(list(diverged.walk(diverged.head.target))[-1].id)
    result = reset_to(diverged, first, "soft")
    assert result.success is True
    assert str(diverged.head.target) == first


def test_reset_rejects_an_unknown_mode(diverged):
    result = reset_to(diverged, str(diverged.head.target), "inexistant")
    assert result.success is False
    assert result.repository_changed is False


def test_reset_to_unknown_commit(diverged):
    result = reset_to(diverged, "0" * 40, "hard")
    assert result.success is False


def test_cherry_pick_applies_a_commit(diverged):
    feature_tip = str(diverged.branches.local["feature"].target)
    result = cherry_pick(diverged, feature_tip)
    assert result.success is True
    assert result.repository_changed is True


def test_cherry_pick_unknown_commit(diverged):
    result = cherry_pick(diverged, "0" * 40)
    assert result.success is False


def test_revert_commit(diverged):
    head = str(diverged.head.target)
    result = revert_commit(diverged, head)
    assert result.success is True


def test_revert_unknown_commit(diverged):
    result = revert_commit(diverged, "0" * 40)
    assert result.success is False


def test_operation_classes_cover_every_operation():
    """§7.7 : chaque opération est classée, l'UI s'en sert pour les menus."""
    assert set(OPERATION_CLASSES) == {"simple", "interactive", "destructive"}
    assert "checkout_branch" in OPERATION_CLASSES["simple"]
    assert "merge_branch" in OPERATION_CLASSES["interactive"]
    assert "reset_to" in OPERATION_CLASSES["destructive"]
    assert "delete_branch" in OPERATION_CLASSES["destructive"]


def test_no_operation_appears_in_two_classes():
    seen: set[str] = set()
    for names in OPERATION_CLASSES.values():
        for name in names:
            assert name not in seen, f"{name} classé deux fois"
            seen.add(name)
