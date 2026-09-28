from tortoisepy.core.model import NodeKind, RefType
from tortoisepy.core.stashes import collect_stashes


def test_finds_both_stashes(repo_stashes):
    result = collect_stashes(repo_stashes.repo)
    assert len(result) == 2


def test_stash_node_is_typed_as_stash(repo_stashes):
    node, _ = collect_stashes(repo_stashes.repo)[0]
    assert node.kind is NodeKind.STASH
    assert node.refs[0].type is RefType.STASH


def test_stash_has_exactly_one_outgoing_edge(repo_stashes):
    """§10.3 invariant : un stash n'a qu'une arête."""
    for node, edge in collect_stashes(repo_stashes.repo):
        assert edge.descendant == node.oid


def test_stash_edge_points_to_first_parent_only(repo_stashes):
    """Un stash a 2-3 parents ; les artificiels créeraient des arêtes parasites."""
    import pygit2
    repo = repo_stashes.repo
    for node, edge in collect_stashes(repo):
        commit = repo.get(pygit2.Oid(hex=node.oid))
        assert len(commit.parents) >= 2  # confirme le cas
        assert edge.ancestor == str(commit.parents[0].id)


def test_repository_without_stash(repo_linear):
    assert collect_stashes(repo_linear.repo) == ()
