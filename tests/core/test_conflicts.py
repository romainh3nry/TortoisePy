import os
import stat
import subprocess

import pygit2
import pytest

from tortoisepy.core.conflicts import (
    Side,
    conclude_merge,
    list_conflicts,
    resolve_with,
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
def conflicted(tmp_path):
    """Un dépôt en pleine fusion conflictuelle sur `f.txt`."""
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
    assert repo.index.conflicts is not None
    return repo


def test_lists_the_conflicted_file(conflicted):
    files = list_conflicts(conflicted)
    assert [f.path for f in files] == ["f.txt"]


def test_reports_both_sides(conflicted):
    conflict = list_conflicts(conflicted)[0]
    assert conflict.has_ours is True
    assert conflict.has_theirs is True


def test_keep_mine(conflicted):
    resolve_with(conflicted, "f.txt", Side.OURS)
    workdir = conflicted.workdir
    assert open(os.path.join(workdir, "f.txt")).read() == "ligne1\nLOCAL\n"
    assert list_conflicts(pygit2.Repository(conflicted.path)) == ()


def test_take_theirs(conflicted):
    resolve_with(conflicted, "f.txt", Side.THEIRS)
    workdir = conflicted.workdir
    assert open(os.path.join(workdir, "f.txt")).read() == "ligne1\nDISTANT\n"
    assert list_conflicts(pygit2.Repository(conflicted.path)) == ()


def test_concluding_creates_a_merge_commit(conflicted):
    resolve_with(conflicted, "f.txt", Side.THEIRS)
    result = conclude_merge(conflicted)
    assert result.success is True, result.git_error

    fresh = pygit2.Repository(conflicted.path)
    assert len(fresh.get(fresh.head.target).parents) == 2
    assert fresh.state() == pygit2.enums.RepositoryState.NONE


def test_cannot_conclude_while_a_conflict_remains(conflicted):
    """Commiter un conflit produirait des marqueurs `<<<<<<<`."""
    result = conclude_merge(conflicted)
    assert result.success is False
    assert "conflict" in (result.git_error or "").lower()

    fresh = pygit2.Repository(conflicted.path)
    assert fresh.index.conflicts is not None


def test_resolving_an_unknown_path_fails_cleanly(conflicted):
    result = resolve_with(conflicted, "jamais.txt", Side.OURS)
    assert result.success is False


def test_binary_conflict_can_be_resolved(tmp_path):
    """Review Focus 3 : aucun choix ligne à ligne n'a de sens ici."""
    bare = tmp_path / "b.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], capture_output=True)
    work = tmp_path / "wb"
    subprocess.run(["git", "clone", "-q", str(bare), str(work)], capture_output=True)
    (work / "img.dat").write_bytes(bytes(range(64)))
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "base")
    run_git(work, "push", "-q", "origin", "HEAD")

    other = tmp_path / "ob"
    subprocess.run(["git", "clone", "-q", str(bare), str(other)], capture_output=True)
    (other / "img.dat").write_bytes(bytes(range(63, -1, -1)))
    run_git(other, "add", ".")
    run_git(other, "commit", "-q", "-m", "distant")
    run_git(other, "push", "-q")

    (work / "img.dat").write_bytes(bytes([7] * 64))
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "local")
    run_git(work, "fetch", "-q")

    repo = pygit2.Repository(str(work))
    repo.merge(repo.branches[repo.head.shorthand].upstream.target)
    assert repo.index.conflicts is not None

    conflict = list_conflicts(repo)[0]
    assert conflict.is_binary is True

    resolve_with(repo, "img.dat", Side.THEIRS)
    assert list_conflicts(pygit2.Repository(str(work))) == ()


def test_delete_modify_conflict_does_not_crash(tmp_path):
    """Review Focus 4 : un côté supprime, l'autre modifie.

    Une des trois versions de `index.conflicts` vaut alors `None`.
    """
    bare = tmp_path / "d.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], capture_output=True)
    work = tmp_path / "wd"
    subprocess.run(["git", "clone", "-q", str(bare), str(work)], capture_output=True)
    (work / "f.txt").write_text("contenu\n")
    (work / "garde.txt").write_text("garde\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "base")
    run_git(work, "push", "-q", "origin", "HEAD")

    other = tmp_path / "od"
    subprocess.run(["git", "clone", "-q", str(bare), str(other)], capture_output=True)
    run_git(other, "rm", "-q", "f.txt")
    run_git(other, "commit", "-q", "-m", "supprime")
    run_git(other, "push", "-q")

    (work / "f.txt").write_text("modifie localement\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "modifie")
    run_git(work, "fetch", "-q")

    repo = pygit2.Repository(str(work))
    repo.merge(repo.branches[repo.head.shorthand].upstream.target)

    files = list_conflicts(repo)
    assert files, "le conflit suppression/modification doit être listé"
    conflict = files[0]
    assert conflict.path == "f.txt"
    # Un des deux côtés n'existe pas — l'interface doit pouvoir le dire.
    assert conflict.has_ours != conflict.has_theirs


def test_no_conflicts_gives_an_empty_tuple(tmp_path):
    path = tmp_path / "propre"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "f.txt").write_text("a\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "base")
    assert list_conflicts(pygit2.Repository(str(path))) == ()


def test_conflicted_file_is_frozen(conflicted):
    import dataclasses

    conflict = list_conflicts(conflicted)[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        conflict.path = "autre.txt"


def _symlink_conflict(tmp_path, name):
    """Un lien `lien` en conflit : base -> a.txt, distant -> b.txt, local -> c.txt.

    Sert aux deux tests de résolution de lien (Fix round 1, Finding 1) :
    résoudre ne doit ni laisser le lien intact ni écraser le contenu du
    fichier vers lequel il pointait avant la résolution.
    """
    bare = tmp_path / f"{name}.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], capture_output=True)
    work = tmp_path / f"w{name}"
    subprocess.run(["git", "clone", "-q", str(bare), str(work)], capture_output=True)
    (work / "a.txt").write_text("contenu a\n")
    (work / "b.txt").write_text("contenu b\n")
    (work / "c.txt").write_text("contenu c\n")
    os.symlink("a.txt", work / "lien")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "base")
    run_git(work, "push", "-q", "origin", "HEAD")

    other = tmp_path / f"o{name}"
    subprocess.run(["git", "clone", "-q", str(bare), str(other)], capture_output=True)
    (other / "lien").unlink()
    os.symlink("b.txt", other / "lien")
    run_git(other, "add", ".")
    run_git(other, "commit", "-q", "-m", "distant pointe vers b")
    run_git(other, "push", "-q")

    (work / "lien").unlink()
    os.symlink("c.txt", work / "lien")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "local pointe vers c")
    run_git(work, "fetch", "-q")

    repo = pygit2.Repository(str(work))
    repo.merge(repo.branches[repo.head.shorthand].upstream.target)
    assert repo.index.conflicts is not None
    return repo


def test_resolving_a_symlink_conflict_with_theirs_repoints_it(tmp_path):
    """Review Finding 1 : `open(full, \"wb\")` suivrait le lien et écraserait
    sa cible au lieu de le recréer — la deuxième assertion capture la
    corruption : le contenu de `c.txt` (l'ancienne cible) doit rester
    intact."""
    repo = _symlink_conflict(tmp_path, "sym_theirs")
    workdir = repo.workdir

    result = resolve_with(repo, "lien", Side.THEIRS)
    assert result.success is True, result.git_error

    lien = os.path.join(workdir, "lien")
    assert os.path.islink(lien)
    assert os.readlink(lien) == "b.txt"
    # La cible précédente (avant résolution) ne doit pas avoir été altérée.
    assert open(os.path.join(workdir, "c.txt")).read() == "contenu c\n"
    assert list_conflicts(pygit2.Repository(str(workdir))) == ()


def test_resolving_a_symlink_conflict_with_ours_repoints_it(tmp_path):
    """Même vérification que ci-dessus, avec l'autre camp."""
    repo = _symlink_conflict(tmp_path, "sym_ours")
    workdir = repo.workdir

    result = resolve_with(repo, "lien", Side.OURS)
    assert result.success is True, result.git_error

    lien = os.path.join(workdir, "lien")
    assert os.path.islink(lien)
    assert os.readlink(lien) == "c.txt"
    # La cible du côté non retenu ne doit pas avoir été altérée.
    assert open(os.path.join(workdir, "b.txt")).read() == "contenu b\n"
    assert list_conflicts(pygit2.Repository(str(workdir))) == ()


def test_resolving_keeps_the_executable_bit(tmp_path):
    """Review Finding 2 : le bit +x doit venir du mode du blob retenu, pas
    d'un hasard de ce que `repo.merge()` a laissé sur disque. On force le
    fichier en non-exécutable juste avant `resolve_with` pour que le test
    échoue si le bit n'est que préservé par accident."""
    bare = tmp_path / "x.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], capture_output=True)
    work = tmp_path / "wx"
    subprocess.run(["git", "clone", "-q", str(bare), str(work)], capture_output=True)
    script = work / "run.sh"
    script.write_text("#!/bin/sh\necho base\n")
    os.chmod(script, 0o755)
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "base")
    run_git(work, "push", "-q", "origin", "HEAD")

    other = tmp_path / "ox"
    subprocess.run(["git", "clone", "-q", str(bare), str(other)], capture_output=True)
    other_script = other / "run.sh"
    other_script.write_text("#!/bin/sh\necho distant\n")
    os.chmod(other_script, 0o755)
    run_git(other, "add", ".")
    run_git(other, "commit", "-q", "-m", "distant")
    run_git(other, "push", "-q")

    script.write_text("#!/bin/sh\necho local\n")
    os.chmod(script, 0o755)
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "local")
    run_git(work, "fetch", "-q")

    repo = pygit2.Repository(str(work))
    repo.merge(repo.branches[repo.head.shorthand].upstream.target)
    assert repo.index.conflicts is not None

    # Force le fichier en non-exécutable avant de résoudre : si le bit +x
    # n'était que préservé par accident, il resterait à 0o644 après.
    os.chmod(script, 0o644)

    result = resolve_with(repo, "run.sh", Side.THEIRS)
    assert result.success is True, result.git_error

    mode = os.stat(script).st_mode
    assert mode & stat.S_IXUSR, "le bit exécutable doit venir du blob retenu"
    assert stat.S_IMODE(mode) == 0o755
