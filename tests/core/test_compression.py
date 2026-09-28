from tortoisepy.core.compression import compress_linear_segments
from tortoisepy.core.refs import collect_refs
from tortoisepy.core.significance import significant_commits


def _edges_for(repo_builder):
    repo = repo_builder.repo
    sig = significant_commits(repo, collect_refs(repo))
    return compress_linear_segments(repo, sig), sig


def test_long_chain_becomes_one_edge(repo_long_linear):
    """Mille commits entre deux nœuds : une seule arête."""
    edges, _ = _edges_for(repo_long_linear)
    long_edges = [e for e in edges if e.skipped_count > 100]
    assert len(long_edges) == 1
    assert long_edges[0].skipped_count == 999


def test_skipped_oids_are_preserved(repo_long_linear):
    """§4.2.1 : la compression est visuelle, les OID restent accessibles."""
    edges, _ = _edges_for(repo_long_linear)
    edge = max(edges, key=lambda e: e.skipped_count)
    assert len(edge.skipped) == edge.skipped_count
    assert len(set(edge.skipped)) == edge.skipped_count  # pas de doublon


def test_adjacent_significant_commits_skip_nothing(repo_merge):
    edges, _ = _edges_for(repo_merge)
    assert any(e.skipped_count == 0 for e in edges)


def test_edge_endpoints_are_significant(repo_diverged):
    edges, sig = _edges_for(repo_diverged)
    for edge in edges:
        assert edge.ancestor in sig
        assert edge.descendant in sig


def test_skipped_commits_are_not_significant(repo_long_linear):
    edges, sig = _edges_for(repo_long_linear)
    for edge in edges:
        for oid in edge.skipped:
            assert oid not in sig


def test_octopus_produces_edge_per_parent(repo_octopus):
    """Quatre parents, quatre arêtes entrantes — aucune perdue."""
    edges, _ = _edges_for(repo_octopus)
    incoming = [e for e in edges if e.descendant == repo_octopus.octopus_oid]
    assert len(incoming) == 4
