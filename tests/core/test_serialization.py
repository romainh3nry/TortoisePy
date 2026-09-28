import json

from tortoisepy.core.graph import build_graph
from tortoisepy.core.serialization import graph_to_dict


def test_shape_matches_spec(repo_diverged):
    """Forme définie en §10.1."""
    data = graph_to_dict(build_graph(repo_diverged.repo))
    assert set(data) == {"nodes", "edges"}
    node = data["nodes"][0]
    assert set(node) == {"oid", "kind", "refs"}
    edge = data["edges"][0]
    assert set(edge) == {"ancestor", "descendant", "skipped"}


def test_is_json_serializable(repo_nested_merges):
    data = graph_to_dict(build_graph(repo_nested_merges.repo))
    assert json.loads(json.dumps(data)) == data


def test_edges_use_ancestor_descendant_not_from_to(repo_merge):
    """§4.2 : les noms du modèle traversent la sérialisation."""
    data = graph_to_dict(build_graph(repo_merge.repo))
    for edge in data["edges"]:
        assert "from" not in edge
        assert "to" not in edge


def test_skipped_is_a_count_not_the_full_list(repo_long_linear):
    """La sérialisation reste lisible : le décompte suffit ici."""
    data = graph_to_dict(build_graph(repo_long_linear.repo))
    assert any(isinstance(e["skipped"], int) and e["skipped"] > 100
               for e in data["edges"])
