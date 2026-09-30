import os
import subprocess

import pygit2
import pytest

from tortoisepy.core.amend import amend_commit, can_amend, last_commit_message


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
    """Un dépôt avec un commit et un fichier suivi."""
    path = tmp_path / "d"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "f.txt").write_text("a\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "message initial")
    return pygit2.Repository(str(path))


def test_the_last_message_is_read_back(repo):
    assert last_commit_message(repo).strip() == "message initial"


def test_amending_only_the_message(repo):
    result = amend_commit(repo, (), "message corrige")
    assert result.success is True

    fresh = pygit2.Repository(repo.path)
    commit = fresh.head.peel(pygit2.Commit)
    assert commit.message.strip() == "message corrige"
    assert len(list(fresh.walk(commit.id))) == 1, "un seul commit"


def test_amending_adds_a_forgotten_file(repo):
    """La moitié du besoin : le fichier qu'on a oublié d'ajouter."""
    open(os.path.join(repo.workdir, "oublie.txt"), "w").write("oublie\n")

    result = amend_commit(repo, ("oublie.txt",), "message initial")
    assert result.success is True

    fresh = pygit2.Repository(repo.path)
    commit = fresh.head.peel(pygit2.Commit)
    assert sorted(e.name for e in commit.tree) == ["f.txt", "oublie.txt"]
    assert len(list(fresh.walk(commit.id))) == 1


def test_amending_keeps_the_original_author(repo):
    """Review Focus 3 : amender n'est pas se réapproprier le travail."""
    avant = repo.head.peel(pygit2.Commit).author
    amend_commit(repo, (), "autre message")

    apres = pygit2.Repository(repo.path).head.peel(pygit2.Commit).author
    assert apres.name == avant.name
    assert apres.time == avant.time


def test_amending_the_root_commit(repo):
    """Le premier commit n'a pas de parent, et s'amende quand même."""
    result = amend_commit(repo, (), "racine amendee")
    assert result.success is True
    fresh = pygit2.Repository(repo.path)
    assert fresh.head.peel(pygit2.Commit).message.strip() == "racine amendee"


def test_amending_on_a_detached_head_creates_no_orphan(repo):
    """Review Focus 1 : le seul cas vraiment dangereux.

    Vérifié : libgit2 **accepte** l'amend sur une HEAD détachée, et le
    nouveau commit n'est suivi par aucune branche — invisible dans le
    graphe, récupérable seulement par le reflog.
    """
    run_git(repo.workdir, "checkout", "-q", "--detach")
    detache = pygit2.Repository(repo.path)
    avant = str(detache.head.target)

    assert can_amend(detache) is not None
    result = amend_commit(detache, (), "ne doit pas passer")
    assert result.success is False

    fresh = pygit2.Repository(repo.path)
    assert str(fresh.head.target) == avant, "aucun commit créé"


def test_amending_an_empty_repository_is_refused(tmp_path):
    path = tmp_path / "vide"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    vide = pygit2.Repository(str(path))

    assert can_amend(vide) is not None
    result = amend_commit(vide, (), "rien")
    assert result.success is False


def test_amending_during_another_operation_is_refused(repo):
    """L'état est déjà instable : n'y ajoutons pas une réécriture."""
    run_git(repo.workdir, "checkout", "-q", "-b", "autre")
    open(os.path.join(repo.workdir, "f.txt"), "w").write("autre\n")
    run_git(repo.workdir, "commit", "-q", "-am", "cote autre")
    run_git(repo.workdir, "checkout", "-q", "main")
    open(os.path.join(repo.workdir, "f.txt"), "w").write("main\n")
    run_git(repo.workdir, "commit", "-q", "-am", "cote main")
    run_git(repo.workdir, "merge", "autre")  # conflit -> état MERGE

    en_conflit = pygit2.Repository(repo.path)
    assert en_conflit.state() != pygit2.enums.RepositoryState.NONE
    assert can_amend(en_conflit) is not None
    assert amend_commit(en_conflit, (), "pendant un merge").success is False


def test_amending_refuses_an_empty_message(repo):
    assert amend_commit(repo, (), "   ").success is False


def test_an_amend_failure_is_labelled_amend(repo):
    """Revue finale, Minor : l'échec s'annonçait « Commit ».

    `_build_tree` est partagé avec `commit_selection` et codait son
    étiquette en dur : un amend raté ouvrait une fenêtre d'erreur
    désignant le mauvais geste.
    """
    result = amend_commit(repo, ("nexistepas.txt",), "un message")
    assert result.success is False
    assert result.summary == "Amend"
    assert "file not found" in (result.git_error or "")
