# tests/core/test_invariants.py
"""Invariants de §10.3, vérifiés sur tous les dépôts de référence."""

from collections import defaultdict

import pytest

from tortoisepy.core.graph import build_graph
from tortoisepy.core.options import GraphOptions

ALL_REPOS = [
    "repo_linear",
    "repo_diverged",
    "repo_merge",
    "repo_nested_merges",
    "repo_long_linear",
    "repo_two_merge_bases",
    "repo_octopus",
    "repo_multi_ref_commit",
    "repo_tags",
    "repo_remotes",
    "repo_detached_head",
    "repo_multiple_roots",
]


@pytest.fixture(params=ALL_REPOS)
def any_repo(request):
    return request.getfixturevalue(request.param)


def test_each_oid_appears_at_most_once(any_repo):
    graph = build_graph(any_repo.repo)
    oids = [n.oid for n in graph.nodes]
    assert len(oids) == len(set(oids))


def test_each_ref_belongs_to_exactly_one_node(any_repo):
    graph = build_graph(any_repo.repo)
    seen: dict[str, int] = defaultdict(int)
    for node in graph.nodes:
        for ref in node.refs:
            seen[f"{ref.type.value}:{ref.name}"] += 1
    assert all(count == 1 for count in seen.values())


def test_every_edge_connects_existing_nodes(any_repo):
    graph = build_graph(any_repo.repo)
    known = {n.oid for n in graph.nodes}
    for e in graph.edges:
        assert e.ancestor in known
        assert e.descendant in known


def test_no_self_loops(any_repo):
    graph = build_graph(any_repo.repo)
    assert all(e.ancestor != e.descendant for e in graph.edges)


def test_stash_nodes_have_single_outgoing_edge(any_repo):
    from tortoisepy.core.model import NodeKind
    graph = build_graph(any_repo.repo)
    for node in graph.nodes:
        if node.kind is NodeKind.STASH:
            incoming = [e for e in graph.edges if e.descendant == node.oid]
            assert len(incoming) == 1


def test_build_is_deterministic(any_repo):
    first = build_graph(any_repo.repo)
    second = build_graph(any_repo.repo)
    assert [n.oid for n in first.nodes] == [n.oid for n in second.nodes]


def test_multi_ref_commit_groups_all_refs(repo_multi_ref_commit):
    """§4.1 : branche + remote + tag annoté sur un seul nœud.

    Les tags sont masqués par défaut (§6.1) : ce test porte sur le
    regroupement, il demande donc explicitement à les voir.
    """
    graph = build_graph(
        repo_multi_ref_commit.repo, GraphOptions(show_tags=True)
    )
    node = graph.node(repo_multi_ref_commit.shared_oid)
    names = {r.name for r in node.refs}
    assert {"develop", "origin/develop", "v1.0"} <= names


def test_multiple_roots_produce_two_components(repo_multiple_roots):
    """§10.4 : deux historiques indépendants restent séparés.

    Les racines anonymes sont des jonctions, masquées par défaut (§6.1) :
    on vérifie donc que les deux HISTORIQUES sont visibles — par leurs
    refs — et qu'aucune arête ne les relie, plutôt que la présence d'un
    commit racine sans nom.
    """
    graph = build_graph(repo_multiple_roots.repo)

    names = {r.name for n in graph.nodes for r in n.refs}
    assert {"first", "second"} <= names

    from collections import defaultdict

    neighbours = defaultdict(set)
    for edge in graph.edges:
        neighbours[edge.ancestor].add(edge.descendant)
        neighbours[edge.descendant].add(edge.ancestor)

    start = next(
        n.oid for n in graph.nodes if any(r.name == "first" for r in n.refs)
    )
    reachable = {start}
    stack = [start]
    while stack:
        for neighbour in neighbours[stack.pop()]:
            if neighbour not in reachable:
                reachable.add(neighbour)
                stack.append(neighbour)

    second = next(
        n.oid for n in graph.nodes if any(r.name == "second" for r in n.refs)
    )
    assert second not in reachable, "les historiques doivent rester séparés"


def test_detached_head_shares_node_with_tag(repo_detached_head):
    """§4.1 : HEAD détaché sur un commit tagué rejoint son nœud.

    Les tags étant masqués par défaut, ce test les réactive : il vérifie
    le regroupement, pas le filtrage.
    """
    from tortoisepy.core.model import RefType
    graph = build_graph(
        repo_detached_head.repo, GraphOptions(show_tags=True)
    )
    node = graph.node(repo_detached_head.detached_oid)
    types = {r.type for r in node.refs}
    assert RefType.HEAD in types
    assert RefType.TAG in types


def test_stash_invariant_on_a_repository_that_has_stashes(repo_stashes):
    """§10.3 : « un stash n'a qu'une arête entrante ».

    `repo_stashes` est absente d'ALL_REPOS (elle expose un objet différent
    de RepoBuilder), donc l'invariant paramétré ne s'exécuterait sur AUCUN
    dépôt contenant un stash — il passerait à vide. Ce test le vérifie là
    où il a du sens.
    """
    from tortoisepy.core.model import NodeKind

    graph = build_graph(repo_stashes.repo)
    stash_nodes = [n for n in graph.nodes if n.kind is NodeKind.STASH]
    assert stash_nodes, "la fixture doit contenir au moins un stash"

    for node in stash_nodes:
        incoming = [e for e in graph.edges if e.descendant == node.oid]
        assert len(incoming) == 1, (
            f"{node.refs[0].name} a {len(incoming)} arêtes entrantes au lieu d'une"
        )
        outgoing = [e for e in graph.edges if e.ancestor == node.oid]
        assert not outgoing, "un stash ne doit rien avoir en aval"
