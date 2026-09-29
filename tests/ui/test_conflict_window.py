import os
import subprocess

import pygit2
import pytest

from tortoisepy.ui.conflict_window import ConflictWindow


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
def conflicted(tmp_path):
    bare = tmp_path / "s.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], capture_output=True)
    work = tmp_path / "w"
    subprocess.run(["git", "clone", "-q", str(bare), str(work)], capture_output=True)
    (work / "f.txt").write_text("ligne1\nligne2\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "base")
    run_git(work, "push", "-q", "origin", "HEAD")

    other = tmp_path / "o"
    subprocess.run(["git", "clone", "-q", str(bare), str(other)], capture_output=True)
    (other / "f.txt").write_text("ligne1\nDISTANT\n")
    run_git(other, "add", ".")
    run_git(other, "commit", "-q", "-m", "distant")
    run_git(other, "push", "-q")

    (work / "f.txt").write_text("ligne1\nLOCAL\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "local")
    run_git(work, "fetch", "-q")

    repo = pygit2.Repository(str(work))
    repo.merge(repo.branches[repo.head.shorthand].upstream.target)
    return repo


@pytest.fixture
def window(qtbot, conflicted):
    w = ConflictWindow(conflicted)
    qtbot.addWidget(w)
    w.show()
    return w


def test_lists_the_conflicts(window):
    assert window.file_count() == 1


def test_resolve_is_disabled_while_a_conflict_remains(window):
    assert window.resolve_button.isEnabled() is False


def test_keeping_mine_resolves_the_file(window, conflicted):
    window.select_file("f.txt")
    window.keep_mine()
    assert open(os.path.join(conflicted.workdir, "f.txt")).read() == (
        "ligne1\nLOCAL\n"
    )


def test_taking_theirs_resolves_the_file(window, conflicted):
    window.select_file("f.txt")
    window.take_theirs()
    assert open(os.path.join(conflicted.workdir, "f.txt")).read() == (
        "ligne1\nDISTANT\n"
    )


def test_resolve_becomes_available_once_everything_is_settled(window):
    window.select_file("f.txt")
    window.take_theirs()
    assert window.resolve_button.isEnabled() is True


def test_resolving_creates_the_merge_commit(window, conflicted):
    window.select_file("f.txt")
    window.take_theirs()
    window.resolve()

    fresh = pygit2.Repository(conflicted.path)
    assert len(fresh.get(fresh.head.target).parents) == 2
    assert fresh.state() == pygit2.enums.RepositoryState.NONE


def test_abort_restores_the_previous_state(window, conflicted):
    """Review Focus 5 : on ne doit jamais rester coincé."""
    before = str(conflicted.head.target)
    window.abort()

    fresh = pygit2.Repository(conflicted.path)
    assert fresh.index.conflicts is None
    assert str(fresh.head.target) == before
    assert fresh.state() == pygit2.enums.RepositoryState.NONE
    assert open(os.path.join(conflicted.workdir, "f.txt")).read() == (
        "ligne1\nLOCAL\n"
    )


def test_window_closes_after_resolving(window):
    window.select_file("f.txt")
    window.take_theirs()
    window.resolve()
    assert window.isHidden() is True


def test_window_closes_after_aborting(window):
    window.abort()
    assert window.isHidden() is True


def test_selecting_a_file_shows_both_versions(window):
    window.select_file("f.txt")
    text = window.diff_view.text()
    assert "LOCAL" in text
    assert "DISTANT" in text


def test_the_two_sides_are_coloured_differently(window):
    """Voir sa version en vert et la distante en rouge aide à choisir."""
    window.select_file("f.txt")
    lines = window.diff_view.text().splitlines()
    notre = next(l for l in lines if "LOCAL" in l and "<<<" not in l)
    leur = next(l for l in lines if "DISTANT" in l and ">>>" not in l)
    assert notre.startswith("+")
    assert leur.startswith("-")
