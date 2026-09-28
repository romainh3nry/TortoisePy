import os
import subprocess

import pygit2
import pytest

from tortoisepy.core.operations import commit_selection


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
    path = tmp_path / "commit"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "a.txt").write_text("A\n")
    (path / "b.txt").write_text("B\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "base")

    (path / "a.txt").write_text("A modifié\n")
    (path / "b.txt").write_text("B modifié\n")
    return pygit2.Repository(str(path))


def commit_count(repo) -> int:
    return len(list(repo.walk(repo.head.target)))


def test_commits_the_selected_files(repo):
    before = commit_count(repo)
    result = commit_selection(repo, ("a.txt",), "mon message")
    assert result.success is True, result.git_error
    assert commit_count(repo) == before + 1


def test_commit_message_is_recorded(repo):
    commit_selection(repo, ("a.txt",), "un message précis")
    assert repo.get(repo.head.target).message.strip() == "un message précis"


def test_unselected_files_stay_out(repo):
    """§5 : décocher un fichier l'exclut du commit."""
    commit_selection(repo, ("a.txt",), "seulement a")
    commit = repo.get(repo.head.target)
    diff = repo.diff(commit.parents[0], commit)
    assert {p.delta.new_file.path for p in diff} == {"a.txt"}


def test_the_user_index_is_left_alone(repo):
    """§5 : l'index préparé au terminal n'est pas modifié."""
    workdir = repo.workdir
    run_git(workdir, "add", "b.txt")  # l'utilisateur a indexé b.txt

    commit_selection(repo, ("a.txt",), "seulement a")

    status = subprocess.run(
        ["git", "status", "--short"], cwd=workdir,
        capture_output=True, text=True,
    ).stdout
    assert "b.txt" in status, "b.txt doit rester visible dans le statut"


def test_empty_message_is_refused(repo):
    """§4.3 : un commit sans message est une dette immédiate."""
    before = commit_count(repo)
    result = commit_selection(repo, ("a.txt",), "   ")
    assert result.success is False
    assert commit_count(repo) == before


def test_empty_selection_is_refused(repo):
    before = commit_count(repo)
    result = commit_selection(repo, (), "un message")
    assert result.success is False
    assert commit_count(repo) == before


def test_untracked_file_can_be_committed(repo):
    from pathlib import Path
    Path(repo.workdir, "neuf.txt").write_text("nouveau\n")

    result = commit_selection(repo, ("neuf.txt",), "ajout")
    assert result.success is True, result.git_error

    commit = repo.get(repo.head.target)
    diff = repo.diff(commit.parents[0], commit)
    assert "neuf.txt" in {p.delta.new_file.path for p in diff}


def test_deleted_file_is_removed_by_the_commit(repo):
    from pathlib import Path
    Path(repo.workdir, "b.txt").unlink()

    result = commit_selection(repo, ("b.txt",), "suppression")
    assert result.success is True, result.git_error

    tree = repo.get(repo.head.target).tree
    assert "b.txt" not in [entry.name for entry in tree]


def test_first_commit_of_an_empty_repository(tmp_path):
    """Review Focus 3 : `HEAD` n'existe pas encore."""
    path = tmp_path / "vide"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "premier.txt").write_text("contenu\n")

    repository = pygit2.Repository(str(path))
    result = commit_selection(repository, ("premier.txt",), "premier commit")

    assert result.success is True, result.git_error
    assert repository.head.target is not None


def test_missing_file_fails_cleanly(repo):
    """Review Focus 4 : le fichier a disparu entre l'affichage et le commit."""
    result = commit_selection(repo, ("jamais-existe.txt",), "message")
    assert result.success is False
    assert "jamais-existe.txt" in (result.git_error or "")


def test_commit_marks_the_repository_changed(repo):
    result = commit_selection(repo, ("a.txt",), "message")
    assert result.repository_changed is True


def test_refusal_leaves_the_repository_untouched(repo):
    result = commit_selection(repo, (), "message")
    assert result.repository_changed is False


def test_commit_never_raises(repo):
    """§7.6 : aucune exception ne remonte."""
    for paths, message in [
        ((), ""),
        (("a.txt",), ""),
        (("inexistant",), "m"),
        ((None,), "m"),
    ]:
        result = commit_selection(repo, paths, message)
        assert result.success is False


def _tree_mode(repo, name: str) -> int:
    return repo.get(repo.head.target).tree[name].filemode


def test_executable_file_keeps_its_mode(repo):
    """Le bit exécutable ne doit pas être écrasé par FileMode.BLOB fixe."""
    from pathlib import Path

    script = Path(repo.workdir, "script.sh")
    script.write_text("#!/bin/sh\necho hi\n")
    script.chmod(0o755)

    result = commit_selection(repo, ("script.sh",), "ajout script")
    assert result.success is True, result.git_error
    assert _tree_mode(repo, "script.sh") == 0o100755


def test_symlink_keeps_link_mode_and_target_content(repo):
    """Un symlink doit être committé en mode LINK, pas en blob régulier."""
    from pathlib import Path

    link = Path(repo.workdir, "lien")
    link.symlink_to("a.txt")

    result = commit_selection(repo, ("lien",), "ajout lien")
    assert result.success is True, result.git_error

    tree = repo.get(repo.head.target).tree
    assert tree["lien"].filemode == 0o120000
    blob = repo.get(tree["lien"].id)
    assert blob.data == b"a.txt"


def test_broken_symlink_is_committed_not_treated_as_deletion(repo):
    """lexists (pas exists) : un lien cassé reste un lien, pas une suppression."""
    from pathlib import Path

    link = Path(repo.workdir, "lien-casse")
    link.symlink_to("cible-inexistante.txt")

    result = commit_selection(repo, ("lien-casse",), "lien casse")
    assert result.success is True, result.git_error

    tree = repo.get(repo.head.target).tree
    assert tree["lien-casse"].filemode == 0o120000
