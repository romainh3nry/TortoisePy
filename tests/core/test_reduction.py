from tortoisepy.core.model import GraphEdge
from tortoisepy.core.reduction import reduce_transitive_edges


def edge(a: str, d: str) -> GraphEdge:
    return GraphEdge(ancestor=a, descendant=d, skipped=())


def test_removes_redundant_direct_edge():
    """A→B est redondante puisque A→C→B existe."""
    edges = (edge("A", "B"), edge("A", "C"), edge("C", "B"))
    result = reduce_transitive_edges(edges)
    pairs = {(e.ancestor, e.descendant) for e in result}
    assert ("A", "B") not in pairs
    assert ("A", "C") in pairs
    assert ("C", "B") in pairs


def test_keeps_all_edges_when_no_redundancy():
    edges = (edge("A", "B"), edge("C", "D"))
    assert len(reduce_transitive_edges(edges)) == 2


def test_keeps_diamond_edges():
    """Un losange n'a aucune arête redondante."""
    edges = (edge("A", "B"), edge("A", "C"), edge("B", "D"), edge("C", "D"))
    assert len(reduce_transitive_edges(edges)) == 4


def test_removes_edge_across_long_path():
    edges = (edge("A", "B"), edge("B", "C"), edge("C", "D"), edge("A", "D"))
    pairs = {(e.ancestor, e.descendant) for e in reduce_transitive_edges(edges)}
    assert ("A", "D") not in pairs
    assert len(pairs) == 3


def test_preserves_skipped_oids():
    """La réduction ne doit pas perdre l'information de compression."""
    edges = (GraphEdge("A", "B", ("x", "y")),)
    result = reduce_transitive_edges(edges)
    assert result[0].skipped == ("x", "y")


def test_empty_input():
    assert reduce_transitive_edges(()) == ()


def test_a_cycle_does_not_hang_and_keeps_its_edges():
    """Un DAG Git n'a pas de cycle, mais l'algorithme ne doit pas s'y perdre.

    Le tri topologique laisse les nœuds d'un cycle de côté : leur masque
    de descendants reste vide, donc les arêtes sont **conservées** plutôt
    que supprimées à tort. Vérifié identique à l'implémentation d'avant.
    """
    cycle = (edge("A", "B"), edge("B", "A"))
    assert len(reduce_transitive_edges(cycle)) == 2


def test_a_single_edge_survives():
    assert reduce_transitive_edges((edge("A", "B"),)) == (edge("A", "B"),)


def test_a_wide_graph_stays_fast():
    """Signalé par l'utilisateur : 16,8 s sur son dépôt `vti`.

    L'ancienne version reparcourait le graphe pour **chaque** arête —
    102 millions d'opérations de liste, mesurées au profileur. Le coût
    venait de la **largeur** : beaucoup de nœuds ayant plusieurs
    descendants, chacun déclenchant un parcours complet.

    Sans ce test, une régression repasserait inaperçue, comme celle-ci
    l'a fait pendant seize phases.
    """
    import time

    # Un graphe large : 300 « branches » partant d'un tronc commun et se
    # rejoignant, ce qui multiplie les ancêtres à plusieurs descendants.
    aretes = []
    for i in range(300):
        aretes.append(edge("racine", f"b{i}"))
        aretes.append(edge(f"b{i}", "jonction"))
    aretes.append(edge("racine", "jonction"))

    debut = time.perf_counter()
    resultat = reduce_transitive_edges(tuple(aretes))
    duree = time.perf_counter() - debut

    # L'arête directe racine → jonction est redondante : 300 chemins
    # indirects existent.
    assert edge("racine", "jonction") not in resultat
    assert duree < 1.0, f"{duree:.2f} s pour 300 branches — trop lent"


def test_the_result_matches_a_brute_force_reference():
    """Le résultat doit être **identique**, pas « assez proche ».

    Le rendu du graphe est validé visuellement (mémoire du projet) : une
    optimisation qui changerait les arêtes serait un défaut, pas une
    amélioration. On compare donc à une référence naïve, écrite pour être
    évidemment juste plutôt que rapide.
    """
    from collections import defaultdict

    aretes = tuple(
        [edge(f"n{i}", f"n{i + 1}") for i in range(30)]
        + [edge(f"n{i}", f"n{i + 3}") for i in range(0, 27, 2)]
        + [edge("n0", "n29"), edge("n5", "n20")]
    )

    def reference(edges):
        succ = defaultdict(set)
        for e in edges:
            succ[e.ancestor].add(e.descendant)

        def atteint(depart, cible, vus=None):
            vus = vus if vus is not None else set()
            for suivant in succ[depart]:
                if suivant == cible:
                    return True
                if suivant not in vus:
                    vus.add(suivant)
                    if atteint(suivant, cible, vus):
                        return True
            return False

        gardees = []
        for e in edges:
            autres = succ[e.ancestor] - {e.descendant}
            if not any(
                c == e.descendant or atteint(c, e.descendant) for c in autres
            ):
                gardees.append(e)
        return set(gardees)

    assert set(reduce_transitive_edges(aretes)) == reference(aretes)
