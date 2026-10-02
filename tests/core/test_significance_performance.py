"""`significant_commits` domine le coût de `build_graph`.

Mesuré sur le dépôt réel de l'utilisateur (701 refs, 16 080 commits) :

    collect_refs + filtre        39.6 ms
    significant_commits        1041.7 ms   <- 87 % du total
    group_refs_by_oid             0.1 ms
    compress_linear_segments     43.0 ms
    reduce_transitive_edges      50.7 ms
    collapse_trivial_junctions   16.7 ms

Cause : `_analyse` propage des `set` d'OID (des chaînes de 40 caractères)
le long de tout le DAG — `marks[parent] |= inherited` pour chaque arête.
Avec 701 pointes, chaque union manipule des ensembles de centaines
d'éléments, des dizaines de milliers de fois.

Un masque de bits fait le même travail en une instruction : c'est ce qui
avait déjà fait passer `reduce_transitive_edges` de 16,4 s à 0,04 s en
phase 17.
"""

from __future__ import annotations

import subprocess
import time

import pygit2
import pytest

from tortoisepy.core.refs import collect_refs
from tortoisepy.core.significance import significant_commits


def _git(chemin, *args):
    subprocess.run(
        ["git", "-C", str(chemin), *args], check=False, capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
            "PATH": "/usr/bin:/bin:/usr/local/bin",
        },
    )


@pytest.fixture(scope="module")
def depot_large(tmp_path_factory):
    """700 branches sur une chaîne de 2000 commits.

    L'échelle qui fait apparaître le coût : beaucoup de pointes ET un
    historique profond, comme un dépôt d'équipe.
    """
    w = tmp_path_factory.mktemp("large") / "w"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "f.txt").write_text("0\n")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "base")

    repo = pygit2.Repository(str(w))
    signature = pygit2.Signature("T", "t@t", 0, 0)
    parent = repo.head.target
    oids = [str(parent)]
    arbre = repo.revparse_single("HEAD").tree.id

    for i in range(2000):
        parent = repo.create_commit(
            None, signature, signature, f"c{i}", arbre, [parent]
        )
        oids.append(str(parent))

    repo.references.create("refs/heads/main", parent, force=True)
    for i in range(700):
        repo.references.create(
            f"refs/heads/b{i}", pygit2.Oid(hex=oids[i * 2]), force=True
        )

    return pygit2.Repository(str(w))


def test_the_result_is_unchanged(depot_large):
    """Le filet : l'optimisation ne doit rien changer au RÉSULTAT.

    C'est l'assertion qui compte — la vitesse se mesure, la justesse se
    teste.
    """
    repo = depot_large
    refs = collect_refs(repo)
    resultat = significant_commits(repo, refs)

    pointes = {ref.target for ref in refs}
    assert pointes <= resultat, "toute pointe doit être significative"

    # La racine aussi : sans elle le graphe perdrait son origine.
    racine = next(
        str(c.id) for c in repo.walk(repo.head.target) if not c.parents
    )
    assert racine in resultat


def test_it_stays_fast(depot_large):
    """Garde-fou : 700 pointes sur 2000 commits en moins d'une seconde.

    Mesuré sur le dépôt de l'utilisateur, l'ancienne version mettait
    1042 ms pour 701 pointes — le coût croît avec le produit des deux.
    """
    repo = depot_large
    refs = collect_refs(repo)

    debut = time.perf_counter()
    significant_commits(repo, refs)
    ecoule = time.perf_counter() - debut

    assert ecoule < 1.0, f"{ecoule:.2f} s pour 700 pointes / 2000 commits"


def test_merge_bases_are_still_found(tmp_path):
    """Un merge-base doit rester significatif : c'est là que l'histoire
    diverge, et le masquer déconnecterait le graphe."""
    w = tmp_path / "w"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "f.txt").write_text("base\n")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "base")
    base = subprocess.run(
        ["git", "-C", str(w), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    for nom in ("gauche", "droite"):
        _git(w, "checkout", "-q", "-b", nom, "main")
        (w / f"{nom}.txt").write_text("x\n")
        _git(w, "add", ".")
        _git(w, "commit", "-q", "-m", nom)

    repo = pygit2.Repository(str(w))
    resultat = significant_commits(repo, collect_refs(repo))
    assert base in resultat, "le point de divergence a disparu"


def test_a_merge_and_its_parents_stay_significant(tmp_path):
    """Un merge et ses parents directs structurent le graphe."""
    w = tmp_path / "w"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "f.txt").write_text("base\n")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "base")
    _git(w, "checkout", "-q", "-b", "cote")
    (w / "g.txt").write_text("x\n")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "cote")
    _git(w, "checkout", "-q", "main")
    (w / "h.txt").write_text("y\n")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "main")
    _git(w, "merge", "--no-edit", "cote")

    repo = pygit2.Repository(str(w))
    resultat = significant_commits(repo, collect_refs(repo))

    fusion = repo.get(repo.head.target)
    assert str(fusion.id) in resultat, "le merge a disparu"
    for parent in fusion.parents:
        assert str(parent.id) in resultat, "un parent de merge a disparu"


def test_an_empty_repository_is_handled(tmp_path):
    """Aucune ref : pas de plantage, un ensemble vide."""
    w = tmp_path / "vide"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    repo = pygit2.Repository(str(w))
    assert significant_commits(repo, ()) == set()


def test_only_the_closest_merge_base_is_kept(tmp_path):
    """Un ancêtre commun n'est une merge-base que s'il est MAXIMAL.

    Vérifié par mutation : inverser l'inclusion dans `_merge_bases`
    passait inaperçu tant que les masques des ancêtres étaient
    IDENTIQUES — les deux formes sont alors équivalentes. Il faut donc
    des masques distincts, c'est-à-dire des branches qui ne partagent
    pas tout :

        base ─→ A ─→ {x, y}
          └────────→ z

    `base` est atteint par x, y ET z (masque 0b1111) ; `A` seulement par
    x et y (0b0111). `A` est la merge-base de x et y ; `base` celle de
    {x,y} et z. Inverser l'inclusion échange les deux.
    """
    from tortoisepy.core.significance import _analyse, _merge_bases

    w = tmp_path / "w"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )

    def oid_courant():
        return subprocess.run(
            ["git", "-C", str(w), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

    (w / "base.txt").write_text("b")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "base")
    base = oid_courant()

    (w / "A.txt").write_text("a")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "A")
    a = oid_courant()

    for nom in ("x", "y"):
        _git(w, "checkout", "-q", "-b", nom, a)
        (w / f"{nom}.txt").write_text(nom)
        _git(w, "add", ".")
        _git(w, "commit", "-q", "-m", nom)

    _git(w, "checkout", "-q", "-b", "z", base)
    (w / "z.txt").write_text("z")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "z")

    repo = pygit2.Repository(str(w))
    reach, _ = _analyse(repo, {r.target for r in collect_refs(repo)})

    assert reach[base] != reach[a], (
        "les masques doivent différer, sinon le test ne discrimine rien"
    )

    bases = _merge_bases(repo, reach)
    assert a in bases, "A est la merge-base de x et y"
    assert base in bases, "base est la merge-base de {x,y} et z"
