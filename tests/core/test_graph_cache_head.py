"""Phase 22 : un checkout ne doit plus reconstruire tout le graphe.

Mesuré sur un dépôt réel de 713 refs : `build_graph` coûte **2185 ms**,
soit 80 % des 2,7 s que l'utilisateur subissait à chaque bascule de
branche. Le checkout git lui-même coûte 35 ms.

Or le graphe reconstruit est presque le même — vérifié :

    noeud 1fde63d4 : avant [main, HEAD]  -> apres [main]
    noeud 696ebd3a : avant [autre]       -> apres [autre, HEAD]
    aretes identiques : True

Seule la ref `HEAD` se déplace. Toute la topologie — parcours du DAG,
merge-bases, compression, réduction — est recalculée pour rien.

**Le piège** : en HEAD détachée, `HEAD` peut désigner un commit qu'aucune
branche ne porte, et il ajoute alors un nœud (mesuré : 1 -> 2). Une
optimisation qui l'ignorerait casserait justement le cas où ce repère
compte le plus.
"""

from __future__ import annotations

import subprocess

import pygit2
import pytest

from tortoisepy.core.graph import build_graph
from tortoisepy.core.graph_cache import GraphCache
from tortoisepy.core.model import RefType


def _git(chemin, *args):
    subprocess.run(
        ["git", "-C", str(chemin), *args],
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
            "PATH": "/usr/bin:/bin:/usr/local/bin",
        },
    )


@pytest.fixture
def depot(tmp_path):
    """Trois commits sur `main`, plus une branche `autre`."""
    w = tmp_path / "w"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    for nom in ("c1", "c2", "c3"):
        (w / f"{nom}.txt").write_text(nom)
        _git(w, "add", ".")
        _git(w, "commit", "-q", "-m", nom)
    _git(w, "checkout", "-q", "-b", "autre")
    (w / "d.txt").write_text("d")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "cote autre")
    _git(w, "checkout", "-q", "main")
    return w


def _head_node(graphe):
    """OID du nœud portant la ref HEAD, ou None."""
    for noeud in graphe.nodes:
        if any(r.type is RefType.HEAD for r in noeud.refs):
            return noeud.oid
    return None


def test_a_checkout_does_not_rebuild_the_graph(depot):
    """Le cœur de la phase : la reconstruction coûteuse est évitée."""
    cache = GraphCache()
    appels = []

    def build(repo):
        appels.append(1)
        return build_graph(repo)

    cache.get(pygit2.Repository(str(depot)), build)
    assert len(appels) == 1

    _git(depot, "checkout", "-q", "autre")
    cache.get(pygit2.Repository(str(depot)), build)

    assert len(appels) == 1, (
        "le graphe a été reconstruit alors que seule HEAD a bougé"
    )


def test_the_head_label_follows_the_current_branch(depot):
    """Éviter la reconstruction ne doit pas figer l'affichage.

    Sans ce test, le cache rendrait un graphe où `HEAD` resterait sur
    l'ancien nœud : plus rapide, mais faux — pire qu'un graphe lent.
    """
    cache = GraphCache()
    repo = pygit2.Repository(str(depot))
    avant = cache.get(repo, build_graph)
    oid_main = _head_node(avant)

    _git(depot, "checkout", "-q", "autre")
    apres = cache.get(pygit2.Repository(str(depot)), build_graph)
    oid_autre = _head_node(apres)

    assert oid_main is not None and oid_autre is not None
    assert oid_main != oid_autre, "la ref HEAD n'a pas suivi le checkout"

    repo2 = pygit2.Repository(str(depot))
    assert oid_autre == str(repo2.head.target)


def test_the_cached_graph_keeps_its_other_refs(depot):
    """Déplacer HEAD ne doit effacer aucune autre ref du nœud."""
    cache = GraphCache()
    cache.get(pygit2.Repository(str(depot)), build_graph)

    _git(depot, "checkout", "-q", "autre")
    graphe = cache.get(pygit2.Repository(str(depot)), build_graph)

    par_oid = {n.oid: {r.name for r in n.refs} for n in graphe.nodes}
    noms = set().union(*par_oid.values())
    assert "main" in noms and "autre" in noms
    assert "HEAD" in noms


def test_a_detached_head_still_rebuilds(depot):
    """Le piège mesuré : en détaché, HEAD AJOUTE un nœud (1 -> 2).

    Réutiliser le graphe en cache perdrait ce nœud — et c'est le cas où
    le repère compte le plus, puisque aucune branche ne le porte.
    """
    cache = GraphCache()
    cache.get(pygit2.Repository(str(depot)), build_graph)

    milieu = subprocess.run(
        ["git", "-C", str(depot), "rev-parse", "HEAD~1"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    _git(depot, "checkout", "-q", milieu)

    graphe = cache.get(pygit2.Repository(str(depot)), build_graph)
    assert _head_node(graphe) == milieu, (
        "le commit détaché doit porter HEAD, même s'il n'a aucune branche"
    )


def test_leaving_a_detached_head_is_correct(depot):
    """Le retour depuis le détaché ne doit pas laisser de nœud fantôme."""
    cache = GraphCache()
    milieu = subprocess.run(
        ["git", "-C", str(depot), "rev-parse", "HEAD~1"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    _git(depot, "checkout", "-q", milieu)
    cache.get(pygit2.Repository(str(depot)), build_graph)

    _git(depot, "checkout", "-q", "main")
    graphe = cache.get(pygit2.Repository(str(depot)), build_graph)

    repo = pygit2.Repository(str(depot))
    assert _head_node(graphe) == str(repo.head.target)


def test_a_real_ref_change_still_rebuilds(depot):
    """Créer une branche doit toujours reconstruire : la topologie change."""
    cache = GraphCache()
    appels = []

    def build(repo):
        appels.append(1)
        return build_graph(repo)

    cache.get(pygit2.Repository(str(depot)), build)
    _git(depot, "branch", "nouvelle")
    cache.get(pygit2.Repository(str(depot)), build)

    assert len(appels) == 2, "un changement de refs doit reconstruire"
