"""Rechercher une branche par mot-clé, pour la centrer dans le graphe.

Demandé par l'utilisateur : « rechercher une branche et centrer dessus
rapidement ; si plusieurs branches ont le même mot-clé, on navigue entre
elles à chaque appui sur Entrée ».

La fonction vit dans `core/` : elle ne dépend ni de Qt ni de l'affichage,
et `tests/test_architecture.py` interdit l'inverse.
"""

from __future__ import annotations

from tortoisepy.core.model import DisplayGraph, DisplayNode, NodeKind, Ref, RefType
from tortoisepy.core.search import matching_branches


def _noeud(oid: str, *refs: tuple[str, RefType]) -> DisplayNode:
    return DisplayNode(
        oid=oid,
        kind=NodeKind.REF,
        refs=tuple(Ref(nom, type_, oid) for nom, type_ in refs),
    )


def _graphe(*noeuds) -> DisplayGraph:
    return DisplayGraph(nodes=tuple(noeuds), edges=())


def test_an_exact_name_is_found():
    graphe = _graphe(
        _noeud("a" * 40, ("main", RefType.LOCAL_BRANCH)),
        _noeud("b" * 40, ("develop", RefType.LOCAL_BRANCH)),
    )
    assert matching_branches(graphe, "develop") == ("b" * 40,)


def test_a_partial_keyword_matches():
    """« rechercher par mot-clé » : pas besoin du nom complet."""
    graphe = _graphe(
        _noeud("a" * 40, ("feature/login", RefType.LOCAL_BRANCH)),
        _noeud("b" * 40, ("fix-login-bug", RefType.LOCAL_BRANCH)),
        _noeud("c" * 40, ("main", RefType.LOCAL_BRANCH)),
    )
    assert matching_branches(graphe, "login") == ("a" * 40, "b" * 40)


def test_the_search_ignores_case():
    graphe = _graphe(_noeud("a" * 40, ("Feature-X", RefType.LOCAL_BRANCH)))
    assert matching_branches(graphe, "feature") == ("a" * 40,)
    assert matching_branches(graphe, "FEATURE") == ("a" * 40,)


def test_remote_branches_are_searched_too():
    """Une branche distante est une cible de navigation légitime."""
    graphe = _graphe(
        _noeud("a" * 40, ("origin/hotfix", RefType.REMOTE_BRANCH)),
    )
    assert matching_branches(graphe, "hotfix") == ("a" * 40,)


def test_tags_and_stashes_are_not_branches():
    """La recherche porte sur les BRANCHES : inclure les tags rendrait
    la navigation imprévisible sur un dépôt qui en compte des centaines."""
    graphe = _graphe(
        _noeud("a" * 40, ("v1.0-release", RefType.TAG)),
        _noeud("b" * 40, ("stash@{0}", RefType.STASH)),
        _noeud("c" * 40, ("release-1.0", RefType.LOCAL_BRANCH)),
    )
    assert matching_branches(graphe, "release") == ("c" * 40,)


def test_one_node_carrying_several_matches_appears_once():
    """Un nœud portant `login` et `origin/login` est UNE destination.

    Sans déduplication, Entrée semblerait ne rien faire : on
    « naviguerait » vers le nœud déjà centré.
    """
    graphe = _graphe(
        _noeud(
            "a" * 40,
            ("login", RefType.LOCAL_BRANCH),
            ("origin/login", RefType.REMOTE_BRANCH),
        ),
    )
    assert matching_branches(graphe, "login") == ("a" * 40,)


def test_the_order_is_stable():
    """Naviguer en boucle exige un ordre constant d'un appel à l'autre."""
    graphe = _graphe(
        _noeud("c" * 40, ("zeta", RefType.LOCAL_BRANCH)),
        _noeud("a" * 40, ("alpha", RefType.LOCAL_BRANCH)),
        _noeud("b" * 40, ("beta", RefType.LOCAL_BRANCH)),
    )
    premier = matching_branches(graphe, "a")
    assert premier == matching_branches(graphe, "a")
    assert len(premier) == 3


def test_no_match_gives_nothing():
    graphe = _graphe(_noeud("a" * 40, ("main", RefType.LOCAL_BRANCH)))
    assert matching_branches(graphe, "absente") == ()


def test_an_empty_pattern_gives_nothing():
    """Un champ vide n'est pas une recherche de tout."""
    graphe = _graphe(_noeud("a" * 40, ("main", RefType.LOCAL_BRANCH)))
    assert matching_branches(graphe, "") == ()
    assert matching_branches(graphe, "   ") == ()


def test_an_empty_graph_is_handled():
    assert matching_branches(_graphe(), "main") == ()
    assert matching_branches(None, "main") == ()
