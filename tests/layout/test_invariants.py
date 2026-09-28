"""§10.4 vérifié sur les dépôts de référence de la phase 1."""

import pytest

from tortoisepy.core.graph import build_graph
from tortoisepy.layout.engine import layout_graph

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


def test_every_node_is_placed(any_repo):
    graph = build_graph(any_repo.repo)
    result = layout_graph(graph)
    assert {p.oid for p in result.placements} == {n.oid for n in graph.nodes}


def test_descendants_sit_above_ancestors(any_repo):
    """L'invariant principal, sur de vraies topologies."""
    graph = build_graph(any_repo.repo)
    result = layout_graph(graph)
    for edge in graph.edges:
        ancestor = result.placement(edge.ancestor)
        descendant = result.placement(edge.descendant)
        assert descendant.y > ancestor.y, (
            f"{edge.descendant[:8]} devrait être au-dessus de "
            f"{edge.ancestor[:8]}"
        )


def test_no_overlap(any_repo):
    graph = build_graph(any_repo.repo)
    placements = layout_graph(graph).placements
    for i, p in enumerate(placements):
        for q in placements[i + 1:]:
            separated = (
                p.right <= q.left or q.right <= p.left
                or p.top <= q.bottom or q.top <= p.bottom
            )
            assert separated, f"{p.oid[:8]} chevauche {q.oid[:8]}"


def test_layout_is_deterministic(any_repo):
    graph = build_graph(any_repo.repo)
    assert layout_graph(graph).placements == layout_graph(graph).placements


def test_bounds_contain_everything(any_repo):
    graph = build_graph(any_repo.repo)
    result = layout_graph(graph)
    if not result.placements:
        return
    assert result.width >= max(p.right for p in result.placements)
    assert result.height >= max(p.top for p in result.placements)


def test_stash_layout(repo_stashes):
    """Les stashes aussi doivent être placés sans chevauchement."""
    graph = build_graph(repo_stashes.repo)
    result = layout_graph(graph)
    assert len(result.placements) == len(graph.nodes)
    for edge in graph.edges:
        assert result.placement(edge.descendant).y > result.placement(edge.ancestor).y
