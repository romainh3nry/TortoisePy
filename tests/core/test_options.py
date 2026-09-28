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


def test_tags_are_shown_by_default():
    """Les tags étaient masqués ; mesuré, ils n'étaient pas la cause de
    l'encombrement (8281 -> 7988 nœuds seulement). C'étaient les jonctions."""
    assert GraphOptions().accepts(ref("v1.0", RefType.TAG)) is True


def test_junctions_are_hidden_by_default():
    """Mesuré sur un dépôt réel : 234 jonctions pour 283 refs."""
    assert GraphOptions().show_junctions is False


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


def test_tags_can_be_hidden():
    options = GraphOptions(show_tags=False)
    assert options.accepts(ref("v1.0", RefType.TAG)) is False


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
    assert kept == {"master", "v1.0", "origin/master"}

    without = GraphOptions(show_tags=False).filter(refs)
    assert {r.name for r in without} == {"master", "origin/master"}


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


def test_default_build_shows_tags(repo_tags):
    """`build_graph` sans options affiche les tags."""
    graph = build_graph(repo_tags.repo)
    types = {r.type for n in graph.nodes for r in n.refs}
    assert RefType.TAG in types


def test_default_build_hides_junctions(repo_diverged):
    """Seules les jonctions indispensables à la connexité sont gardées."""
    from tortoisepy.core.model import NodeKind

    graph = build_graph(repo_diverged.repo)
    junctions = [n for n in graph.nodes if n.kind is NodeKind.JUNCTION]
    # Sur deux branches divergentes, le merge-base est leur SEUL lien :
    # il est conservé, sinon le graphe se casserait en deux (§4.2).
    assert len(junctions) <= 1


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
