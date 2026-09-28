import os
import subprocess

import pygit2
import pytest

from tortoisepy.core.changes import ChangeKind, changes_in_commit, diff_in_commit


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
    path = tmp_path / "histoire"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "premier.txt").write_text("un\ndeux\ntrois\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "racine")

    (path / "premier.txt").write_text("un\nDEUX MODIFIE\ntrois\n")
    (path / "ajoute.txt").write_text("nouveau\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "deuxieme")
    return pygit2.Repository(str(path))


def test_lists_files_touched_by_the_commit(repo):
    head = str(repo.head.target)
    paths = {c.path for c in changes_in_commit(repo, head)}
    assert paths == {"premier.txt", "ajoute.txt"}


def test_marks_a_modified_file(repo):
    head = str(repo.head.target)
    change = next(
        c for c in changes_in_commit(repo, head) if c.path == "premier.txt"
    )
    assert change.kind is ChangeKind.MODIFIED


def test_marks_an_added_file(repo):
    head = str(repo.head.target)
    change = next(
        c for c in changes_in_commit(repo, head) if c.path == "ajoute.txt"
    )
    assert change.kind is ChangeKind.ADDED


def test_shows_the_modified_lines(repo):
    head = str(repo.head.target)
    diff = diff_in_commit(repo, head, "premier.txt")
    assert diff.added == 1
    assert diff.removed == 1
    contents = [l.content for h in diff.hunks for l in h.lines]
    assert any("DEUX MODIFIE" in c for c in contents)


def test_unchanged_file_is_absent(repo):
    """Le commit ne touche pas à ce qu'il n'a pas modifié."""
    head = str(repo.head.target)
    root = repo.get(repo.head.target).parents[0]
    assert "premier.txt" in {c.path for c in changes_in_commit(repo, str(head))}
    # Le commit racine, lui, ne contient pas `ajoute.txt`.
    assert "ajoute.txt" not in {
        c.path for c in changes_in_commit(repo, str(root.id))
    }


def test_root_commit_shows_its_files_as_added(repo):
    """Review Focus 6 : sans `swap=True`, ils apparaîtraient en suppressions."""
    root = [c for c in repo.walk(repo.head.target) if not c.parents][0]
    changes = changes_in_commit(repo, str(root.id))

    assert {c.path for c in changes} == {"premier.txt"}
    assert changes[0].kind is ChangeKind.ADDED

    diff = diff_in_commit(repo, str(root.id), "premier.txt")
    assert diff.added == 3
    assert diff.removed == 0


def test_merge_commit_diffs_against_its_first_parent(tmp_path):
    """Review Focus 6 : un merge a deux parents, donc pas d'« avant » évident.

    On diffe contre le premier, comme `git show` : c'est ce qui montre ce
    que le merge a apporté à la branche d'accueil.
    """
    path = tmp_path / "merge"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "base.txt").write_text("base\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "base")

    run_git(path, "checkout", "-q", "-b", "cote")
    (path / "depuis-cote.txt").write_text("apporte par la branche\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "cote")

    run_git(path, "checkout", "-q", "main")
    (path / "depuis-main.txt").write_text("apporte par main\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "main avance")
    run_git(path, "merge", "-q", "--no-ff", "-m", "fusion", "cote")

    repository = pygit2.Repository(str(path))
    merge = repository.get(repository.head.target)
    assert len(merge.parents) == 2, "la fixture doit produire un vrai merge"

    paths = {c.path for c in changes_in_commit(repository, str(merge.id))}
    assert "depuis-cote.txt" in paths
    assert "depuis-main.txt" not in paths


def test_unknown_oid_gives_no_changes(repo):
    assert changes_in_commit(repo, "0" * 40) == ()


def test_unknown_oid_gives_an_empty_diff(repo):
    assert diff_in_commit(repo, "0" * 40, "premier.txt").hunks == ()


def test_unknown_path_gives_an_empty_diff(repo):
    head = str(repo.head.target)
    assert diff_in_commit(repo, head, "jamais.txt").hunks == ()


def test_binary_file_is_flagged(tmp_path):
    """Review Focus 1, côté commit : afficher des octets serait illisible."""
    path = tmp_path / "binaire-commit"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "image.dat").write_bytes(bytes(range(256)))
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "ajout binaire")

    repository = pygit2.Repository(str(path))
    head = str(repository.head.target)
    assert diff_in_commit(repository, head, "image.dat").is_binary is True


def test_rename_is_one_entry_not_a_delete_plus_add(tmp_path):
    """Un `git mv` doit ressortir en une seule ligne, comme dans TortoiseGit.

    Sans `find_similar()`, pygit2 n'apparie jamais un renommage : le commit
    ressortait en deux entrées sans rapport (`D ancien` + `A nouveau`), là où
    git montre un seul `R ancien -> nouveau`. Vérifié sur un dépôt réel.
    """
    path = tmp_path / "renomme"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "ancien.txt").write_text("l1\nl2\nl3\nl4\nl5\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "base")

    run_git(path, "mv", "ancien.txt", "nouveau.txt")
    run_git(path, "commit", "-q", "-m", "renomme")

    repository = pygit2.Repository(str(path))
    changes = changes_in_commit(repository, str(repository.head.target))

    assert len(changes) == 1, (
        f"un renommage doit donner une seule entrée, obtenu : "
        f"{[(c.path, c.kind) for c in changes]}"
    )
    # Le chemin affiché est le nouveau nom : c'est celui que le fichier porte
    # désormais dans l'arbre de travail.
    assert changes[0].path == "nouveau.txt"
    assert changes[0].kind is ChangeKind.MODIFIED


def test_reading_a_commit_writes_nothing(repo):
    """§7.0 : inspecter un commit ne modifie pas le dépôt."""
    import hashlib
    from pathlib import Path

    git_dir = Path(repo.path)

    def fingerprint():
        digest = hashlib.sha256()
        for item in sorted(git_dir.rglob("*")):
            if item.is_file():
                digest.update(f"{item}:{item.stat().st_mtime_ns}".encode())
        return digest.hexdigest()

    head = str(repo.head.target)
    before = fingerprint()
    for change in changes_in_commit(repo, head):
        diff_in_commit(repo, head, change.path)
    assert fingerprint() == before
