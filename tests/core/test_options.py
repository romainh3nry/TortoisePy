"""Filtrage des refs affichées.

Sur un dépôt professionnel réel, 413 des 710 refs étaient des tags de
version. Les masquer par défaut est un choix d'affichage — mais il doit
rester réversible, et ne jamais faire disparaître HEAD.
"""

from tortoisepy.core.graph import build_graph
from tortoisepy.core.model import Ref, RefType
from tortoisepy.core.options import GraphOptions


def ref(name: str, type_: RefType) -> Ref:
    return Ref(name, type_, "a" * 40)


def test_tags_are_hidden_by_default():
    assert GraphOptions().accepts(ref("v1.0", RefType.TAG)) is False


def test_branches_are_shown_by_default():
    options = GraphOptions()
    assert options.accepts(ref("master", RefType.LOCAL_BRANCH)) is True
    assert options.accepts(ref("origin/master", RefType.REMOTE_BRANCH)) is True


def test_head_is_always_kept():
    """Sans HEAD, le nœud courant n'est plus identifiable."""
    options = GraphOptions(
        show_local_branches=False,
        show_remote_branches=False,
        show_tags=False,
    )
    assert options.accepts(ref("HEAD", RefType.HEAD)) is True


def test_tags_can_be_requested():
    options = GraphOptions(show_tags=True)
    assert options.accepts(ref("v1.0", RefType.TAG)) is True


def test_remote_branches_can_be_hidden():
    options = GraphOptions(show_remote_branches=False)
    assert options.accepts(ref("origin/f", RefType.REMOTE_BRANCH)) is False
    assert options.accepts(ref("f", RefType.LOCAL_BRANCH)) is True


def test_filter_keeps_only_accepted_refs():
    refs = (
        ref("master", RefType.LOCAL_BRANCH),
        ref("v1.0", RefType.TAG),
        ref("origin/master", RefType.REMOTE_BRANCH),
    )
    kept = {r.name for r in GraphOptions().filter(refs)}
    assert kept == {"master", "origin/master"}


def test_options_are_frozen():
    import pytest

    options = GraphOptions()
    with pytest.raises(AttributeError):
        options.show_tags = True


def test_hiding_tags_reduces_the_graph(repo_tags):
    """Le filtrage agit sur le graphe construit, pas seulement le rendu."""
    with_tags = build_graph(repo_tags.repo, GraphOptions(show_tags=True))
    without = build_graph(repo_tags.repo, GraphOptions(show_tags=False))

    names_with = {r.name for n in with_tags.nodes for r in n.refs}
    names_without = {r.name for n in without.nodes for r in n.refs}

    assert "light" in names_with
    assert "light" not in names_without


def test_default_build_hides_tags(repo_tags):
    """`build_graph` sans options applique bien les valeurs par défaut."""
    graph = build_graph(repo_tags.repo)
    types = {r.type for n in graph.nodes for r in n.refs}
    assert RefType.TAG not in types


def test_head_survives_every_filter(repo_linear):
    graph = build_graph(
        repo_linear.repo,
        GraphOptions(
            show_local_branches=False,
            show_remote_branches=False,
            show_tags=False,
        ),
    )
    types = {r.type for n in graph.nodes for r in n.refs}
    assert RefType.HEAD in types
