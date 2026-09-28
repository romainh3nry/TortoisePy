import os
import subprocess

import pygit2
import pytest

from tortoisepy.ui.commit_detail_window import CommitDetailWindow


def run_git(path, *args):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Alice", "GIT_AUTHOR_EMAIL": "alice@example.com",
        "GIT_COMMITTER_NAME": "Alice", "GIT_COMMITTER_EMAIL": "alice@example.com",
    }
    return subprocess.run(
        ["git", *args], cwd=path, env=env, capture_output=True, text=True
    )


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "detail"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "a.txt").write_text("un\ndeux\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "racine")

    (path / "a.txt").write_text("un\nDEUX CHANGE\n")
    (path / "b.txt").write_text("neuf\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "sujet du commit")
    return pygit2.Repository(str(path))


@pytest.fixture
def window(qtbot, repo):
    w = CommitDetailWindow(repo, str(repo.head.target))
    qtbot.addWidget(w)
    return w


def test_lists_the_files_of_the_commit(window):
    assert window.file_count() == 2


def test_shows_the_commit_message(window):
    assert "sujet du commit" in window.header_text()


def test_shows_the_author(window):
    assert "Alice" in window.header_text()


def test_shows_the_short_oid(window, repo):
    assert str(repo.head.target)[:8] in window.header_text()


def test_selects_the_first_file_on_opening(window):
    """Ouvrir sur un volet de diff vide donne l'impression d'un bug."""
    assert window.diff_view.text()


def test_selecting_a_file_shows_its_diff(window):
    window.select_file("a.txt")
    assert "DEUX CHANGE" in window.diff_view.text()


def test_has_no_checkboxes(window):
    """Ce commit est déjà fait : rien à stager."""
    from PySide6.QtCore import Qt

    item = window.item_for("a.txt")
    assert not (item.flags() & Qt.ItemFlag.ItemIsUserCheckable)


def test_root_commit_opens(qtbot, repo):
    """Review Focus 6 : un commit racine n'a pas de parent."""
    root = [c for c in repo.walk(repo.head.target) if not c.parents][0]
    w = CommitDetailWindow(repo, str(root.id))
    qtbot.addWidget(w)
    assert w.file_count() == 1


def test_unknown_oid_opens_without_crashing(qtbot, repo):
    w = CommitDetailWindow(repo, "0" * 40)
    qtbot.addWidget(w)
    assert w.file_count() == 0


def test_empty_commit_shows_an_explanation_instead_of_a_blank_pane(qtbot, repo):
    """Un volet de diff muet donnerait l'impression d'un bug (cf. brief) —

    y compris quand le commit est légitimement vide (`--allow-empty`,
    certains merges), pas seulement pour un OID inconnu."""
    run_git(repo.workdir, "commit", "-q", "--allow-empty", "-m", "vide")
    oid = str(repo.head.target)

    w = CommitDetailWindow(repo, oid)
    qtbot.addWidget(w)

    assert w.file_count() == 0
    assert w.diff_view.text()


def test_opening_writes_nothing(window, repo):
    """§7.0 : consulter un commit ne modifie pas le dépôt."""
    before = subprocess.run(
        ["git", "status", "--short"], cwd=repo.workdir,
        capture_output=True, text=True,
    ).stdout
    window.select_file("a.txt")
    window.select_file("b.txt")
    after = subprocess.run(
        ["git", "status", "--short"], cwd=repo.workdir,
        capture_output=True, text=True,
    ).stdout
    assert before == after
