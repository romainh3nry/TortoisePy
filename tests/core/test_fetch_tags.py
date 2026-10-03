"""Le fetch doit aussi tenir les tags à jour.

Signalé par l'utilisateur. Mesuré dans un dépôt jetable : les NOUVEAUX
tags arrivent bien, mais deux cas échouaient —

    clone       : {'v1.0': '0685f319', 'v2.0': '0685f319'}
    apres fetch : {'v1.0': '0685f319', 'v2.0': '0685f319'}

    tag SUPPRIMÉ du serveur retiré ? False
    tag DÉPLACÉ mis à jour ?         False
       serveur v2.0 = b7c64db8   local v2.0 = 0685f319

Le refspec par défaut (`refs/heads/*`) ne couvre pas les tags : git les
rapporte par un mécanisme séparé qui ne supprime ni ne déplace rien.
"""

from __future__ import annotations

import subprocess

import pygit2
import pytest

from tortoisepy.core.operations import fetch_remote


def _git(chemin, *args):
    subprocess.run(
        ["git", "-C", str(chemin), *args], check=False, capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
            "PATH": "/usr/bin:/bin:/usr/local/bin",
        },
    )


def _tags(chemin) -> dict[str, str]:
    repo = pygit2.Repository(str(chemin))
    return {
        nom.replace("refs/tags/", ""): str(repo.references[nom].target)
        for nom in repo.references
        if nom.startswith("refs/tags/")
    }


@pytest.fixture
def serveur_et_clone(tmp_path):
    """Un serveur portant deux tags, et un clone à jour."""
    serveur = tmp_path / "s.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", str(serveur)], check=True,
        capture_output=True,
    )
    source = tmp_path / "source"
    subprocess.run(
        ["git", "clone", "-q", str(serveur), str(source)], check=True,
        capture_output=True,
    )
    (source / "a.txt").write_text("a\n")
    _git(source, "add", ".")
    _git(source, "commit", "-q", "-m", "base")
    _git(source, "push", "-q", "origin", "HEAD:refs/heads/main")
    _git(source, "tag", "v1.0")
    _git(source, "tag", "v2.0")
    _git(source, "push", "-q", "origin", "--tags")

    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", "-q", str(serveur), str(clone)], check=True,
        capture_output=True,
    )
    return source, clone


def test_a_new_tag_is_fetched(tmp_path):
    """Le cas qui marchait déjà : rien ne doit régresser."""
    serveur = tmp_path / "s.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", str(serveur)], check=True,
        capture_output=True,
    )
    source = tmp_path / "source"
    subprocess.run(
        ["git", "clone", "-q", str(serveur), str(source)], check=True,
        capture_output=True,
    )
    (source / "a.txt").write_text("a\n")
    _git(source, "add", ".")
    _git(source, "commit", "-q", "-m", "base")
    _git(source, "push", "-q", "origin", "HEAD:refs/heads/main")

    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", "-q", str(serveur), str(clone)], check=True,
        capture_output=True,
    )
    _git(source, "tag", "v1.0")
    _git(source, "push", "-q", "origin", "v1.0")

    fetch_remote(pygit2.Repository(str(clone)))
    assert "v1.0" in _tags(clone)


def test_a_tag_deleted_on_the_server_is_removed(serveur_et_clone):
    """Signalé : un tag supprimé côté serveur survivait en local."""
    source, clone = serveur_et_clone
    assert "v1.0" in _tags(clone)

    _git(source, "push", "-q", "origin", ":refs/tags/v1.0")
    fetch_remote(pygit2.Repository(str(clone)))

    assert "v1.0" not in _tags(clone), (
        "le tag supprimé du serveur survit au fetch"
    )


def test_a_moved_tag_follows(serveur_et_clone):
    """Signalé : un tag déplacé gardait son ancienne cible.

    C'est le cas le plus trompeur — le tag existe des deux côtés, mais
    il ne désigne pas le même commit.
    """
    source, clone = serveur_et_clone
    ancien = _tags(clone)["v2.0"]

    (source / "b.txt").write_text("b\n")
    _git(source, "add", ".")
    _git(source, "commit", "-q", "-m", "second")
    _git(source, "push", "-q", "origin", "main")
    _git(source, "tag", "-f", "v2.0")
    _git(source, "push", "-q", "--force", "origin", "v2.0")

    fetch_remote(pygit2.Repository(str(clone)))

    nouveau = _tags(clone).get("v2.0")
    assert nouveau is not None, "le tag a disparu"
    assert nouveau != ancien, "le tag déplacé garde son ancienne cible"
    assert nouveau == _tags(source)["v2.0"], "cible différente du serveur"


def test_the_summary_mentions_the_tags(serveur_et_clone):
    """L'utilisateur doit savoir ce qui a bougé."""
    source, clone = serveur_et_clone
    _git(source, "tag", "v3.0")
    _git(source, "push", "-q", "origin", "v3.0")

    resultat = fetch_remote(pygit2.Repository(str(clone)))
    assert resultat.success
    assert "v3.0" in resultat.summary, resultat.summary


def test_branches_are_still_fetched(serveur_et_clone):
    """La correction ne doit pas emporter le comportement d'origine."""
    source, clone = serveur_et_clone
    _git(source, "checkout", "-q", "-b", "nouvelle")
    (source / "c.txt").write_text("c\n")
    _git(source, "add", ".")
    _git(source, "commit", "-q", "-m", "sur nouvelle")
    _git(source, "push", "-q", "origin", "nouvelle")

    fetch_remote(pygit2.Repository(str(clone)))

    repo = pygit2.Repository(str(clone))
    assert "origin/nouvelle" in list(repo.branches.remote)


def test_a_deleted_remote_branch_is_still_pruned(serveur_et_clone):
    """Le prune des branches, ajouté plus tôt, doit survivre."""
    source, clone = serveur_et_clone
    _git(source, "checkout", "-q", "-b", "ephemere")
    (source / "d.txt").write_text("d\n")
    _git(source, "add", ".")
    _git(source, "commit", "-q", "-m", "x")
    _git(source, "push", "-q", "origin", "ephemere")
    fetch_remote(pygit2.Repository(str(clone)))
    assert "origin/ephemere" in list(
        pygit2.Repository(str(clone)).branches.remote
    )

    _git(source, "push", "-q", "origin", ":ephemere")
    fetch_remote(pygit2.Repository(str(clone)))

    assert "origin/ephemere" not in list(
        pygit2.Repository(str(clone)).branches.remote
    )
