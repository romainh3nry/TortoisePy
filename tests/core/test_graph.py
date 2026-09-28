from pathlib import Path

from tortoisepy.core.graph import build_graph
from tortoisepy.core.options import GraphOptions
from tortoisepy.core.model import NodeKind


def test_diverged_graph_is_connected(repo_diverged):
    """Le test central : sans le merge-base, deux composantes séparées."""
    graph = build_graph(repo_diverged.repo)
    reachable = {graph.nodes[0].oid}
    changed = True
    while changed:
        changed = False
        for e in graph.edges:
            if e.ancestor in reachable and e.descendant not in reachable:
                reachable.add(e.descendant)
                changed = True
            elif e.descendant in reachable and e.ancestor not in reachable:
                reachable.add(e.ancestor)
                changed = True
    assert reachable == {n.oid for n in graph.nodes}


def test_merge_base_node_has_no_refs(repo_diverged):
    graph = build_graph(repo_diverged.repo)
    base = graph.node(repo_diverged.merge_base_expected)
    assert base is not None
    assert base.kind is NodeKind.JUNCTION or base.refs == ()


def test_ref_nodes_carry_their_refs(repo_diverged):
    graph = build_graph(repo_diverged.repo)
    tip = graph.node(repo_diverged.master_tip)
    assert any(r.name == "master" for r in tip.refs)


def test_each_oid_appears_once(repo_nested_merges):
    """§10.3 invariant."""
    graph = build_graph(repo_nested_merges.repo)
    oids = [n.oid for n in graph.nodes]
    assert len(oids) == len(set(oids))


def test_every_edge_connects_existing_nodes(repo_nested_merges):
    """§10.3 invariant."""
    graph = build_graph(repo_nested_merges.repo)
    known = {n.oid for n in graph.nodes}
    for e in graph.edges:
        assert e.ancestor in known
        assert e.descendant in known


def test_graph_is_acyclic(repo_nested_merges):
    """§10.3 invariant."""
    graph = build_graph(repo_nested_merges.repo)
    from collections import defaultdict
    succ = defaultdict(list)
    for e in graph.edges:
        succ[e.ancestor].append(e.descendant)

    state: dict[str, int] = {}

    def visit(node: str) -> bool:
        if state.get(node) == 1:
            return False
        if state.get(node) == 2:
            return True
        state[node] = 1
        for nxt in succ[node]:
            if not visit(nxt):
                return False
        state[node] = 2
        return True

    assert all(visit(n.oid) for n in graph.nodes)


def test_long_history_compresses_below_ten_nodes(repo_long_linear):
    graph = build_graph(repo_long_linear.repo)
    assert len(graph.nodes) < 10


def test_octopus_graph_keeps_four_incoming_edges(repo_octopus):
    """Les quatre branches d'un octopus restent distinctes.

    La fixture ne met une ref que sur le commit de merge : ses parents
    sont des jonctions, masquées par défaut (§6.1). On demande donc à les
    voir — c'est la topologie qu'on teste ici, pas le filtrage.

    Sur un octopus réel, dont les branches fusionnées existent encore, les
    quatre arêtes sont conservées sans cette option (vérifié).
    """
    graph = build_graph(repo_octopus.repo, GraphOptions(show_junctions=True))
    incoming = [e for e in graph.edges if e.descendant == repo_octopus.octopus_oid]
    assert len(incoming) == 4


def test_octopus_with_named_branches_keeps_its_edges(tmp_path):
    """Le cas réel : les branches fusionnées portent encore un nom."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from tests.fixtures.builder import RepoBuilder

    b = RepoBuilder(tmp_path / "octopus-nomme")
    base = b.commit("base")
    b.branch("main", base)
    parents = []
    for index in range(1, 5):
        oid = b.commit(f"p{index}", parents=[base])
        b.branch(f"feat{index}", oid)
        parents.append(oid)
    octopus = b.commit("octopus", parents=parents)
    b.branch("main", octopus)

    graph = build_graph(b.repo)
    incoming = [e for e in graph.edges if e.descendant == octopus]
    assert len(incoming) == 4, "les quatre branches doivent rester visibles"


def test_empty_repository_yields_empty_graph(tmp_path):
    import pygit2
    repo = pygit2.init_repository(str(tmp_path / "empty"))
    graph = build_graph(repo)
    assert graph.nodes == ()
    assert graph.edges == ()


def test_build_is_deterministic(repo_nested_merges):
    """§10.4 : deux exécutions donnent le même résultat."""
    first = build_graph(repo_nested_merges.repo)
    second = build_graph(repo_nested_merges.repo)
    assert [n.oid for n in first.nodes] == [n.oid for n in second.nodes]
    assert [(e.ancestor, e.descendant) for e in first.edges] == [
        (e.ancestor, e.descendant) for e in second.edges
    ]


def test_stash_edge_survives_junction_collapsing(repo_stashes):
    """Une arête de stash ne doit jamais pointer vers un nœud retiré.

    `collapse_trivial_junctions` peut supprimer le parent d'un stash. Le
    filtre qui rattache les stashes doit donc regarder les nœuds RÉELLEMENT
    présents, pas l'ensemble des commits significatifs d'avant la
    simplification — sinon l'arête devient orpheline et viole §10.3.
    Défaut rencontré sur un dépôt réel de 710 refs.
    """
    graph = build_graph(repo_stashes.repo)
    known = {n.oid for n in graph.nodes}
    orphans = [
        e for e in graph.edges
        if e.ancestor not in known or e.descendant not in known
    ]
    assert not orphans, f"{len(orphans)} arête(s) orpheline(s)"


def test_no_orphan_edges_on_a_branch_heavy_repository(tmp_path):
    """Beaucoup de branches et de merges : le cas qui a révélé le défaut."""
    import subprocess

    path = tmp_path / "heavy"
    path.mkdir()
    env = {
        "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
        "PATH": "/usr/bin:/bin:/usr/local/bin",
    }

    def git(*args):
        subprocess.run(["git", *args], cwd=path, env=env, capture_output=True)

    git("init", "-q", "-b", "master")
    (path / "f.txt").write_text("base\n")
    git("add", "."); git("commit", "-q", "-m", "base")

    for index in range(6):
        git("checkout", "-q", "-b", f"b{index}", "master")
        (path / f"b{index}.txt").write_text(f"{index}\n")
        git("add", "."); git("commit", "-q", "-m", f"b{index}")
        git("checkout", "-q", "master")
        git("merge", "-q", "--no-ff", "--no-edit", f"b{index}")

    (path / "f.txt").write_text("à stasher\n")
    git("stash", "-q")

    import pygit2
    graph = build_graph(pygit2.Repository(str(path)))
    known = {n.oid for n in graph.nodes}
    for edge in graph.edges:
        assert edge.ancestor in known
        assert edge.descendant in known
