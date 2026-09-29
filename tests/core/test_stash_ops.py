import os
import subprocess

import pygit2
import pytest

from tortoisepy.core.stash_ops import (
    apply_stash,
    drop_stash,
    index_of,
    pop_stash,
    stash_changes,
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
    """Un dépôt avec un commit et deux fichiers suivis."""
    path = tmp_path / "d"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "f.txt").write_text("a\nb\n")
    (path / "g.txt").write_text("x\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "base")
    return pygit2.Repository(str(path))


def _sale(repo, contenu="a\nMODIF\n"):
    """Salit l'arbre de travail."""
    open(os.path.join(repo.workdir, "f.txt"), "w").write(contenu)


def test_stashing_cleans_the_tree(repo):
    _sale(repo)
    result = stash_changes(repo, "mon travail")
    assert result.success is True

    fresh = pygit2.Repository(repo.path)
    assert len(fresh.listall_stashes()) == 1
    assert open(os.path.join(fresh.workdir, "f.txt")).read() == "a\nb\n"


def test_stashing_a_clean_tree_is_refused(repo):
    """Vérifié : pygit2 lève « nothing to stash »."""
    result = stash_changes(repo, "rien")
    assert result.success is False
    assert "nothing to stash" in (result.git_error or "").lower()


def test_an_untracked_file_alone_is_stashed(repo):
    """D17 : sans `include_untracked`, rien ne partait (vérifié)."""
    open(os.path.join(repo.workdir, "neuf.txt"), "w").write("neuf\n")
    result = stash_changes(repo, "fichier neuf")
    assert result.success is True
    assert not os.path.exists(os.path.join(repo.workdir, "neuf.txt"))


def test_the_index_follows_the_oid_not_the_position(repo):
    """Le test central : les index glissent (§3).

    Trois stashes, on retire le premier, et l'OID doit toujours désigner
    le bon — sinon on applique le travail de quelqu'un d'autre.
    """
    oids = []
    for i in (1, 2, 3):
        _sale(repo, f"a\nmodif {i}\n")
        assert stash_changes(repo, f"travail {i}").success is True
        # Le plus récent est en 0 : on relit pour capturer son OID.
        oids.append(str(pygit2.Repository(repo.path).listall_stashes()[0].commit_id))

    fresh = pygit2.Repository(repo.path)
    # Le plus récent est en 0 : `oids[-1]` est donc `stash@{0}`.
    assert index_of(fresh, oids[-1]) == 0
    assert index_of(fresh, oids[0]) == 2

    drop_stash(fresh, oids[-1])

    fresh = pygit2.Repository(repo.path)
    assert index_of(fresh, oids[-1]) is None, "le stash retiré ne doit plus être trouvé"
    assert index_of(fresh, oids[0]) == 1, "l'index a glissé, l'OID doit suivre"


def test_acting_on_an_unknown_oid_is_refused(repo):
    """Plutôt que d'agir au hasard sur un index."""
    _sale(repo)
    stash_changes(repo, "un")
    fresh = pygit2.Repository(repo.path)
    for operation in (apply_stash, pop_stash, drop_stash):
        result = operation(fresh, "0" * 40)
        assert result.success is False
        assert "no longer" in (result.git_error or "").lower()


def test_apply_restores_and_keeps_the_stash(repo):
    _sale(repo)
    stash_changes(repo, "mon travail")
    fresh = pygit2.Repository(repo.path)
    oid = str(fresh.listall_stashes()[0].commit_id)

    result = apply_stash(fresh, oid)
    assert result.success is True
    assert open(os.path.join(fresh.workdir, "f.txt")).read() == "a\nMODIF\n"
    assert len(pygit2.Repository(repo.path).listall_stashes()) == 1, (
        "apply conserve le stash"
    )


def test_pop_restores_and_removes_the_stash(repo):
    _sale(repo)
    stash_changes(repo, "mon travail")
    fresh = pygit2.Repository(repo.path)
    oid = str(fresh.listall_stashes()[0].commit_id)

    result = pop_stash(fresh, oid)
    assert result.success is True
    assert open(os.path.join(fresh.workdir, "f.txt")).read() == "a\nMODIF\n"
    assert pygit2.Repository(repo.path).listall_stashes() == []


def test_a_failed_pop_keeps_the_stash(repo):
    """Review Focus 4 : c'est ce qui rend Pop sans danger."""
    _sale(repo, "a\nSTASH\n")
    stash_changes(repo, "mon travail")
    # On modifie la même ligne autrement : l'application ne peut pas passer.
    _sale(repo, "a\nAUTRE\n")

    fresh = pygit2.Repository(repo.path)
    oid = str(fresh.listall_stashes()[0].commit_id)
    result = pop_stash(fresh, oid)

    assert result.success is False
    fresh = pygit2.Repository(repo.path)
    assert len(fresh.listall_stashes()) == 1, "le stash doit survivre"
    assert open(os.path.join(fresh.workdir, "f.txt")).read() == "a\nAUTRE\n"
    assert int(fresh.state()) == 0, "aucun état conflictuel (§5)"


def test_drop_removes_without_restoring(repo):
    _sale(repo)
    stash_changes(repo, "mon travail")
    fresh = pygit2.Repository(repo.path)
    oid = str(fresh.listall_stashes()[0].commit_id)

    result = drop_stash(fresh, oid)
    assert result.success is True
    fresh = pygit2.Repository(repo.path)
    assert fresh.listall_stashes() == []
    assert open(os.path.join(fresh.workdir, "f.txt")).read() == "a\nb\n", (
        "drop ne restaure rien"
    )


def test_a_refused_pop_reports_no_change(repo):
    """Revue de tâche : `changed_on_error` n'a pas lieu d'être ici.

    Contrairement au merge ou au rebase, qui modifient puis échouent,
    libgit2 refuse un stash inapplicable **avant** d'y toucher. Annoncer
    un changement provoquerait un rafraîchissement pour rien.
    """
    _sale(repo, "a\nSTASH\n")
    stash_changes(repo, "mon travail")
    _sale(repo, "a\nAUTRE\n")

    fresh = pygit2.Repository(repo.path)
    oid = str(fresh.listall_stashes()[0].commit_id)
    result = pop_stash(fresh, oid)

    assert result.success is False
    assert result.repository_changed is False


def test_stashing_works_without_a_configured_user(repo):
    """`default_signature` lève `InvalidError` sur un `user.name` vide.

    Elle hérite de `GitError`, donc le repli la couvre — mais rien ne le
    vérifiait. Un stash est local : il ne doit pas exiger une
    configuration d'auteur.
    """
    run_git(repo.workdir, "config", "--local", "user.name", "")
    run_git(repo.workdir, "config", "--local", "user.email", "")
    _sale(repo)

    result = stash_changes(pygit2.Repository(repo.path), "sans auteur")
    assert result.success is True, result.git_error
    assert len(pygit2.Repository(repo.path).listall_stashes()) == 1


def test_looking_up_a_stash_in_a_repository_without_any(repo):
    """`index_of` ne doit pas lever sur un dépôt sans stash."""
    assert index_of(repo, "a" * 40) is None
