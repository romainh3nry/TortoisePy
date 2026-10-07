"""Comparer deux révisions — `git diff A B` et `git log A..B`.

Deux entrées du menu contextuel les promettaient depuis le début, à la
sélection de deux nœuds :

    Compare revisions        -> _not_available
    Show log of differences  -> _not_available

Toutes deux **actives** et sans effet (vérifié). C'est le même défaut
que `show_log`, câblé il y a quelques jours : une entrée qui ne répond
pas est pire qu'une entrée absente, parce qu'elle apprend à se méfier de
l'interface.

Les deux briques existaient : `_commit_diff` compare un commit à son
parent, `read_log` parcourt une ref. Il manquait de pouvoir viser deux
commits quelconques.
"""

from __future__ import annotations

import subprocess

import pygit2
import pytest

from tortoisepy.core.changes import changes_between, diff_between
from tortoisepy.core.log import read_log

ENV = {
    "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
    "PATH": "/usr/bin:/bin:/usr/local/bin",
}


def _git(chemin, *args, check=True):
    return subprocess.run(
        ["git", "-C", str(chemin), *args], check=check,
        capture_output=True, env=ENV, text=True,
    )


@pytest.fixture
def depot(tmp_path):
    """Quatre commits en ligne, pour comparer des points éloignés.

        A ─ B ─ C ─ D

        A : a.txt
        B : + b.txt
        C : a.txt modifié
        D : + d.txt, b.txt supprimé
    """
    w = tmp_path / "w"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    oids = []

    def commit(message):
        _git(w, "add", "-A")
        _git(w, "commit", "-qm", message)
        oids.append(str(pygit2.Repository(str(w)).head.target))

    (w / "a.txt").write_text("version 1\n")
    commit("A")

    (w / "b.txt").write_text("b\n")
    commit("B")

    (w / "a.txt").write_text("version 2\n")
    commit("C")

    (w / "d.txt").write_text("d\n")
    (w / "b.txt").unlink()
    commit("D")

    return pygit2.Repository(str(w)), oids


# --- les fichiers qui diffèrent -----------------------------------------


def test_comparing_a_commit_with_itself_shows_nothing(depot):
    """Deux fois le même commit : aucune différence.

    Le piège : rendre tout l'arbre, ou les fichiers du commit, au lieu
    de rien.
    """
    repo, oids = depot
    assert changes_between(repo, oids[0], oids[0]) == ()


def test_comparing_two_adjacent_commits(depot):
    """A..B n'ajoute qu'un fichier."""
    repo, oids = depot
    chemins = [c.path for c in changes_between(repo, oids[0], oids[1])]

    assert chemins == ["b.txt"]


def test_comparing_across_several_commits(depot):
    """A..D : le cumul, pas le dernier pas.

    C'est tout l'intérêt par rapport au détail d'un commit — voir ce qui
    sépare deux points de l'histoire, même éloignés.
    """
    repo, oids = depot
    chemins = sorted(c.path for c in changes_between(repo, oids[0], oids[3]))

    assert chemins == ["a.txt", "d.txt"], (
        "b.txt, ajouté puis supprimé entre les deux, ne doit pas figurer"
    )


def test_the_direction_matters(depot):
    """D..A doit montrer l'inverse de A..D.

    Comparer dans le mauvais sens affiche des ajouts là où il y a des
    suppressions : le sens doit être celui demandé.
    """
    repo, oids = depot
    avant = {c.path: c.kind for c in changes_between(repo, oids[0], oids[3])}
    apres = {c.path: c.kind for c in changes_between(repo, oids[3], oids[0])}

    from tortoisepy.core.changes import ChangeKind

    assert avant["d.txt"] is ChangeKind.ADDED
    assert apres["d.txt"] is ChangeKind.DELETED


def test_a_deleted_file_is_reported(depot):
    """B..D supprime b.txt : la suppression doit se voir."""
    from tortoisepy.core.changes import ChangeKind

    repo, oids = depot
    par_chemin = {
        c.path: c.kind for c in changes_between(repo, oids[1], oids[3])
    }

    assert par_chemin["b.txt"] is ChangeKind.DELETED


def test_an_unknown_revision_yields_nothing(depot):
    """Un OID absent ne doit pas lever : un nœud peut disparaître."""
    repo, oids = depot
    assert changes_between(repo, "0" * 40, oids[0]) == ()


# --- le diff d'un fichier entre deux révisions --------------------------


def test_the_diff_of_one_file_between_two_revisions(depot):
    """Le contenu de la différence, pas seulement la liste des fichiers."""
    repo, oids = depot
    diff = diff_between(repo, oids[0], oids[3], "a.txt")

    texte = "\n".join(
        ligne.content for hunk in diff.hunks for ligne in hunk.lines
    )
    assert "version 1" in texte
    assert "version 2" in texte


def test_the_diff_of_an_untouched_file_is_empty(depot):
    """Un fichier identique des deux côtés n'a pas de hunk."""
    repo, oids = depot
    diff = diff_between(repo, oids[2], oids[3], "a.txt")

    assert diff.hunks == ()


# --- les commits qui séparent deux révisions ----------------------------


def test_the_log_between_two_revisions(depot):
    """`git log A..D` : les commits de D que A n'a pas.

    `read_log` sait déjà parcourir une ref ; il manquait de pouvoir
    borner ce parcours.
    """
    repo, oids = depot
    journal = read_log(repo, ref=oids[3], until=oids[0])

    assert [c.summary for c in journal] == ["D", "C", "B"], (
        "A lui-même ne doit pas figurer : il est la borne"
    )


def test_the_log_between_adjacent_revisions(depot):
    """Un seul commit d'écart : un seul résultat."""
    repo, oids = depot
    journal = read_log(repo, ref=oids[1], until=oids[0])

    assert [c.summary for c in journal] == ["B"]


def test_the_log_of_a_revision_with_itself_is_empty(depot):
    """Rien ne sépare un commit de lui-même."""
    repo, oids = depot
    assert read_log(repo, ref=oids[2], until=oids[2]) == ()


def test_an_unknown_boundary_is_ignored(depot):
    """Une borne introuvable ne doit pas vider le journal en silence.

    Mieux vaut rendre l'historique entier — ce que `read_log` fait sans
    borne — que de laisser croire qu'il n'y a rien à voir.
    """
    repo, oids = depot
    journal = read_log(repo, ref=oids[3], until="0" * 40)

    assert len(journal) == 4, (
        f"4 commits attendus sans borne valide, obtenu {len(journal)}"
    )


def test_reading_a_comparison_writes_nothing(depot):
    """§7.0 : comparer est une consultation."""
    repo, oids = depot
    refs_avant = {r: str(repo.references[r].target) for r in repo.references}

    changes_between(repo, oids[0], oids[3])
    diff_between(repo, oids[0], oids[3], "a.txt")
    read_log(repo, ref=oids[3], until=oids[0])

    assert {
        r: str(repo.references[r].target) for r in repo.references
    } == refs_avant
