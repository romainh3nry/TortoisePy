# tortoisePy — Plan d'implémentation, phase 2 : `layout/`

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Placer les nœuds du `DisplayGraph` en coordonnées 2D, de façon lisible
et déterministe, sans aucune dépendance à Qt.

**Architecture:** Sugiyama simplifié en quatre étapes séparées — rangs,
ordonnancement, composantes, coordonnées. Chaque étape est une fonction pure
prenant et rendant des structures immuables, testable isolément. Les dimensions
des nœuds viennent d'un protocole injectable, pas de Qt.

**Tech Stack:** Python 3.13, pytest. Aucune dépendance pygit2 ni PySide6 dans
`layout/`.

**Spec:** `docs/superpowers/specs/2026-09-11-tortoisepy-design.md` (§6.2, §10.4)

**Prérequis:** phase 1 terminée — `tortoisepy.core` fournit `DisplayGraph`,
`DisplayNode`, `GraphEdge`, `NodeKind`, `Ref`, `RefType`. 144 tests passent.

## Global Constraints

- **Python 3.13**, typage moderne (`str | None`).
- **`layout/` n'importe JAMAIS PySide6, ni pygit2, ni `tortoisepy.ui`.**
  Un test le vérifie (tâche 5). La dépendance à `core.model` est permise —
  c'est le modèle partagé.
- **Toutes les structures retournées sont `frozen=True`.**
- **Déterminisme absolu.** Aucune itération sur un `set` nu ni sur un `dict`
  non trié dans un chemin qui influence les coordonnées. Trier explicitement.
- **Convention d'axes :** `y` croît vers le **haut**. Un descendant a un `y`
  plus grand que son ancêtre. C'est l'inverse de la convention écran ; la
  conversion est le travail de `ui/`, pas de `layout/`.
- **Aucune commande `git`.** L'utilisateur gère son dépôt. Les plans contiennent
  parfois des étapes de commit : les ignorer.
- Messages de commit (si l'utilisateur commite) en anglais, préfixe
  conventionnel.

---

### Task 1: Modèle de placement et mesure des nœuds

**Files:**
- Create: `src/tortoisepy/layout/__init__.py`
- Create: `src/tortoisepy/layout/metrics.py`
- Test: `tests/layout/__init__.py`
- Test: `tests/layout/test_metrics.py`

**Interfaces:**
- Consumes: `DisplayNode`, `Ref` (phase 1)
- Produces: `Size`, `Placement`, `LayoutResult`, `NodeMeasurer` (Protocol),
  `MonospaceMeasurer`

**Pourquoi un protocole de mesure.** La largeur d'un nœud dépend de la police
de rendu, que seul Qt connaît. Mais `layout/` ne doit pas importer Qt. La
mesure est donc **injectée** : `layout/` définit le contrat, `ui/` fournira
plus tard une implémentation basée sur `QFontMetrics`. `MonospaceMeasurer` est
l'implémentation par défaut, suffisante pour les tests et pour une police à
chasse fixe — celle que la capture de référence utilise (§4.4).

- [ ] **Step 1: Écrire les tests**

```python
# tests/layout/test_metrics.py
import pytest

from tortoisepy.core.model import DisplayNode, NodeKind, Ref, RefType
from tortoisepy.layout.metrics import (
    LayoutResult,
    MonospaceMeasurer,
    Placement,
    Size,
)


def node(oid: str, *names: str) -> DisplayNode:
    refs = tuple(Ref(n, RefType.LOCAL_BRANCH, oid) for n in names)
    return DisplayNode(
        oid=oid,
        kind=NodeKind.REF if refs else NodeKind.JUNCTION,
        refs=refs,
    )


def test_size_is_frozen():
    s = Size(width=10.0, height=4.0)
    with pytest.raises(AttributeError):
        s.width = 99.0


def test_placement_exposes_its_bounds():
    p = Placement(oid="abc", x=10.0, y=20.0, size=Size(30.0, 8.0))
    assert p.left == 10.0
    assert p.right == 40.0
    assert p.bottom == 20.0
    assert p.top == 28.0


def test_single_ref_node_width_follows_name_length():
    m = MonospaceMeasurer()
    short = m.measure(node("a" * 40, "x"))
    long = m.measure(node("b" * 40, "a-very-long-branch-name"))
    assert long.width > short.width


def test_multi_ref_node_is_taller():
    m = MonospaceMeasurer()
    one = m.measure(node("a" * 40, "master"))
    three = m.measure(node("b" * 40, "master", "origin/master", "github/master"))
    assert three.height > one.height
    assert three.width >= one.width


def test_multi_ref_width_follows_longest_name():
    """Un nœud à trois refs est large comme sa ref la plus longue."""
    m = MonospaceMeasurer()
    got = m.measure(node("a" * 40, "x", "a-much-longer-name", "y"))
    expected = m.measure(node("b" * 40, "a-much-longer-name"))
    assert got.width == expected.width


def test_junction_node_is_labelled_by_short_oid():
    """§4.3 : les jonctions affichent leur OID court."""
    m = MonospaceMeasurer()
    size = m.measure(node("abcdef1234567890" + "0" * 24))
    assert size.width > 0
    assert size.height > 0


def test_measurement_is_deterministic():
    m = MonospaceMeasurer()
    n = node("a" * 40, "master", "origin/master")
    assert m.measure(n) == m.measure(n)


def test_layout_result_lookup():
    p = Placement(oid="abc", x=0.0, y=0.0, size=Size(10.0, 5.0))
    result = LayoutResult(placements=(p,), width=10.0, height=5.0)
    assert result.placement("abc") is p
    assert result.placement("inconnu") is None
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/layout/test_metrics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tortoisepy.layout'`

- [ ] **Step 3: Implémenter**

```python
# src/tortoisepy/layout/metrics.py
"""Dimensions des nœuds et structures de placement.

`layout/` ne connaît pas la police de rendu : la mesure est injectée via le
protocole `NodeMeasurer`. `ui/` en fournira une implémentation fondée sur
QFontMetrics ; `MonospaceMeasurer` suffit aux tests et à une police à chasse
fixe, celle qu'utilise la capture de référence (§4.4).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from tortoisepy.core.model import DisplayNode, Oid

SHORT_OID_LENGTH = 8
"""Longueur de l'étiquette d'un nœud de jonction (§4.3)."""


@dataclass(frozen=True)
class Size:
    width: float
    height: float


@dataclass(frozen=True)
class Placement:
    """Un nœud posé. `x`/`y` désignent son coin bas-gauche.

    `y` croît vers le haut : un descendant a un `y` supérieur à son ancêtre.
    La conversion vers la convention écran appartient à `ui/`.
    """

    oid: Oid
    x: float
    y: float
    size: Size

    @property
    def left(self) -> float:
        return self.x

    @property
    def right(self) -> float:
        return self.x + self.size.width

    @property
    def bottom(self) -> float:
        return self.y

    @property
    def top(self) -> float:
        return self.y + self.size.height


@dataclass(frozen=True)
class LayoutResult:
    placements: tuple[Placement, ...]
    width: float
    height: float

    def placement(self, oid: Oid) -> Placement | None:
        for p in self.placements:
            if p.oid == oid:
                return p
        return None


class NodeMeasurer(Protocol):
    """Contrat de mesure. `ui/` l'implémentera avec QFontMetrics."""

    def measure(self, node: DisplayNode) -> Size: ...


@dataclass(frozen=True)
class MonospaceMeasurer:
    """Mesure pour une police à chasse fixe.

    Les valeurs par défaut correspondent à une police ~13 px : elles servent
    de base cohérente, `ui/` les remplacera par les métriques réelles.
    """

    char_width: float = 8.0
    line_height: float = 18.0
    padding_x: float = 12.0
    padding_y: float = 6.0

    def measure(self, node: DisplayNode) -> Size:
        labels = [ref.name for ref in node.refs] or [node.oid[:SHORT_OID_LENGTH]]
        longest = max(len(label) for label in labels)
        return Size(
            width=longest * self.char_width + 2 * self.padding_x,
            height=len(labels) * self.line_height + 2 * self.padding_y,
        )
```

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/layout/test_metrics.py -v`
Expected: PASS, 8 tests.

- [ ] **Step 5: Signaler les fichiers prêts**

Ne commite pas. Liste les fichiers créés dans ton rapport.

---

### Task 2: Calcul des rangs

**Files:**
- Create: `src/tortoisepy/layout/ranking.py`
- Test: `tests/layout/test_ranking.py`

**Interfaces:**
- Consumes: `DisplayGraph`, `GraphEdge` (phase 1)
- Produces: `compute_ranks(graph) -> dict[Oid, int]`

Le rang d'un nœud est la **longueur du plus long chemin depuis une racine**
(§6.2 étape 1). Le plus long, pas le plus court : il garantit qu'un nœud est
toujours strictement au-dessus de tous ses ancêtres, y compris via un chemin
détourné.

- [ ] **Step 1: Écrire les tests**

```python
# tests/layout/test_ranking.py
from tortoisepy.core.model import (
    DisplayGraph,
    DisplayNode,
    GraphEdge,
    NodeKind,
)
from tortoisepy.layout.ranking import compute_ranks


def n(oid: str) -> DisplayNode:
    return DisplayNode(oid=oid, kind=NodeKind.JUNCTION, refs=())


def e(a: str, d: str) -> GraphEdge:
    return GraphEdge(ancestor=a, descendant=d, skipped=())


def graph(oids: list[str], edges: list[GraphEdge]) -> DisplayGraph:
    return DisplayGraph(nodes=tuple(n(o) for o in oids), edges=tuple(edges))


def test_single_node_is_rank_zero():
    assert compute_ranks(graph(["a"], [])) == {"a": 0}


def test_chain_increments_rank():
    ranks = compute_ranks(graph(["a", "b", "c"], [e("a", "b"), e("b", "c")]))
    assert ranks == {"a": 0, "b": 1, "c": 2}


def test_diverged_branches_share_a_rank():
    """Deux branches issues du même point sont au même niveau."""
    ranks = compute_ranks(graph(["base", "x", "y"], [e("base", "x"), e("base", "y")]))
    assert ranks["x"] == ranks["y"] == 1


def test_longest_path_wins_not_shortest():
    """a→d directement ET a→b→c→d : d doit être au rang 3, pas 1."""
    edges = [e("a", "b"), e("b", "c"), e("c", "d"), e("a", "d")]
    ranks = compute_ranks(graph(["a", "b", "c", "d"], edges))
    assert ranks["d"] == 3


def test_merge_sits_above_both_parents():
    edges = [e("base", "l"), e("base", "r"), e("l", "m"), e("r", "m")]
    ranks = compute_ranks(graph(["base", "l", "r", "m"], edges))
    assert ranks["m"] > ranks["l"]
    assert ranks["m"] > ranks["r"]


def test_every_edge_goes_up():
    """L'invariant central de §10.4."""
    edges = [e("a", "b"), e("a", "c"), e("b", "d"), e("c", "d"), e("d", "x")]
    g = graph(["a", "b", "c", "d", "x"], edges)
    ranks = compute_ranks(g)
    for edge in g.edges:
        assert ranks[edge.ancestor] < ranks[edge.descendant]


def test_disconnected_components_both_start_at_zero():
    edges = [e("a1", "a2"), e("b1", "b2")]
    ranks = compute_ranks(graph(["a1", "a2", "b1", "b2"], edges))
    assert ranks["a1"] == 0
    assert ranks["b1"] == 0


def test_isolated_node_is_rank_zero():
    ranks = compute_ranks(graph(["a", "b", "lone"], [e("a", "b")]))
    assert ranks["lone"] == 0


def test_empty_graph():
    assert compute_ranks(DisplayGraph(nodes=(), edges=())) == {}


def test_is_deterministic():
    edges = [e("a", "b"), e("a", "c"), e("b", "d"), e("c", "d")]
    g = graph(["a", "b", "c", "d"], edges)
    assert compute_ranks(g) == compute_ranks(g)
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/layout/test_ranking.py -v`
Expected: FAIL — module introuvable.

- [ ] **Step 3: Implémenter**

```python
# src/tortoisepy/layout/ranking.py
"""Rang de chaque nœud — §6.2 étape 1.

Rang = longueur du plus LONG chemin depuis une racine. Le plus court ne
conviendrait pas : avec les arêtes a→b→c→d et a→d, il placerait `d` juste
au-dessus de `a`, donc au même niveau que `b`, alors que `d` descend de `c`.
"""

from __future__ import annotations

from collections import defaultdict, deque

from tortoisepy.core.model import DisplayGraph, Oid


def compute_ranks(graph: DisplayGraph) -> dict[Oid, int]:
    """Rang de chaque nœud, les racines à 0.

    Tri topologique de Kahn. Le graphe est acyclique par construction
    (invariant vérifié en phase 1) ; un cycle laisserait des nœuds non
    traités, qui retombent alors au rang 0 plutôt que de boucler.
    """
    oids = [node.oid for node in graph.nodes]
    known = set(oids)

    successors: dict[Oid, list[Oid]] = defaultdict(list)
    indegree: dict[Oid, int] = {oid: 0 for oid in oids}

    for edge in graph.edges:
        if edge.ancestor not in known or edge.descendant not in known:
            continue
        successors[edge.ancestor].append(edge.descendant)
        indegree[edge.descendant] += 1

    ranks: dict[Oid, int] = {oid: 0 for oid in oids}
    remaining = dict(indegree)

    # sorted() : deux exécutions doivent donner le même résultat (§10.4)
    queue = deque(sorted(oid for oid in oids if remaining[oid] == 0))

    while queue:
        current = queue.popleft()
        for successor in sorted(successors[current]):
            if ranks[current] + 1 > ranks[successor]:
                ranks[successor] = ranks[current] + 1
            remaining[successor] -= 1
            if remaining[successor] == 0:
                queue.append(successor)

    return ranks
```

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/layout/test_ranking.py -v`
Expected: PASS, 10 tests.

- [ ] **Step 5: Signaler les fichiers prêts** — ne commite pas.

---

### Task 3: Composantes et ordonnancement

**Files:**
- Create: `src/tortoisepy/layout/ordering.py`
- Test: `tests/layout/test_ordering.py`

**Interfaces:**
- Consumes: `DisplayGraph`, `compute_ranks` (tâche 2)
- Produces: `find_components(graph) -> tuple[tuple[Oid, ...], ...]`,
  `order_within_ranks(graph, ranks) -> dict[int, tuple[Oid, ...]]`

Deux responsabilités liées : séparer les historiques indépendants (§10.4), et
ordonner les nœuds d'un même rang pour réduire les croisements d'arêtes
(§6.2 étape 2, heuristique du barycentre).

- [ ] **Step 1: Écrire les tests**

```python
# tests/layout/test_ordering.py
from tortoisepy.core.model import (
    DisplayGraph,
    DisplayNode,
    GraphEdge,
    NodeKind,
)
from tortoisepy.layout.ordering import find_components, order_within_ranks
from tortoisepy.layout.ranking import compute_ranks


def n(oid: str) -> DisplayNode:
    return DisplayNode(oid=oid, kind=NodeKind.JUNCTION, refs=())


def e(a: str, d: str) -> GraphEdge:
    return GraphEdge(ancestor=a, descendant=d, skipped=())


def graph(oids: list[str], edges: list[GraphEdge]) -> DisplayGraph:
    return DisplayGraph(nodes=tuple(n(o) for o in oids), edges=tuple(edges))


def test_connected_graph_is_one_component():
    g = graph(["a", "b", "c"], [e("a", "b"), e("b", "c")])
    assert len(find_components(g)) == 1


def test_two_histories_are_two_components():
    """§10.4 : les historiques indépendants restent séparés."""
    g = graph(["a1", "a2", "b1"], [e("a1", "a2")])
    components = find_components(g)
    assert len(components) == 2
    assert {frozenset(c) for c in components} == {
        frozenset({"a1", "a2"}),
        frozenset({"b1"}),
    }


def test_components_are_connected_through_shared_ancestor():
    """Deux branches divergentes partagent leur merge-base : une composante."""
    g = graph(["base", "x", "y"], [e("base", "x"), e("base", "y")])
    assert len(find_components(g)) == 1


def test_component_membership_is_sorted():
    """Déterminisme : l'ordre interne ne dépend pas du parcours."""
    g = graph(["c", "a", "b"], [e("a", "b"), e("b", "c")])
    assert find_components(g)[0] == ("a", "b", "c")


def test_components_are_deterministic():
    g = graph(["a1", "a2", "b1", "b2"], [e("a1", "a2"), e("b1", "b2")])
    assert find_components(g) == find_components(g)


def test_empty_graph_has_no_components():
    assert find_components(DisplayGraph(nodes=(), edges=())) == ()


def test_ordering_groups_by_rank():
    g = graph(["base", "x", "y"], [e("base", "x"), e("base", "y")])
    orders = order_within_ranks(g, compute_ranks(g))
    assert orders[0] == ("base",)
    assert set(orders[1]) == {"x", "y"}


def test_ordering_is_deterministic():
    g = graph(["base", "x", "y", "z"],
              [e("base", "x"), e("base", "y"), e("base", "z")])
    ranks = compute_ranks(g)
    assert order_within_ranks(g, ranks) == order_within_ranks(g, ranks)


def test_every_node_appears_exactly_once():
    g = graph(["a", "b", "c", "d"], [e("a", "b"), e("a", "c"), e("b", "d")])
    orders = order_within_ranks(g, compute_ranks(g))
    placed = [oid for rank in sorted(orders) for oid in orders[rank]]
    assert sorted(placed) == ["a", "b", "c", "d"]


def test_children_follow_their_parents_order():
    """Les enfants s'ordonnent comme leurs parents, pas alphabétiquement.

    Rang 0 trié : ("aaa", "bbb"). Leurs enfants sont nommés à contre-sens —
    "aaa" a pour enfant "zzz", "bbb" a pour enfant "mmm". Un tri
    alphabétique du rang 1 donnerait ("mmm", "zzz") et croiserait les deux
    arêtes ; le barycentre doit produire ("zzz", "mmm").
    """
    g = graph(["aaa", "bbb", "zzz", "mmm"],
              [e("aaa", "zzz"), e("bbb", "mmm")])
    orders = order_within_ranks(g, compute_ranks(g))

    assert list(orders[0]) == ["aaa", "bbb"]
    assert list(orders[1]) == ["zzz", "mmm"], (
        "l'enfant de 'aaa' doit précéder celui de 'bbb' : sinon les arêtes "
        "se croisent inutilement"
    )
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/layout/test_ordering.py -v`
Expected: FAIL — module introuvable.

- [ ] **Step 3: Implémenter**

```python
# src/tortoisepy/layout/ordering.py
"""Composantes connexes et ordre intra-rang — §6.2 étape 2, §10.4."""

from __future__ import annotations

from collections import defaultdict

from tortoisepy.core.model import DisplayGraph, Oid

BARYCENTRE_PASSES = 3
"""Passes de l'heuristique. Au-delà, le gain devient négligeable (§6.2)."""


def find_components(graph: DisplayGraph) -> tuple[tuple[Oid, ...], ...]:
    """Composantes connexes, en traitant les arêtes comme non orientées.

    Deux historiques sans ancêtre commun forment deux composantes, que le
    placement disposera côte à côte (§10.4).
    """
    oids = sorted(node.oid for node in graph.nodes)
    known = set(oids)

    neighbours: dict[Oid, set[Oid]] = defaultdict(set)
    for edge in graph.edges:
        if edge.ancestor in known and edge.descendant in known:
            neighbours[edge.ancestor].add(edge.descendant)
            neighbours[edge.descendant].add(edge.ancestor)

    seen: set[Oid] = set()
    components: list[tuple[Oid, ...]] = []

    for start in oids:  # ordre trié : déterminisme
        if start in seen:
            continue
        stack = [start]
        seen.add(start)
        members: list[Oid] = []
        while stack:
            current = stack.pop()
            members.append(current)
            for neighbour in sorted(neighbours[current]):
                if neighbour not in seen:
                    seen.add(neighbour)
                    stack.append(neighbour)
        components.append(tuple(sorted(members)))

    return tuple(components)


def order_within_ranks(
    graph: DisplayGraph, ranks: dict[Oid, int]
) -> dict[int, tuple[Oid, ...]]:
    """Ordre horizontal des nœuds de chaque rang.

    Heuristique du barycentre : un nœud se place à la moyenne des positions
    de ses voisins du rang précédent. Répétée quelques fois, elle réduit les
    croisements sans coûter cher. L'ordre initial est alphabétique, ce qui
    garantit le déterminisme exigé par §10.4.
    """
    by_rank: dict[int, list[Oid]] = defaultdict(list)
    for oid in sorted(ranks):
        by_rank[ranks[oid]].append(oid)

    known = set(ranks)
    ancestors: dict[Oid, list[Oid]] = defaultdict(list)
    for edge in graph.edges:
        if edge.ancestor in known and edge.descendant in known:
            ancestors[edge.descendant].append(edge.ancestor)

    for _ in range(BARYCENTRE_PASSES):
        for rank in sorted(by_rank):
            if rank == 0:
                continue
            previous = {oid: i for i, oid in enumerate(by_rank[rank - 1])}

            def barycentre(oid: Oid) -> tuple[float, str]:
                positions = [
                    previous[a] for a in ancestors[oid] if a in previous
                ]
                if not positions:
                    # Sans ancêtre au rang précédent, garder sa place :
                    # le nom départage, donc le résultat reste stable.
                    return (float("inf"), oid)
                return (sum(positions) / len(positions), oid)

            by_rank[rank].sort(key=barycentre)

    return {rank: tuple(oids) for rank, oids in by_rank.items()}
```

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/layout/test_ordering.py -v`
Expected: PASS, 10 tests.

- [ ] **Step 5: Signaler les fichiers prêts** — ne commite pas.

---

### Task 4: Placement en coordonnées

**Files:**
- Create: `src/tortoisepy/layout/engine.py`
- Test: `tests/layout/test_engine.py`

**Interfaces:**
- Consumes: tâches 1 à 3
- Produces: `layout_graph(graph, measurer=None) -> LayoutResult`

C'est l'assemblage : rangs → ordre → composantes → coordonnées réelles, en
tenant compte de la taille variable de chaque nœud (§6.2 étape 3).

- [ ] **Step 1: Écrire les tests**

```python
# tests/layout/test_engine.py
from tortoisepy.core.model import (
    DisplayGraph,
    DisplayNode,
    GraphEdge,
    NodeKind,
    Ref,
    RefType,
)
from tortoisepy.layout.engine import layout_graph


def n(oid: str, *names: str) -> DisplayNode:
    refs = tuple(Ref(x, RefType.LOCAL_BRANCH, oid) for x in names)
    return DisplayNode(
        oid=oid,
        kind=NodeKind.REF if refs else NodeKind.JUNCTION,
        refs=refs,
    )


def e(a: str, d: str) -> GraphEdge:
    return GraphEdge(ancestor=a, descendant=d, skipped=())


def test_empty_graph_yields_empty_layout():
    result = layout_graph(DisplayGraph(nodes=(), edges=()))
    assert result.placements == ()
    assert result.width == 0.0
    assert result.height == 0.0


def test_every_node_is_placed():
    g = DisplayGraph(
        nodes=(n("a", "master"), n("b", "dev"), n("c")),
        edges=(e("a", "b"), e("b", "c")),
    )
    result = layout_graph(g)
    assert {p.oid for p in result.placements} == {"a", "b", "c"}


def test_descendant_sits_above_ancestor():
    """L'invariant central de §10.4, avec y croissant vers le haut."""
    g = DisplayGraph(
        nodes=(n("a", "old"), n("b", "new")),
        edges=(e("a", "b"),),
    )
    result = layout_graph(g)
    assert result.placement("b").y > result.placement("a").y


def test_no_two_nodes_overlap():
    """§10.4 : aucun chevauchement."""
    g = DisplayGraph(
        nodes=(n("base"), n("x", "feature"), n("y", "other"),
               n("z", "third"), n("w", "fourth")),
        edges=(e("base", "x"), e("base", "y"), e("base", "z"), e("base", "w")),
    )
    result = layout_graph(g)
    placements = result.placements
    for i, p in enumerate(placements):
        for q in placements[i + 1:]:
            separated = (
                p.right <= q.left or q.right <= p.left
                or p.top <= q.bottom or q.top <= p.bottom
            )
            assert separated, f"{p.oid} chevauche {q.oid}"


def test_wider_node_gets_more_room():
    """Un nom long ne doit pas déborder sur son voisin."""
    g = DisplayGraph(
        nodes=(n("base"),
               n("x", "a-very-long-branch-name-indeed"),
               n("y", "s")),
        edges=(e("base", "x"), e("base", "y")),
    )
    result = layout_graph(g)
    px, py = result.placement("x"), result.placement("y")
    assert px.right <= py.left or py.right <= px.left


def test_disconnected_components_do_not_overlap():
    """§10.4 : historiques indépendants côte à côte."""
    g = DisplayGraph(
        nodes=(n("a1", "first"), n("a2", "first-tip"),
               n("b1", "second"), n("b2", "second-tip")),
        edges=(e("a1", "a2"), e("b1", "b2")),
    )
    result = layout_graph(g)
    a = [result.placement(o) for o in ("a1", "a2")]
    b = [result.placement(o) for o in ("b1", "b2")]
    a_right = max(p.right for p in a)
    b_left = min(p.left for p in b)
    b_right = max(p.right for p in b)
    a_left = min(p.left for p in a)
    assert a_right <= b_left or b_right <= a_left


def test_bounds_cover_every_placement():
    g = DisplayGraph(
        nodes=(n("a", "x"), n("b", "y")),
        edges=(e("a", "b"),),
    )
    result = layout_graph(g)
    assert result.width >= max(p.right for p in result.placements)
    assert result.height >= max(p.top for p in result.placements)


def test_layout_is_deterministic():
    """§10.4 : même dépôt → même layout."""
    g = DisplayGraph(
        nodes=(n("base"), n("x", "a"), n("y", "b"), n("m", "merge")),
        edges=(e("base", "x"), e("base", "y"), e("x", "m"), e("y", "m")),
    )
    first = layout_graph(g)
    second = layout_graph(g)
    assert first.placements == second.placements
    assert (first.width, first.height) == (second.width, second.height)


def test_all_edges_point_upward():
    g = DisplayGraph(
        nodes=(n("base"), n("l", "left"), n("r", "right"), n("m", "merge")),
        edges=(e("base", "l"), e("base", "r"), e("l", "m"), e("r", "m")),
    )
    result = layout_graph(g)
    for edge in g.edges:
        assert result.placement(edge.descendant).y > result.placement(edge.ancestor).y
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/layout/test_engine.py -v`
Expected: FAIL — module introuvable.

- [ ] **Step 3: Implémenter**

```python
# src/tortoisepy/layout/engine.py
"""Placement final — §6.2 étape 3.

Assemble rangs, ordre et composantes en coordonnées réelles, en tenant
compte de la taille propre à chaque nœud : un nœud à trois refs est plus
haut, un nom de branche long est plus large.
"""

from __future__ import annotations

from tortoisepy.core.model import DisplayGraph, DisplayNode, Oid
from tortoisepy.layout.metrics import (
    LayoutResult,
    MonospaceMeasurer,
    NodeMeasurer,
    Placement,
    Size,
)
from tortoisepy.layout.ordering import find_components, order_within_ranks
from tortoisepy.layout.ranking import compute_ranks

GAP_X = 40.0
"""Espace horizontal minimal entre deux nœuds d'un même rang."""

GAP_Y = 60.0
"""Espace vertical entre deux rangs, mesuré entre leurs bases."""

COMPONENT_GAP = 120.0
"""Écart entre deux historiques indépendants, plus large pour les distinguer."""


def layout_graph(
    graph: DisplayGraph, measurer: NodeMeasurer | None = None
) -> LayoutResult:
    """Place chaque nœud du graphe.

    `measurer` permet à `ui/` d'injecter les métriques réelles de sa police ;
    à défaut, une mesure monospace cohérente est utilisée.
    """
    if not graph.nodes:
        return LayoutResult(placements=(), width=0.0, height=0.0)

    measure = measurer or MonospaceMeasurer()
    sizes = {node.oid: measure.measure(node) for node in graph.nodes}

    ranks = compute_ranks(graph)
    orders = order_within_ranks(graph, ranks)
    components = find_components(graph)

    row_heights = _row_heights(orders, sizes)
    row_bottoms = _row_bottoms(orders, row_heights)

    placements: list[Placement] = []
    offset_x = 0.0

    for component in components:
        members = set(component)
        width = _place_component(
            members, orders, sizes, row_bottoms, offset_x, placements
        )
        offset_x += width + COMPONENT_GAP

    total_width = max((p.right for p in placements), default=0.0)
    total_height = max((p.top for p in placements), default=0.0)

    # Tri final : deux exécutions doivent produire la même séquence (§10.4).
    return LayoutResult(
        placements=tuple(sorted(placements, key=lambda p: p.oid)),
        width=total_width,
        height=total_height,
    )


def _row_heights(
    orders: dict[int, tuple[Oid, ...]], sizes: dict[Oid, Size]
) -> dict[int, float]:
    """Hauteur de chaque rang : celle de son nœud le plus haut."""
    return {
        rank: max((sizes[oid].height for oid in oids), default=0.0)
        for rank, oids in orders.items()
    }


def _row_bottoms(
    orders: dict[int, tuple[Oid, ...]], heights: dict[int, float]
) -> dict[int, float]:
    """Ordonnée de la base de chaque rang, du bas vers le haut."""
    bottoms: dict[int, float] = {}
    y = 0.0
    for rank in sorted(orders):
        bottoms[rank] = y
        y += heights[rank] + GAP_Y
    return bottoms


def _place_component(
    members: set[Oid],
    orders: dict[int, tuple[Oid, ...]],
    sizes: dict[Oid, Size],
    row_bottoms: dict[int, float],
    offset_x: float,
    out: list[Placement],
) -> float:
    """Pose les nœuds d'une composante. Retourne sa largeur."""
    width = 0.0

    for rank in sorted(orders):
        x = offset_x
        for oid in orders[rank]:
            if oid not in members:
                continue
            size = sizes[oid]
            out.append(Placement(oid=oid, x=x, y=row_bottoms[rank], size=size))
            x += size.width + GAP_X
        width = max(width, x - offset_x - GAP_X if x > offset_x else 0.0)

    return width
```

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/layout/test_engine.py -v`
Expected: PASS, 9 tests.

- [ ] **Step 5: Signaler les fichiers prêts** — ne commite pas.

---

### Task 5: Invariants sur dépôts réels et garde d'architecture

**Files:**
- Test: `tests/layout/test_invariants.py`
- Modify: `tests/test_architecture.py`

**Interfaces:**
- Consumes: `layout_graph` (tâche 4), `build_graph` (phase 1), les fixtures
- Produces: validation de §10.4 sur les douze dépôts de référence

Les tâches 2 à 4 testent sur des graphes fabriqués à la main. Ici, le layout
est confronté aux **vrais** graphes produits par la phase 1.

- [ ] **Step 1: Écrire les tests d'invariants**

```python
# tests/layout/test_invariants.py
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
```

- [ ] **Step 2: Étendre la garde d'architecture**

Remplacer entièrement `tests/test_architecture.py` :

```python
# tests/test_architecture.py
"""Gardes d'architecture : les couches ne remontent jamais vers l'UI (§5)."""

import ast
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "tortoisepy"

QT = ("PySide6", "PyQt6", "PyQt5")
UI = ("tortoisepy.ui",)


def _imports_of(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def _offenders(package: str, forbidden: tuple[str, ...]) -> list[str]:
    found: list[str] = []
    for path in (SRC / package).rglob("*.py"):
        for name in _imports_of(path):
            if any(name.startswith(f) for f in forbidden):
                found.append(f"{package}/{path.name} importe {name}")
    return found


def test_core_never_imports_qt_or_ui():
    offenders = _offenders("core", QT + UI + ("tortoisepy.layout",))
    assert not offenders, "core/ doit rester indépendant : " + "; ".join(offenders)


def test_layout_never_imports_qt_or_ui():
    """layout/ ne connaît ni la police de rendu ni Git : la mesure est injectée."""
    offenders = _offenders("layout", QT + UI)
    assert not offenders, "layout/ doit rester indépendant : " + "; ".join(offenders)


def test_layout_never_imports_pygit2():
    """layout/ travaille sur le modèle, jamais sur le dépôt."""
    offenders = _offenders("layout", ("pygit2",))
    assert not offenders, "layout/ ne doit pas dépendre de pygit2 : " + "; ".join(offenders)
```

- [ ] **Step 3: Exécuter**

Run: `.venv/bin/pytest tests/layout/ tests/test_architecture.py -v`
Expected: PASS. Cinq invariants × douze dépôts, plus le test des stashes et
les trois gardes.

- [ ] **Step 4: Suite complète**

Run: `.venv/bin/pytest tests/ -q`
Expected: tous les tests passent, phase 1 comprise (144 avant cette phase).

- [ ] **Step 5: Signaler les fichiers prêts** — ne commite pas. Liste les
fichiers créés ou modifiés dans ton rapport, avec le décompte final des tests.

---

## Fin de phase 2

À ce stade :

- chaque nœud d'un vrai dépôt reçoit des coordonnées ;
- les invariants de §10.4 sont vérifiés sur douze topologies réelles ;
- `layout/` ne dépend ni de Qt, ni de pygit2 — vérifié par trois gardes ;
- la mesure des nœuds est injectable, prête à recevoir `QFontMetrics`.

**Ce que cette phase ne fait pas**, et qui reste à traiter :

- **Le routage des arêtes.** Les arêtes sont pour l'instant des segments
  implicites entre deux points ; leur tracé est du ressort de `ui/` (§4.4 :
  courbes simples, pas de routage orthogonal).
- **La stabilité locale** (§10.4) — objectif v1.1 assumé.

**Phases suivantes :**

- **Phase 3 — `core/operations.py` + `state.py`** : opérations Git,
  `OperationResult`, `RepositoryState`.
- **Phase 4 — `ui/`** : fenêtre, QGraphicsView, menu contextuel, mini-carte,
  surveillance de `.git`.
- **Phase 5 — `cli.py`** : point d'entrée `tgraph`.
