"""Conclure une résolution même sans `MERGE_HEAD`.

Signalé par l'utilisateur, capture à l'appui : après avoir résolu son
conflit avec « Take theirs », « Resolve » répondait *« Fusion did not
complete — Git says: no merge in progress »*. Plus rien n'était possible
à part « Abort », qui aurait détruit les résolutions.

Reproduit :

    conflits apres « Take theirs » : []
    Resolve -> success=False  « no merge in progress »
    index modifie non commite ? True

Les résolutions sont dans l'index, mais `conclude_merge` refusait de les
commiter faute de `MERGE_HEAD` — le fichier d'état que git supprime, ou
qui disparaît après une fermeture brutale.

Un commit ORDINAIRE est alors la bonne réponse : sans `MERGE_HEAD`, on
ne connaît pas le second parent, donc on n'invente pas un commit de
fusion — mais le travail de l'utilisateur doit être sauvé.
"""

from __future__ import annotations

import pathlib
import subprocess

import pygit2
import pytest

from tortoisepy.core.conflicts import Side, conclude_merge, resolve_with
from tortoisepy.core.state import read_state


def _git(chemin, *args):
    subprocess.run(
        ["git", "-C", str(chemin), *args], check=False, capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
            "PATH": "/usr/bin:/bin:/usr/local/bin",
        },
    )


def _depot_en_conflit(tmp_path):
    w = tmp_path / "w"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "v.txt").write_text("base\n")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "base")
    _git(w, "checkout", "-q", "-b", "TEST")
    (w / "v.txt").write_text("leur version\n")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "cote TEST")
    _git(w, "checkout", "-q", "main")
    (w / "v.txt").write_text("notre version\n")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "cote main")
    _git(w, "merge", "TEST")
    return w


@pytest.fixture
def merge_orphelin(tmp_path):
    """Conflits résolus, mais `MERGE_HEAD` a disparu."""
    w = _depot_en_conflit(tmp_path)
    (pathlib.Path(w) / ".git" / "MERGE_HEAD").unlink()
    resolve_with(pygit2.Repository(str(w)), "v.txt", Side.THEIRS)
    return w


def test_a_normal_merge_still_creates_a_merge_commit(tmp_path):
    """Le cas nominal ne doit pas régresser : deux parents."""
    w = _depot_en_conflit(tmp_path)
    resolve_with(pygit2.Repository(str(w)), "v.txt", Side.THEIRS)

    resultat = conclude_merge(pygit2.Repository(str(w)))
    assert resultat.success, resultat.git_error

    repo = pygit2.Repository(str(w))
    assert len(repo.get(repo.head.target).parents) == 2, (
        "un vrai merge doit garder ses deux parents"
    )


def test_resolutions_are_committed_without_merge_head(merge_orphelin):
    """L'assertion centrale : le travail de l'utilisateur est sauvé."""
    avant = str(pygit2.Repository(str(merge_orphelin)).head.target)

    resultat = conclude_merge(pygit2.Repository(str(merge_orphelin)))

    assert resultat.success, resultat.git_error
    repo = pygit2.Repository(str(merge_orphelin))
    assert str(repo.head.target) != avant, "rien n'a été commité"


def test_the_commit_has_a_single_parent_without_merge_head(merge_orphelin):
    """Sans `MERGE_HEAD`, le second parent est inconnu : ne pas l'inventer.

    Un commit de fusion dont le second parent serait deviné mentirait sur
    l'histoire du dépôt.
    """
    conclude_merge(pygit2.Repository(str(merge_orphelin)))

    repo = pygit2.Repository(str(merge_orphelin))
    assert len(repo.get(repo.head.target).parents) == 1


def test_the_resolved_content_is_what_was_chosen(merge_orphelin):
    """« Take theirs » doit vraiment garder leur version."""
    conclude_merge(pygit2.Repository(str(merge_orphelin)))

    contenu = (pathlib.Path(merge_orphelin) / "v.txt").read_text()
    assert contenu == "leur version\n", contenu


def test_the_tree_is_clean_afterwards(merge_orphelin):
    """Plus rien en attente : l'utilisateur peut changer de branche."""
    conclude_merge(pygit2.Repository(str(merge_orphelin)))

    repo = pygit2.Repository(str(merge_orphelin))
    assert not repo.status(), repo.status()
    etat = read_state(repo)
    assert not etat.has_conflicts
    assert etat.operation_in_progress is None


def test_unresolved_conflicts_are_still_refused(tmp_path):
    """La garantie de la phase 6 : jamais de marqueurs dans un commit."""
    w = _depot_en_conflit(tmp_path)
    (pathlib.Path(w) / ".git" / "MERGE_HEAD").unlink()

    resultat = conclude_merge(pygit2.Repository(str(w)))
    assert not resultat.success
    assert "unresolved" in (resultat.git_error or "")


def test_nothing_to_commit_is_refused(tmp_path):
    """Un dépôt propre n'a rien à conclure."""
    w = tmp_path / "propre"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "a.txt").write_text("a")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "base")

    resultat = conclude_merge(pygit2.Repository(str(w)))
    assert not resultat.success
