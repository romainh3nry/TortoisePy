import os
import subprocess

import pygit2
import pytest

from tortoisepy.core.changes import (
    ChangeKind,
    diff_for,
    list_changes,
)


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
    """Un dépôt portant les quatre sortes de changements."""
    path = tmp_path / "changes"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "garde.txt").write_text("ligne 1\nligne 2\nligne 3\n")
    (path / "supprime.txt").write_text("à supprimer\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "base")

    (path / "garde.txt").write_text("ligne 1\nLIGNE 2 MODIFIÉE\nligne 3\n")
    (path / "nouveau.txt").write_text("tout neuf\n")
    (path / "supprime.txt").unlink()
    return pygit2.Repository(str(path))


def test_lists_every_changed_file(repo):
    paths = {c.path for c in list_changes(repo)}
    assert paths == {"garde.txt", "nouveau.txt", "supprime.txt"}


def test_classifies_a_modified_file(repo):
    change = next(c for c in list_changes(repo) if c.path == "garde.txt")
    assert change.kind is ChangeKind.MODIFIED


def test_classifies_an_untracked_file(repo):
    change = next(c for c in list_changes(repo) if c.path == "nouveau.txt")
    assert change.kind is ChangeKind.UNTRACKED


def test_classifies_a_deleted_file(repo):
    change = next(c for c in list_changes(repo) if c.path == "supprime.txt")
    assert change.kind is ChangeKind.DELETED


def test_untracked_files_are_not_preselected(repo):
    """§4.1 : cocher un fichier non suivi par défaut ajouterait des `.env`."""
    change = next(c for c in list_changes(repo) if c.path == "nouveau.txt")
    assert change.selected_by_default is False


def test_tracked_changes_are_preselected(repo):
    change = next(c for c in list_changes(repo) if c.path == "garde.txt")
    assert change.selected_by_default is True


def test_changes_are_sorted_by_path(repo):
    paths = [c.path for c in list_changes(repo)]
    assert paths == sorted(paths)


def test_clean_repository_has_no_changes(tmp_path):
    path = tmp_path / "propre"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "f.txt").write_text("a\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "base")
    assert list_changes(pygit2.Repository(str(path))) == ()


def test_diff_shows_added_and_removed_lines(repo):
    diff = diff_for(repo, "garde.txt")
    origins = {line.origin for hunk in diff.hunks for line in hunk.lines}
    assert "+" in origins
    assert "-" in origins


def test_diff_counts_lines(repo):
    diff = diff_for(repo, "garde.txt")
    assert diff.added == 1
    assert diff.removed == 1


def test_diff_keeps_context_lines(repo):
    """Sans contexte, on ne sait pas où le changement se situe."""
    diff = diff_for(repo, "garde.txt")
    origins = [line.origin for hunk in diff.hunks for line in hunk.lines]
    assert " " in origins


def test_hunk_carries_its_header(repo):
    diff = diff_for(repo, "garde.txt")
    assert diff.hunks
    assert diff.hunks[0].header.startswith("@@")


def test_untracked_file_shows_as_fully_added(repo):
    """§4.2 : un fichier non suivi n'a pas de version précédente."""
    diff = diff_for(repo, "nouveau.txt")
    assert diff.added >= 1
    assert diff.removed == 0


def test_binary_file_is_flagged(tmp_path):
    """Review Focus 1 : un diff d'octets bruts serait illisible."""
    path = tmp_path / "binaire"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "image.dat").write_bytes(bytes(range(256)))
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "base")
    (path / "image.dat").write_bytes(bytes(range(255, -1, -1)))

    repository = pygit2.Repository(str(path))
    change = next(c for c in list_changes(repository) if c.path == "image.dat")
    assert change.is_binary is True

    diff = diff_for(repository, "image.dat")
    assert diff.is_binary is True
    assert diff.hunks == ()


def test_conflicted_file_is_flagged(tmp_path):
    """Review Focus 2 : commiter un conflit produirait des marqueurs."""
    path = tmp_path / "conflit"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "f.txt").write_text("base\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "base")

    run_git(path, "checkout", "-q", "-b", "autre")
    (path / "f.txt").write_text("leur version\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "leur")

    run_git(path, "checkout", "-q", "main")
    (path / "f.txt").write_text("notre version\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "notre")
    run_git(path, "merge", "autre")

    repository = pygit2.Repository(str(path))
    change = next(c for c in list_changes(repository) if c.path == "f.txt")
    assert change.kind is ChangeKind.CONFLICTED
    assert change.selectable is False


def test_unknown_path_gives_an_empty_diff(repo):
    diff = diff_for(repo, "inexistant.txt")
    assert diff.hunks == ()


def test_untracked_binary_file_is_flagged(tmp_path):
    """Régression : un fichier binaire non suivi doit être marqué comme binaire."""
    path = tmp_path / "untracked_binary"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "base.txt").write_text("base\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "base")

    # Add untracked binary file
    (path / "image.dat").write_bytes(bytes(range(256)))

    repository = pygit2.Repository(str(path))
    change = next(c for c in list_changes(repository) if c.path == "image.dat")
    assert change.kind is ChangeKind.UNTRACKED
    assert change.is_binary is True

    diff = diff_for(repository, "image.dat")
    assert diff.is_binary is True
    assert diff.hunks == ()


def test_reading_changes_writes_nothing(repo):
    """§7.0 : lire l'état ne modifie pas le dépôt."""
    import hashlib
    from pathlib import Path

    git_dir = Path(repo.path)

    def fingerprint():
        digest = hashlib.sha256()
        for item in sorted(git_dir.rglob("*")):
            if item.is_file():
                digest.update(f"{item}:{item.stat().st_mtime_ns}".encode())
        return digest.hexdigest()

    before = fingerprint()
    list_changes(repo)
    for change in list_changes(repo):
        diff_for(repo, change.path)
    assert fingerprint() == before
