# tests/conftest.py
"""Dépôts de référence, §10.2 de la spec.

Le mode offscreen est posé ici, à la racine des tests, et non dans
`tests/ui/` seulement : tout test qui construit un widget Qt en a besoin,
où qu'il vive. Il doit l'être AVANT le premier import de PySide6, d'où sa
place au niveau module.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pygit2
import pytest

from tests.fixtures.builder import RepoBuilder


@pytest.fixture
def repo_linear(tmp_path):
    """1. Branche unique, quatre commits."""
    b = RepoBuilder(tmp_path / "linear")
    for name in ("A", "B", "C", "D"):
        b.commit(name)
    return b


@pytest.fixture
def repo_diverged(tmp_path):
    """2. Deux branches divergentes — le cas du merge-base (§4.2).

    A ─ B ─ C ─ D        master
             \\
              X ─ Y ─ Z  feature

    Ni master ni feature n'est ancêtre de l'autre. Le merge-base est C.
    """
    b = RepoBuilder(tmp_path / "diverged")
    a = b.commit("A")
    bb = b.commit("B")
    c = b.commit("C")
    d = b.commit("D")
    b.branch("feature", c)
    b.checkout("feature")
    x = b.commit("X", parents=[c])
    y = b.commit("Y", parents=[x])
    z = b.commit("Z", parents=[y])
    b.branch("feature", z)
    b.merge_base_expected = c
    b.master_tip = d
    b.feature_tip = z
    return b


@pytest.fixture
def repo_merge(tmp_path):
    """3. Un merge simple."""
    b = RepoBuilder(tmp_path / "merge")
    a = b.commit("A")
    left = b.commit("left", parents=[a])
    right = b.commit("right", parents=[a])
    merge = b.commit("merge", parents=[left, right])
    b.branch("side", right)
    b.branch("master", merge)
    b.merge_oid = merge
    b.left_oid = left
    b.right_oid = right
    return b


@pytest.fixture
def repo_nested_merges(tmp_path):
    """4. Merges imbriqués."""
    b = RepoBuilder(tmp_path / "nested")
    root = b.commit("root")
    a1 = b.commit("a1", parents=[root])
    b1 = b.commit("b1", parents=[root])
    m1 = b.commit("m1", parents=[a1, b1])
    c1 = b.commit("c1", parents=[root])
    m2 = b.commit("m2", parents=[m1, c1])
    b.branch("master", m2)
    b.final_merge = m2
    return b


@pytest.fixture
def repo_long_linear(tmp_path):
    """5. Mille commits sans ref intermédiaire (compression)."""
    b = RepoBuilder(tmp_path / "long")
    first = b.commit("first")
    previous = first
    for i in range(1000):
        previous = b.commit(f"c{i}", parents=[previous])
    b.branch("tip", previous)
    b.first_oid = first
    b.tip_oid = previous
    return b


@pytest.fixture
def repo_two_merge_bases(tmp_path):
    """11. Merges croisés : DEUX merge-bases entre A et B.

    Vérifié en ligne de commande : `git merge-base -a` retourne deux OID
    là où `git merge-base` n'en retourne qu'un. Une implémentation
    utilisant la forme singulière rate une jonction.
    """
    b = RepoBuilder(tmp_path / "twobases")
    root = b.commit("root")
    a1 = b.commit("a1", parents=[root])
    b1 = b.commit("b1", parents=[root])
    # Merges croisés : chacun fusionne l'autre branche
    x = b.commit("x", parents=[a1, b1])
    y = b.commit("y", parents=[b1, a1])
    b.branch("A", x)
    b.branch("B", y)
    b.tip_a = x
    b.tip_b = y
    b.expected_base_count = 2
    return b


@pytest.fixture
def repo_octopus(tmp_path):
    """12. Merge octopus : un commit à quatre parents.

    Vérifié : `git merge b1 b2 b3` produit un commit à quatre parents.
    Tout code indexant parents[0] et parents[1] est faux ici.
    """
    b = RepoBuilder(tmp_path / "octopus")
    base = b.commit("base")
    p1 = b.commit("p1", parents=[base])
    p2 = b.commit("p2", parents=[base])
    p3 = b.commit("p3", parents=[base])
    p4 = b.commit("p4", parents=[base])
    octopus = b.commit("octopus", parents=[p1, p2, p3, p4])
    b.branch("master", octopus)
    b.octopus_oid = octopus
    return b


@pytest.fixture
def repo_stashes(tmp_path):
    """13. Plusieurs stashes à premiers parents différents.

    Construits via l'exécutable git : pygit2 n'expose pas de création de
    stash aussi directement, et on teste ici la lecture, pas l'écriture.
    """
    import subprocess

    path = tmp_path / "stashes"
    path.mkdir()

    def git(*args):
        subprocess.run(
            ["git", *args], cwd=path, check=True,
            capture_output=True,
            env={"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
                 "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
                 "PATH": "/usr/bin:/bin:/usr/local/bin"},
        )

    git("init", "-q", "-b", "master")
    (path / "f.txt").write_text("base\n")
    git("add", "f.txt")
    git("commit", "-q", "-m", "base")

    (path / "f.txt").write_text("stash 1\n")
    git("stash", "-q")

    (path / "f.txt").write_text("second commit\n")
    git("add", "f.txt")
    git("commit", "-q", "-m", "second")

    (path / "f.txt").write_text("stash 2\n")
    (path / "untracked.txt").write_text("untracked\n")
    git("stash", "-q", "-u")

    import pygit2
    class _Holder:
        pass
    holder = _Holder()
    holder.repo = pygit2.Repository(str(path))
    return holder


@pytest.fixture
def repo_multi_ref_commit(tmp_path):
    """6 et 14. Un commit portant branche locale, distante et tag annoté."""
    b = RepoBuilder(tmp_path / "multiref")
    oid = b.commit("only")
    b.branch("develop", oid)
    b.remote_ref("origin", "develop", oid)
    b.tag_annotated("v1.0", oid)
    b.shared_oid = oid
    return b


@pytest.fixture
def repo_tags(tmp_path):
    """7. Tags légers et annotés."""
    b = RepoBuilder(tmp_path / "tags")
    first = b.commit("first")
    second = b.commit("second")
    b.tag_lightweight("light", first)
    b.tag_annotated("heavy", second)
    b.first_oid = first
    b.second_oid = second
    return b


@pytest.fixture
def repo_remotes(tmp_path):
    """8. Plusieurs remotes."""
    b = RepoBuilder(tmp_path / "remotes")
    oid = b.commit("c1")
    other = b.commit("c2")
    b.remote_ref("origin", "master", oid)
    b.remote_ref("github", "master", other)
    return b


@pytest.fixture
def repo_detached_head(tmp_path):
    """10. HEAD détaché sur un commit déjà porteur d'un tag."""
    b = RepoBuilder(tmp_path / "detached")
    first = b.commit("first")
    b.commit("second")
    b.tag_lightweight("v1.0", first)
    b.repo.set_head(pygit2.Oid(hex=first))
    b.detached_oid = first
    return b


@pytest.fixture
def repo_multiple_roots(tmp_path):
    """15. Deux historiques indépendants dans un même dépôt."""
    b = RepoBuilder(tmp_path / "roots")
    a1 = b.commit("a1", parents=[])
    a2 = b.commit("a2", parents=[a1])
    b1 = b.commit("b1", parents=[])
    b.branch("first", a2)
    b.branch("second", b1)
    b.root_a = a1
    b.root_b = b1
    return b
