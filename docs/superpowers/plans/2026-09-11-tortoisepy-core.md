# tortoisePy — Plan d'implémentation, phase 1 : `core/`

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construire le modèle de graphe Git de tortoisePy — DAG réel, compression
visuelle, arêtes réduites — validé sur quinze dépôts de référence, sans aucune
dépendance à Qt.

**Architecture:** Pipeline en cinq étapes (§6.1 de la spec) : collecte des refs →
marquage des commits significatifs → compression des segments linéaires →
réduction transitive → rattachement des stashes. Le DAG Git réel est conservé
intégralement ; seul le rendu masquera les commits compressés. Chaque étape est
une fonction pure testable isolément.

**Tech Stack:** Python 3.13, pygit2 (liaison libgit2), pytest. Aucune dépendance
PySide6 dans cette phase.

**Spec:** `docs/superpowers/specs/2026-09-11-tortoisepy-design.md`

## Global Constraints

- **Python 3.13**, typage moderne (`str | None`, pas `Optional[str]`).
- **`core/` n'importe jamais PySide6**, ni aucun module `ui.*` ou `layout.*`.
  Un test automatisé le vérifie (tâche 12).
- **Noms :** projet `tortoisePy`, package `tortoisepy`, commande `tgraph`.
- **Arêtes :** champs nommés `ancestor` / `descendant`, **jamais** `from` / `to`
  (§4.2). `from` est en outre un mot-clé Python.
- **Parents de commits : toujours itérés, jamais indexés en dur.** Les merges
  octopus ont plus de deux parents (vérifié : quatre).
- **Merge-bases : jamais les API pygit2.** Vérifié sur pygit2 1.20.0 :
  `merge_base`, `merge_base_many` et `merge_base_octopus` retournent toutes un
  **seul** OID, alors qu'un dépôt à merges croisés en a deux. Les jonctions se
  détectent par **parcours du DAG avec marquage par pointe**, puis sélection des
  ancêtres communs maximaux (§6.1 de la spec).
- **Stashes : premier parent seulement.** Les parents 2 et 3 sont artificiels.
- **Tags annotés : toujours déréférencés** (`peel`) avant regroupement.
- **Tous les dataclasses du modèle sont `frozen=True`.**
- Messages de commit en anglais, préfixe conventionnel (`feat:`, `test:`,
  `chore:`).

---

### Task 1: Squelette du projet et vérification de l'API pygit2

**Files:**
- Create: `pyproject.toml`
- Create: `src/tortoisepy/__init__.py`
- Create: `src/tortoisepy/core/__init__.py`
- Create: `tests/__init__.py`
- Test: `tests/test_environment.py`

**Interfaces:**
- Consumes: rien (première tâche)
- Produces: package `tortoisepy` installable en mode éditable ; confirmation
  écrite des noms exacts de l'API pygit2 utilisés par les tâches suivantes.

**Pourquoi cette tâche existe :** la spec suppose l'existence de
`merge_base_many` ou équivalent, sans que ce soit vérifié — pygit2 n'était pas
installé au moment de la rédaction. Les tâches 5 et 6 en dépendent
entièrement. On vérifie avant de construire dessus.

- [ ] **Step 1: Créer `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "tortoisepy"
version = "0.1.0"
description = "TortoiseGit Revision Graph pour macOS"
requires-python = ">=3.13"
dependencies = ["pygit2>=1.15"]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[project.scripts]
tgraph = "tortoisepy.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Créer les packages vides**

```bash
mkdir -p src/tortoisepy/core tests
touch src/tortoisepy/__init__.py src/tortoisepy/core/__init__.py tests/__init__.py
```

- [ ] **Step 3: Créer l'environnement virtuel et installer**

```bash
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -e ".[dev]"
```

Si l'installation de pygit2 échoue (compilation de libgit2), installer d'abord
libgit2 via Homebrew : `brew install libgit2`, puis réessayer.

- [ ] **Step 4: Écrire le test de vérification d'API**

Ce test documente l'API réellement disponible. Il échouera si pygit2 change de
surface dans une version future — c'est voulu.

```python
# tests/test_environment.py
import pygit2


def test_pygit2_importable():
    assert pygit2.LIBGIT2_VERSION


def test_repository_has_required_methods(tmp_path):
    """Les méthodes dont dépendent les tâches 4 à 9.

    Testées sur une INSTANCE : `references` est une propriété, absente de la
    classe. La tester sur `pygit2.Repository` donnerait un faux négatif.
    """
    repo = pygit2.init_repository(str(tmp_path / "probe"))
    required = [
        "descendant_of",
        "walk",
        "references",
        "revparse_single",
        "listall_stashes",
    ]
    missing = [n for n in required if not hasattr(repo, n)]
    assert not missing, f"API pygit2 manquante : {missing}"


def test_no_pygit2_api_enumerates_all_merge_bases():
    """Vérifie la limite qui impose le parcours du DAG en tâche 6.

    Aucune API pygit2 ne retourne TOUS les merge-bases : merge_base,
    merge_base_many et merge_base_octopus retournent un OID unique.
    Si une version future expose une forme « all », ce test échoue — et
    c'est le signal pour reconsidérer l'algorithme de la tâche 6.
    """
    list_apis = [n for n in ("merge_bases", "merge_bases_many")
                 if hasattr(pygit2.Repository, n)]
    assert not list_apis, (
        f"pygit2 expose maintenant {list_apis} : réexaminer le parcours "
        "du DAG de la tâche 6, qui n'est peut-être plus nécessaire"
    )
    single = [n for n in ("merge_base", "merge_base_many", "merge_base_octopus")
              if hasattr(pygit2.Repository, n)]
    print(f"\nAPI merge-base (OID unique) : {single}")


def test_discover_repository_returns_none_when_absent(tmp_path):
    """Vérifié sur pygit2 1.20.0 : retourne None, ne lève pas.

    Une version antérieure de la spec §8 affirmait l'inverse. Le code
    testera `is None`, avec un try/except en ceinture et bretelles.
    """
    result = pygit2.discover_repository(str(tmp_path))
    assert result is None, (
        f"discover_repository retourne {result!r} au lieu de None — "
        "réexaminer la gestion d'erreur de la CLI"
    )
```

- [ ] **Step 5: Exécuter et consigner le résultat**

Run: `.venv/bin/pytest tests/test_environment.py -v -s`
Expected: PASS. **Noter la sortie de `test_merge_base_all_is_available`** — le
nom d'API qu'elle affiche est celui à utiliser en tâche 6. Si
`test_discover_repository_raises_when_absent` échoue, corriger §8 de la spec
avant de continuer.

- [ ] **Step 6: Créer `.gitignore` et commiter**

```bash
cat >> .gitignore <<'EOF'
.venv/
EOF
git add pyproject.toml src tests .gitignore
git commit -m "chore: scaffold package and verify pygit2 API surface"
```

---

### Task 2: Modèle de données

**Files:**
- Create: `src/tortoisepy/core/model.py`
- Test: `tests/core/test_model.py`

**Interfaces:**
- Consumes: rien
- Produces: `Oid` (alias `str`), `RefType`, `Ref`, `NodeKind`, `DisplayNode`,
  `GraphEdge`, `DisplayGraph`. Toutes les tâches suivantes en dépendent.
  `GraphEdge` expose la propriété `skipped_count`; `DisplayGraph` expose
  `node(oid) -> DisplayNode | None`.

- [ ] **Step 1: Écrire les tests du modèle**

```python
# tests/core/test_model.py
import pytest

from tortoisepy.core.model import (
    DisplayGraph,
    DisplayNode,
    GraphEdge,
    NodeKind,
    Ref,
    RefType,
)


def test_ref_is_frozen():
    ref = Ref(name="master", type=RefType.LOCAL_BRANCH, target="abc123")
    with pytest.raises(AttributeError):
        ref.name = "autre"


def test_edge_uses_ancestor_descendant_naming():
    """La spec §4.2 impose ces noms : ni from/to, ni source/target."""
    edge = GraphEdge(ancestor="old", descendant="new", skipped=())
    assert edge.ancestor == "old"
    assert edge.descendant == "new"
    assert not hasattr(edge, "source")
    assert not hasattr(edge, "target")


def test_edge_skipped_holds_ordered_oids():
    """§4.2.1 : la compression est visuelle, les OID sautés sont conservés."""
    edge = GraphEdge(ancestor="a", descendant="d", skipped=("b", "c"))
    assert edge.skipped == ("b", "c")
    assert edge.skipped_count == 2


def test_edge_with_no_skipped_commits():
    edge = GraphEdge(ancestor="a", descendant="b", skipped=())
    assert edge.skipped_count == 0


def test_display_node_groups_several_refs():
    """§4.1 : plusieurs refs sur un même commit forment un seul nœud."""
    node = DisplayNode(
        oid="abc123",
        kind=NodeKind.REF,
        refs=(
            Ref("origin/master", RefType.REMOTE_BRANCH, "abc123"),
            Ref("master", RefType.LOCAL_BRANCH, "abc123"),
        ),
    )
    assert len(node.refs) == 2


def test_junction_node_has_no_refs():
    """§4.1 catégorie 2 : les merge-bases sont des nœuds sans ref."""
    node = DisplayNode(oid="def456", kind=NodeKind.JUNCTION, refs=())
    assert node.refs == ()
    assert node.kind is NodeKind.JUNCTION


def test_graph_lookup_by_oid():
    node = DisplayNode(oid="abc123", kind=NodeKind.JUNCTION, refs=())
    graph = DisplayGraph(nodes=(node,), edges=())
    assert graph.node("abc123") is node
    assert graph.node("inconnu") is None
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/core/test_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tortoisepy.core.model'`

- [ ] **Step 3: Écrire le modèle**

```python
# src/tortoisepy/core/model.py
"""Modèle du graphe affiché.

Voir §4 de la spec. Trois niveaux distincts :
  - le DAG Git réel (commits et parents), manipulé par graph.py ;
  - les refs, collectées par refs.py ;
  - le graphe affiché (DisplayNode / GraphEdge), défini ici.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

Oid = str
"""OID de commit sous forme hexadécimale. Alias pour la lisibilité."""


class RefType(Enum):
    LOCAL_BRANCH = "local_branch"
    REMOTE_BRANCH = "remote_branch"
    TAG = "tag"
    HEAD = "head"
    STASH = "stash"


class NodeKind(Enum):
    REF = "ref"
    """Nœud portant au moins une ref."""

    JUNCTION = "junction"
    """Point de jonction topologique sans ref : merge-base, racine, merge."""

    STASH = "stash"
    """Stash, rattaché hors du calcul topologique (§4.1)."""


@dataclass(frozen=True)
class Ref:
    name: str
    type: RefType
    target: Oid
    """OID du commit, tags annotés déjà déréférencés."""


@dataclass(frozen=True)
class DisplayNode:
    oid: Oid
    kind: NodeKind
    refs: tuple[Ref, ...]

    @property
    def is_junction(self) -> bool:
        return self.kind is NodeKind.JUNCTION


@dataclass(frozen=True)
class GraphEdge:
    """Arête du graphe compressé.

    Les champs sont nommés ancestor/descendant et non from/to : le modèle
    exprime une relation Git, pas une direction de dessin. Le sens de la
    flèche est une décision du rendu (§4.2).
    """

    ancestor: Oid
    descendant: Oid
    skipped: tuple[Oid, ...]
    """OID des commits compressés, du plus ancien au plus récent (§4.2.1)."""

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)


@dataclass(frozen=True)
class DisplayGraph:
    nodes: tuple[DisplayNode, ...]
    edges: tuple[GraphEdge, ...]

    def node(self, oid: Oid) -> DisplayNode | None:
        for node in self.nodes:
            if node.oid == oid:
                return node
        return None
```

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/core/test_model.py -v`
Expected: PASS, 7 tests.

- [ ] **Step 5: Commiter**

```bash
mkdir -p tests/core && touch tests/core/__init__.py
git add src/tortoisepy/core/model.py tests/core/
git commit -m "feat: add display graph data model"
```

---

### Task 3: Fixtures — dépôts de référence 1 à 5

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/fixtures/builder.py`
- Test: `tests/fixtures/test_builder.py`

**Interfaces:**
- Consumes: rien
- Produces: `RepoBuilder` (constructeur de dépôts de test) et les fixtures
  pytest `repo_linear`, `repo_diverged`, `repo_merge`, `repo_nested_merges`,
  `repo_long_linear`. Les tâches 4 à 11 les consomment.

**Pourquoi un builder :** créer des commits via l'API pygit2 brute demande une
douzaine de lignes par commit (arbre, index, signature). Répété sur quinze
dépôts, c'est illisible. Le builder réduit un dépôt à quelques appels.

- [ ] **Step 1: Écrire le builder**

```python
# tests/fixtures/builder.py
"""Construction de dépôts Git de test.

Utilise pygit2 directement plutôt que des sous-processus git : plus rapide,
et cohérent avec ce que le code testé manipule.
"""

from __future__ import annotations

from pathlib import Path

import pygit2


class RepoBuilder:
    """Construit un dépôt de test. Chaque méthode retourne self (chaînable)."""

    def __init__(self, path: Path):
        self.repo = pygit2.init_repository(str(path), bare=False, initial_head="master")
        self.signature = pygit2.Signature("Test", "test@example.com", 0, 0)
        self._counter = 0

    def commit(self, message: str, parents: list[str] | None = None) -> str:
        """Crée un commit avec un contenu de fichier unique. Retourne son OID.

        Les commits sont créés **détachés** (`ref=None`), puis la branche
        courante est déplacée explicitement. C'est nécessaire pour les
        racines multiples : écrire un commit sans parent sur une branche
        qui en a déjà une fait échouer libgit2 avec « current tip is not
        the first parent » (vérifié).

        `parents=None` enchaîne sur HEAD ; `parents=[]` crée une racine.
        """
        self._counter += 1
        blob = self.repo.create_blob(f"content {self._counter}\n".encode())
        builder = self.repo.TreeBuilder()
        builder.insert(f"file{self._counter}.txt", blob, pygit2.GIT_FILEMODE_BLOB)
        tree = builder.write()

        chain_from_head = parents is None
        if chain_from_head:
            try:
                parents = [str(self.repo.head.target)]
            except (pygit2.GitError, KeyError):
                parents = []

        oid = self.repo.create_commit(
            None,  # commit détaché : la ref est posée ensuite
            self.signature,
            self.signature,
            message,
            tree,
            [pygit2.Oid(hex=p) if isinstance(p, str) else p for p in parents],
        )

        if chain_from_head:
            self._advance_head(oid)

        return str(oid)

    def _advance_head(self, oid) -> None:
        """Fait pointer la branche courante sur `oid`, en la créant au besoin."""
        try:
            name = self.repo.head.name  # ex. "refs/heads/master"
            self.repo.references[name].set_target(oid)
        except (pygit2.GitError, KeyError):
            # Premier commit : la branche n'existe pas encore.
            self.repo.create_reference("refs/heads/master", oid)

    def branch(self, name: str, oid: str | None = None) -> RepoBuilder:
        """Crée la branche, ou la déplace si elle existe déjà.

        `master` existe dès le premier `commit()` sans parents explicites :
        sans ce `force`, toute fixture qui repositionne `master` échoue avec
        `AlreadyExistsError` (vérifié).
        """
        target = oid or str(self.repo.head.target)
        target_oid = pygit2.Oid(hex=target) if isinstance(target, str) else target
        ref_name = f"refs/heads/{name}"

        if ref_name in self.repo.references:
            # set_target fonctionne même sur la branche courante, là où
            # create_branch(force=True) refuse : « cannot force update
            # branch as it is the current HEAD » (vérifié).
            self.repo.references[ref_name].set_target(target_oid)
        else:
            self.repo.create_branch(name, self.repo.get(target_oid))
        return self

    def checkout(self, name: str) -> RepoBuilder:
        self.repo.checkout(f"refs/heads/{name}")
        return self

    def tag_lightweight(self, name: str, oid: str) -> RepoBuilder:
        self.repo.create_reference(f"refs/tags/{name}", oid)
        return self

    def tag_annotated(self, name: str, oid: str) -> RepoBuilder:
        self.repo.create_tag(
            name, oid, pygit2.GIT_OBJECT_COMMIT, self.signature, f"tag {name}"
        )
        return self

    def remote_ref(self, remote: str, branch: str, oid: str) -> RepoBuilder:
        """Crée une ref de suivi distant sans réseau."""
        self.repo.create_reference(f"refs/remotes/{remote}/{branch}", oid)
        return self
```

- [ ] **Step 2: Écrire les fixtures 1 à 5**

```python
# tests/conftest.py
"""Dépôts de référence, §10.2 de la spec."""

from __future__ import annotations

import pygit2
import pytest

from tests.fixtures.builder import RepoBuilder


@pytest.fixture
def repo_linear(tmp_path):
    """1. Branche unique, quatre commits."""
    b = RepoBuilder(tmp_path / "linear")
    for name in ("A", "B", "C", "D"):
        b.commit(name)
    return b


@pytest.fixture
def repo_diverged(tmp_path):
    """2. Deux branches divergentes — le cas du merge-base (§4.2).

    A ─ B ─ C ─ D        master
             \\
              X ─ Y ─ Z  feature

    Ni master ni feature n'est ancêtre de l'autre. Le merge-base est C.
    """
    b = RepoBuilder(tmp_path / "diverged")
    a = b.commit("A")
    bb = b.commit("B")
    c = b.commit("C")
    d = b.commit("D")
    b.branch("feature", c)
    b.checkout("feature")
    x = b.commit("X", parents=[c])
    y = b.commit("Y", parents=[x])
    z = b.commit("Z", parents=[y])
    b.merge_base_expected = c
    b.master_tip = d
    b.feature_tip = z
    return b


@pytest.fixture
def repo_merge(tmp_path):
    """3. Un merge simple.

    Les branches sont repositionnées explicitement : `commit(parents=[...])`
    n'avance aucune ref, donc sans ces appels le commit de merge n'aurait
    aucune ref et resterait invisible du graphe (vérifié).
    """
    b = RepoBuilder(tmp_path / "merge")
    a = b.commit("A")
    left = b.commit("left", parents=[a])
    right = b.commit("right", parents=[a])
    merge = b.commit("merge", parents=[left, right])
    b.branch("side", right)
    b.branch("master", merge)
    b.merge_oid = merge
    b.left_oid = left
    b.right_oid = right
    return b


@pytest.fixture
def repo_nested_merges(tmp_path):
    """4. Merges imbriqués."""
    b = RepoBuilder(tmp_path / "nested")
    root = b.commit("root")
    a1 = b.commit("a1", parents=[root])
    b1 = b.commit("b1", parents=[root])
    m1 = b.commit("m1", parents=[a1, b1])
    c1 = b.commit("c1", parents=[root])
    m2 = b.commit("m2", parents=[m1, c1])
    b.branch("master", m2)
    b.final_merge = m2
    return b


@pytest.fixture
def repo_long_linear(tmp_path):
    """5. Mille commits sans ref intermédiaire (compression)."""
    b = RepoBuilder(tmp_path / "long")
    first = b.commit("first")
    previous = first
    for i in range(1000):
        previous = b.commit(f"c{i}", parents=[previous])
    b.branch("tip", previous)
    b.first_oid = first
    b.tip_oid = previous
    return b
```

- [ ] **Step 3: Écrire le test des fixtures**

Les fixtures sont du code : si elles construisent la mauvaise topologie, tous
les tests suivants valident un mensonge.

```python
# tests/fixtures/test_builder.py
import pygit2


def test_linear_has_four_commits(repo_linear):
    commits = list(repo_linear.repo.walk(repo_linear.repo.head.target))
    assert len(commits) == 4


def test_diverged_branches_are_not_ancestors(repo_diverged):
    """Le cœur du problème de §4.2, vérifié sur la fixture."""
    repo = repo_diverged.repo
    master = pygit2.Oid(hex=repo_diverged.master_tip)
    feature = pygit2.Oid(hex=repo_diverged.feature_tip)
    assert not repo.descendant_of(master, feature)
    assert not repo.descendant_of(feature, master)


def test_diverged_merge_base_is_c(repo_diverged):
    repo = repo_diverged.repo
    base = repo.merge_base(
        pygit2.Oid(hex=repo_diverged.master_tip),
        pygit2.Oid(hex=repo_diverged.feature_tip),
    )
    assert str(base) == repo_diverged.merge_base_expected


def test_merge_commit_has_two_parents(repo_merge):
    commit = repo_merge.repo.get(repo_merge.merge_oid)
    assert len(commit.parents) == 2


def test_long_linear_has_1001_commits(repo_long_linear):
    commits = list(repo_long_linear.repo.walk(pygit2.Oid(hex=repo_long_linear.tip_oid)))
    assert len(commits) == 1001
```

- [ ] **Step 4: Exécuter**

Run: `.venv/bin/pytest tests/fixtures/ -v`
Expected: PASS, 5 tests. Si `test_diverged_branches_are_not_ancestors` échoue,
la fixture ne construit pas la topologie voulue — corriger avant de continuer,
car les tâches 5 et 6 en dépendent.

- [ ] **Step 5: Commiter**

```bash
touch tests/fixtures/__init__.py
git add tests/conftest.py tests/fixtures/
git commit -m "test: add repository builder and fixtures 1-5"
```

---

### Task 4: Collecte des refs

**Files:**
- Create: `src/tortoisepy/core/refs.py`
- Test: `tests/core/test_refs.py`

**Interfaces:**
- Consumes: `Ref`, `RefType` (tâche 2) ; fixtures (tâche 3)
- Produces: `collect_refs(repo) -> tuple[Ref, ...]` et
  `group_refs_by_oid(refs) -> dict[Oid, tuple[Ref, ...]]`

- [ ] **Step 1: Écrire les tests**

```python
# tests/core/test_refs.py
from tortoisepy.core.model import RefType
from tortoisepy.core.refs import collect_refs, group_refs_by_oid


def test_collects_local_branch(repo_linear):
    refs = collect_refs(repo_linear.repo)
    names = {r.name for r in refs if r.type is RefType.LOCAL_BRANCH}
    assert "master" in names


def test_collects_head(repo_linear):
    refs = collect_refs(repo_linear.repo)
    heads = [r for r in refs if r.type is RefType.HEAD]
    assert len(heads) == 1


def test_collects_both_branches_when_diverged(repo_diverged):
    refs = collect_refs(repo_diverged.repo)
    names = {r.name for r in refs if r.type is RefType.LOCAL_BRANCH}
    assert {"master", "feature"} <= names


def test_lightweight_tag_is_collected(repo_linear):
    oid = str(repo_linear.repo.head.target)
    repo_linear.tag_lightweight("v1.0", oid)
    refs = collect_refs(repo_linear.repo)
    tags = [r for r in refs if r.type is RefType.TAG]
    assert [t.name for t in tags] == ["v1.0"]
    assert tags[0].target == oid


def test_annotated_tag_is_peeled_to_commit(repo_linear):
    """§4.1 : un tag annoté est un objet `tag`, pas un `commit`.

    Sans déréférencement, target serait l'OID de l'objet tag, qui
    n'apparaît nulle part dans le DAG — le nœud serait orphelin.
    """
    oid = str(repo_linear.repo.head.target)
    repo_linear.tag_annotated("v2.0", oid)
    refs = collect_refs(repo_linear.repo)
    tag = next(r for r in refs if r.name == "v2.0")
    assert tag.target == oid


def test_remote_branch_is_typed_correctly(repo_linear):
    oid = str(repo_linear.repo.head.target)
    repo_linear.remote_ref("origin", "master", oid)
    refs = collect_refs(repo_linear.repo)
    remotes = [r for r in refs if r.type is RefType.REMOTE_BRANCH]
    assert [r.name for r in remotes] == ["origin/master"]


def test_group_by_oid_merges_refs_on_same_commit(repo_linear):
    """§4.1 : plusieurs refs sur un commit forment un seul groupe."""
    oid = str(repo_linear.repo.head.target)
    repo_linear.tag_lightweight("v1.0", oid)
    repo_linear.remote_ref("origin", "master", oid)
    grouped = group_refs_by_oid(collect_refs(repo_linear.repo))
    assert len(grouped[oid]) >= 3  # master, HEAD, v1.0, origin/master


def test_empty_repository_yields_no_refs(tmp_path):
    import pygit2
    repo = pygit2.init_repository(str(tmp_path / "empty"))
    assert collect_refs(repo) == ()
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/core/test_refs.py -v`
Expected: FAIL — module introuvable.

- [ ] **Step 3: Implémenter**

```python
# src/tortoisepy/core/refs.py
"""Collecte et typage des refs Git. Voir §6.1 étape 1."""

from __future__ import annotations

from collections import defaultdict

import pygit2

from tortoisepy.core.model import Oid, Ref, RefType


def _peel_to_commit(repo: pygit2.Repository, ref) -> Oid | None:
    """Résout une ref vers l'OID de son commit.

    Un tag annoté pointe sur un objet `tag`, pas sur un `commit` : sans
    déréférencement, l'OID obtenu n'existe pas dans le DAG (§4.1).
    """
    try:
        commit = repo.get(ref.target).peel(pygit2.Commit)
        return str(commit.id)
    except (pygit2.GitError, AttributeError, TypeError):
        return None


def collect_refs(repo: pygit2.Repository) -> tuple[Ref, ...]:
    """Toutes les refs du dépôt, tags annotés déréférencés.

    Les stashes sont exclus : ils sont traités à part (§6.1 étape 5).
    """
    refs: list[Ref] = []

    for name in repo.references:
        if name.startswith("refs/stash"):
            continue
        ref = repo.references[name]
        oid = _peel_to_commit(repo, ref)
        if oid is None:
            continue

        if name.startswith("refs/heads/"):
            refs.append(Ref(name[len("refs/heads/"):], RefType.LOCAL_BRANCH, oid))
        elif name.startswith("refs/remotes/"):
            refs.append(Ref(name[len("refs/remotes/"):], RefType.REMOTE_BRANCH, oid))
        elif name.startswith("refs/tags/"):
            refs.append(Ref(name[len("refs/tags/"):], RefType.TAG, oid))

    head_oid = _head_oid(repo)
    if head_oid is not None:
        refs.append(Ref("HEAD", RefType.HEAD, head_oid))

    return tuple(refs)


def _head_oid(repo: pygit2.Repository) -> Oid | None:
    try:
        return str(repo.head.target)
    except (pygit2.GitError, KeyError):
        return None  # dépôt sans commit, ou HEAD non résolvable


def group_refs_by_oid(refs: tuple[Ref, ...]) -> dict[Oid, tuple[Ref, ...]]:
    """Regroupe les refs partageant un même commit (§4.1)."""
    grouped: dict[Oid, list[Ref]] = defaultdict(list)
    for ref in refs:
        grouped[ref.target].append(ref)
    return {oid: tuple(rs) for oid, rs in grouped.items()}
```

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/core/test_refs.py -v`
Expected: PASS, 8 tests.

- [ ] **Step 5: Commiter**

```bash
git add src/tortoisepy/core/refs.py tests/core/test_refs.py
git commit -m "feat: collect and type Git refs, peeling annotated tags"
```

---

### Task 5: Fixtures — dépôts 11 et 12 (merge-bases multiples, octopus)

**Files:**
- Modify: `tests/conftest.py`
- Test: `tests/fixtures/test_hard_cases.py`

**Interfaces:**
- Consumes: `RepoBuilder` (tâche 3)
- Produces: fixtures `repo_two_merge_bases`, `repo_octopus`

**Pourquoi ces deux fixtures avant l'algorithme :** ce sont les cas qui font
échouer une implémentation naïve. Les écrire d'abord garantit que la tâche 6 est
développée contre eux, et non corrigée après coup.

- [ ] **Step 1: Ajouter les fixtures**

```python
# à ajouter dans tests/conftest.py

@pytest.fixture
def repo_two_merge_bases(tmp_path):
    """11. Merges croisés : DEUX merge-bases entre A et B.

    Vérifié en ligne de commande : `git merge-base -a` retourne deux OID
    là où `git merge-base` n'en retourne qu'un. Une implémentation
    utilisant la forme singulière rate une jonction.
    """
    b = RepoBuilder(tmp_path / "twobases")
    root = b.commit("root")
    a1 = b.commit("a1", parents=[root])
    b1 = b.commit("b1", parents=[root])
    # Merges croisés : chacun fusionne l'autre branche
    x = b.commit("x", parents=[a1, b1])
    y = b.commit("y", parents=[b1, a1])
    b.branch("A", x)
    b.branch("B", y)
    b.tip_a = x
    b.tip_b = y
    b.expected_base_count = 2
    return b


@pytest.fixture
def repo_octopus(tmp_path):
    """12. Merge octopus : un commit à quatre parents.

    Vérifié : `git merge b1 b2 b3` produit un commit à quatre parents.
    Tout code indexant parents[0] et parents[1] est faux ici.
    """
    b = RepoBuilder(tmp_path / "octopus")
    base = b.commit("base")
    p1 = b.commit("p1", parents=[base])
    p2 = b.commit("p2", parents=[base])
    p3 = b.commit("p3", parents=[base])
    p4 = b.commit("p4", parents=[base])
    octopus = b.commit("octopus", parents=[p1, p2, p3, p4])
    b.branch("master", octopus)
    b.octopus_oid = octopus
    return b
```

- [ ] **Step 2: Écrire les tests des fixtures**

```python
# tests/fixtures/test_hard_cases.py
import pygit2


def _git_merge_base_all(repo_path: str, a: str, b: str) -> set[str]:
    """Vérité terrain : `git merge-base -a`, qui énumère TOUTES les bases."""
    import subprocess
    out = subprocess.run(
        ["git", "merge-base", "-a", a, b],
        cwd=repo_path, capture_output=True, text=True, check=True,
    ).stdout.split()
    return set(out)


def test_two_merge_bases_really_exist(repo_two_merge_bases):
    """Si ce test échoue, la fixture ne reproduit pas le cas visé."""
    bases = _git_merge_base_all(
        repo_two_merge_bases.repo.workdir,
        repo_two_merge_bases.tip_a,
        repo_two_merge_bases.tip_b,
    )
    assert len(bases) == repo_two_merge_bases.expected_base_count


def test_pygit2_apis_cannot_enumerate_all_bases(repo_two_merge_bases):
    """Documente la limite qui impose le parcours du DAG en tâche 6.

    Vérifié sur pygit2 1.20.0 : les trois API retournent un OID unique là
    où le dépôt a deux merge-bases.
    """
    repo = repo_two_merge_bases.repo
    a = pygit2.Oid(hex=repo_two_merge_bases.tip_a)
    b = pygit2.Oid(hex=repo_two_merge_bases.tip_b)

    truth = _git_merge_base_all(
        repo.workdir, repo_two_merge_bases.tip_a, repo_two_merge_bases.tip_b
    )
    assert len(truth) == 2

    for name in ("merge_base", "merge_base_many", "merge_base_octopus"):
        api = getattr(repo, name, None)
        if api is None:
            continue
        result = api(a, b) if name == "merge_base" else api([a, b])
        assert isinstance(result, pygit2.Oid), (
            f"{name} retourne maintenant autre chose qu'un OID unique : "
            "réexaminer si le parcours du DAG reste nécessaire"
        )


def test_octopus_has_four_parents(repo_octopus):
    commit = repo_octopus.repo.get(repo_octopus.octopus_oid)
    assert len(commit.parents) == 4
```

- [ ] **Step 3: Exécuter**

Run: `.venv/bin/pytest tests/fixtures/test_hard_cases.py -v`
Expected: PASS, 3 tests. Si `test_two_merge_bases_really_exist` trouve un seul
merge-base, la topologie de la fixture est mauvaise — la corriger avant la
tâche 6, sinon le cas critique n'est pas couvert.

- [ ] **Step 4: Commiter**

```bash
git add tests/conftest.py tests/fixtures/test_hard_cases.py
git commit -m "test: add fixtures for multiple merge-bases and octopus merge"
```

---

### Task 6: Marquage des commits significatifs

**Files:**
- Create: `src/tortoisepy/core/significance.py`
- Test: `tests/core/test_significance.py`

**Interfaces:**
- Consumes: `collect_refs` (tâche 4), fixtures (tâches 3 et 5)
- Produces: `significant_commits(repo, refs) -> set[Oid]`

**C'est l'étape la plus risquée du projet** (§6.1 étape 2). Elle décide quels
commits deviennent visibles ; une erreur ici produit un graphe faux que rien
en aval ne rattrapera.

> **⚠ Tâche terminée — le code ci-dessous est dépassé.** L'implémentation a
> depuis été optimisée : les fonctions `_reachability` et `_merges_and_roots`
> décrites plus bas lançaient un parcours du DAG **par pointe de ref**, soit
> 44 s de construction sur 200 branches (redondance de facteur 101). Elles sont
> remplacées par `_walk_once` et `_analyse`, qui font **un seul** parcours
> alimenté par `walker.push()` : 0,66 s, pour un résultat identique.
>
> Référence : `src/tortoisepy/core/significance.py` et §12.1 de la spec.

- [ ] **Step 1: Écrire les tests**

```python
# tests/core/test_significance.py
from tortoisepy.core.refs import collect_refs
from tortoisepy.core.significance import significant_commits


def test_ref_tips_are_significant(repo_diverged):
    refs = collect_refs(repo_diverged.repo)
    result = significant_commits(repo_diverged.repo, refs)
    assert repo_diverged.master_tip in result
    assert repo_diverged.feature_tip in result


def test_merge_base_is_significant(repo_diverged):
    """Le cas central de §4.2 : sans C, deux composantes déconnectées."""
    refs = collect_refs(repo_diverged.repo)
    result = significant_commits(repo_diverged.repo, refs)
    assert repo_diverged.merge_base_expected in result


def test_intermediate_commits_are_not_significant(repo_long_linear):
    """Mille commits sans ref ne doivent pas devenir significatifs."""
    refs = collect_refs(repo_long_linear.repo)
    result = significant_commits(repo_long_linear.repo, refs)
    assert len(result) < 10


def test_root_is_significant(repo_linear):
    refs = collect_refs(repo_linear.repo)
    result = significant_commits(repo_linear.repo, refs)
    walker = list(repo_linear.repo.walk(repo_linear.repo.head.target))
    root = str(walker[-1].id)
    assert root in result


def test_both_merge_bases_are_significant(repo_two_merge_bases):
    """Le test décisif de cette tâche.

    Toute implémentation reposant sur une API merge-base de pygit2 échoue
    ici : elles retournent un seul OID là où le dépôt en a deux. Seul le
    parcours du DAG avec marquage par pointe les trouve tous.

    La vérité terrain vient de `git merge-base -a`, pas de pygit2.
    """
    import subprocess

    repo = repo_two_merge_bases.repo
    truth = set(
        subprocess.run(
            ["git", "merge-base", "-a",
             repo_two_merge_bases.tip_a, repo_two_merge_bases.tip_b],
            cwd=repo.workdir, capture_output=True, text=True, check=True,
        ).stdout.split()
    )
    assert len(truth) == 2, "la fixture ne produit pas deux merge-bases"

    result = significant_commits(repo, collect_refs(repo))
    for base in truth:
        assert base in result, f"merge-base {base[:7]} manquant"


def test_octopus_merge_is_significant(repo_octopus):
    """Fixture 12 : quatre parents, aucun indexé en dur."""
    refs = collect_refs(repo_octopus.repo)
    result = significant_commits(repo_octopus.repo, refs)
    assert repo_octopus.octopus_oid in result


def test_empty_repository_yields_nothing(tmp_path):
    import pygit2
    repo = pygit2.init_repository(str(tmp_path / "empty"))
    assert significant_commits(repo, ()) == set()
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/core/test_significance.py -v`
Expected: FAIL — module introuvable.

- [ ] **Step 3: Implémenter**

Utiliser le nom d'API merge-base confirmé en tâche 1 step 5.

```python
# src/tortoisepy/core/significance.py
"""Marquage des commits significatifs — §6.1 étape 2.

Intention (le contrat, indépendant de l'algorithme) :

    Conserver l'ensemble minimal de commits préservant la connectivité
    topologique entre les refs. Deux refs reliées dans le DAG Git doivent
    le rester dans le graphe compressé, et tout point où l'histoire
    diverge ou converge doit rester visible.
"""

from __future__ import annotations

from collections import defaultdict

import pygit2

from tortoisepy.core.model import Oid, Ref


def _reachability(
    repo: pygit2.Repository, tips: set[Oid]
) -> dict[Oid, frozenset[Oid]]:
    """Pour chaque commit, l'ensemble des pointes qui l'atteignent.

    Un parcours par pointe, linéaire en nombre de commits. Remplace les API
    merge-base de pygit2 : aucune ne sait énumérer TOUS les merge-bases
    (vérifié sur 1.20.0 — elles en retournent un seul là où un dépôt à
    merges croisés en a deux).
    """
    marks: dict[Oid, set[Oid]] = defaultdict(set)

    for tip in sorted(tips):
        try:
            walker = repo.walk(pygit2.Oid(hex=tip), pygit2.GIT_SORT_TOPOLOGICAL)
        except (pygit2.GitError, ValueError):
            continue
        for commit in walker:
            marks[str(commit.id)].add(tip)

    return {oid: frozenset(labels) for oid, labels in marks.items()}


def _merge_bases(
    repo: pygit2.Repository, reach: dict[Oid, frozenset[Oid]]
) -> set[Oid]:
    """Ancêtres communs maximaux : les merge-bases.

    Un commun est maximal si aucun de ses enfants n'est commun aux mêmes
    pointes — sinon l'enfant est une base plus proche, et lui seul compte.
    """
    common = {oid for oid, labels in reach.items() if len(labels) >= 2}
    if not common:
        return set()

    children: dict[Oid, set[Oid]] = defaultdict(set)
    for oid in common:
        try:
            commit = repo.get(pygit2.Oid(hex=oid))
        except (pygit2.GitError, ValueError):
            continue
        if commit is None:
            continue
        for parent in commit.parents:
            children[str(parent.id)].add(oid)

    return {
        oid
        for oid in common
        if not any(reach[child] >= reach[oid] for child in children[oid] if child in reach)
    }


def significant_commits(
    repo: pygit2.Repository, refs: tuple[Ref, ...]
) -> set[Oid]:
    """Commits devenant des DisplayNode.

    Un commit est significatif s'il :
      - porte une ref ;
      - est un merge-base (ancêtre commun maximal) ;
      - est un merge dont au moins deux parents mènent à des refs distinctes ;
      - est une racine.
    """
    if not refs:
        return set()

    tips = {ref.target for ref in refs}
    significant: set[Oid] = set(tips)

    reach = _reachability(repo, tips)
    significant.update(_merge_bases(repo, reach))
    significant.update(_merges_and_roots(repo, tips))

    return significant


def _merges_and_roots(repo: pygit2.Repository, tips: set[Oid]) -> set[Oid]:
    """Merges, PARENTS de merges, et racines atteignables depuis les pointes.

    Les parents d'un merge sont significatifs même sans ref. Sans eux, les
    chemins parallèles d'un merge remontent tous jusqu'au même ancêtre et la
    déduplication par couple (ancêtre, descendant) n'en garde qu'un seul :
    vérifié sur un octopus à quatre parents, une arête produite au lieu de
    quatre, trois branches perdues.

    Les parents sont itérés, jamais indexés : un octopus en a plus de deux.
    """
    found: set[Oid] = set()
    visited: set[Oid] = set()

    for tip in sorted(tips):
        try:
            walker = repo.walk(pygit2.Oid(hex=tip), pygit2.GIT_SORT_TOPOLOGICAL)
        except (pygit2.GitError, ValueError):
            continue
        for commit in walker:
            oid = str(commit.id)
            if oid in visited:
                continue
            visited.add(oid)

            parents = commit.parents  # itérés, jamais indexés
            if not parents:
                found.add(oid)  # racine
            elif len(parents) >= 2:
                found.add(oid)  # merge
                found.update(str(p.id) for p in parents)  # et ses parents

    return found
```

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/core/test_significance.py -v`
Expected: PASS, 7 tests. `test_both_merge_bases_are_significant` est le test
critique : s'il échoue, l'API merge-base utilisée est la mauvaise.

- [ ] **Step 5: Commiter**

```bash
git add src/tortoisepy/core/significance.py tests/core/test_significance.py
git commit -m "feat: mark topologically significant commits"
```

---

### Task 7: Compression des segments linéaires

**Files:**
- Create: `src/tortoisepy/core/compression.py`
- Test: `tests/core/test_compression.py`

**Interfaces:**
- Consumes: `significant_commits` (tâche 6), `GraphEdge` (tâche 2)
- Produces: `compress_linear_segments(repo, significant) -> tuple[GraphEdge, ...]`

**Compression et réduction transitive sont deux transformations distinctes**
(§6.1). Cette tâche ne fait que la première.

- [ ] **Step 1: Écrire les tests**

```python
# tests/core/test_compression.py
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
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/core/test_compression.py -v`
Expected: FAIL — module introuvable.

- [ ] **Step 3: Implémenter**

```python
# src/tortoisepy/core/compression.py
"""Compression des segments linéaires — §6.1 étape 3.

Remplace toute chaîne de commits non significatifs entre deux commits
significatifs par une arête unique conservant les OID traversés.
"""

from __future__ import annotations

import pygit2

from tortoisepy.core.model import GraphEdge, Oid


def compress_linear_segments(
    repo: pygit2.Repository, significant: set[Oid]
) -> tuple[GraphEdge, ...]:
    """Une arête par chemin reliant deux commits significatifs."""
    edges: list[GraphEdge] = []
    seen: set[tuple[Oid, Oid]] = set()

    for oid in sorted(significant):
        try:
            commit = repo.get(pygit2.Oid(hex=oid))
        except (pygit2.GitError, ValueError):
            continue
        if commit is None:
            continue

        # Les parents sont itérés : un octopus en a plus de deux.
        for parent in commit.parents:
            ancestor, skipped = _walk_to_significant(repo, parent, significant)
            if ancestor is None:
                continue
            key = (ancestor, oid)
            if key in seen:
                continue
            seen.add(key)
            edges.append(
                GraphEdge(ancestor=ancestor, descendant=oid, skipped=tuple(skipped))
            )

    return tuple(edges)


def _walk_to_significant(
    repo: pygit2.Repository, start, significant: set[Oid]
) -> tuple[Oid | None, list[Oid]]:
    """Remonte le premier parent jusqu'au prochain commit significatif.

    Retourne cet ancêtre et les OID traversés, du plus récent au plus ancien
    inversés pour respecter l'ordre ancien → récent.
    """
    skipped: list[Oid] = []
    current = start
    guard = 0

    while current is not None:
        oid = str(current.id)
        if oid in significant:
            skipped.reverse()
            return oid, skipped

        skipped.append(oid)
        guard += 1
        if guard > 100_000:
            break  # garde-fou : historique anormalement long

        current = current.parents[0] if current.parents else None

    return None, []
```

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/core/test_compression.py -v`
Expected: PASS, 6 tests.

- [ ] **Step 5: Commiter**

```bash
git add src/tortoisepy/core/compression.py tests/core/test_compression.py
git commit -m "feat: compress linear commit segments into single edges"
```

---

### Task 8: Réduction transitive

**Files:**
- Create: `src/tortoisepy/core/reduction.py`
- Test: `tests/core/test_reduction.py`

**Interfaces:**
- Consumes: `GraphEdge` (tâche 2)
- Produces: `reduce_transitive_edges(edges) -> tuple[GraphEdge, ...]`

Fonction **pure** : elle ne touche pas au dépôt, seulement aux arêtes. Testable
sans aucune fixture Git.

- [ ] **Step 1: Écrire les tests**

```python
# tests/core/test_reduction.py
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
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/core/test_reduction.py -v`
Expected: FAIL — module introuvable.

- [ ] **Step 3: Implémenter**

```python
# src/tortoisepy/core/reduction.py
"""Réduction transitive — §6.1 étape 4.

Distincte de la compression (§6.1 étape 3) : celle-ci supprime des arêtes
redondantes, celle-là remplace des chaînes de commits. Les garder séparées
évite qu'une correction de l'une casse l'autre.
"""

from __future__ import annotations

from collections import defaultdict

from tortoisepy.core.model import GraphEdge, Oid


def reduce_transitive_edges(edges: tuple[GraphEdge, ...]) -> tuple[GraphEdge, ...]:
    """Supprime (A, B) s'il existe un chemin A → … → B d'au moins deux arêtes."""
    if not edges:
        return ()

    successors: dict[Oid, set[Oid]] = defaultdict(set)
    for e in edges:
        successors[e.ancestor].add(e.descendant)

    kept = [e for e in edges if not _has_indirect_path(successors, e.ancestor, e.descendant)]
    return tuple(kept)


def _has_indirect_path(
    successors: dict[Oid, set[Oid]], start: Oid, target: Oid
) -> bool:
    """Existe-t-il un chemin start → target passant par au moins un nœud ?"""
    stack = [s for s in successors.get(start, ()) if s != target]
    visited: set[Oid] = set()

    while stack:
        node = stack.pop()
        if node == target:
            return True
        if node in visited:
            continue
        visited.add(node)
        stack.extend(successors.get(node, ()))

    return False
```

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/core/test_reduction.py -v`
Expected: PASS, 6 tests.

- [ ] **Step 5: Commiter**

```bash
git add src/tortoisepy/core/reduction.py tests/core/test_reduction.py
git commit -m "feat: reduce transitive edges in compressed graph"
```

---

### Task 9: Stashes

**Files:**
- Create: `src/tortoisepy/core/stashes.py`
- Modify: `tests/conftest.py`
- Test: `tests/core/test_stashes.py`

**Interfaces:**
- Consumes: `DisplayNode`, `GraphEdge`, `Ref` (tâche 2)
- Produces: `collect_stashes(repo) -> tuple[tuple[DisplayNode, GraphEdge], ...]` ;
  fixture `repo_stashes`

**Vérifié :** un commit de stash a **2 ou 3 parents** (HEAD, index, fichiers non
suivis). Seul le premier compte (§4.1).

- [ ] **Step 1: Ajouter la fixture 13**

```python
# à ajouter dans tests/conftest.py

@pytest.fixture
def repo_stashes(tmp_path):
    """13. Plusieurs stashes à premiers parents différents.

    Construits via l'exécutable git : pygit2 n'expose pas de création de
    stash aussi directement, et on teste ici la lecture, pas l'écriture.
    """
    import subprocess

    path = tmp_path / "stashes"
    path.mkdir()

    def git(*args):
        subprocess.run(
            ["git", *args], cwd=path, check=True,
            capture_output=True,
            env={"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
                 "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
                 "PATH": "/usr/bin:/bin:/usr/local/bin"},
        )

    git("init", "-q", "-b", "master")
    (path / "f.txt").write_text("base\n")
    git("add", "f.txt")
    git("commit", "-q", "-m", "base")

    (path / "f.txt").write_text("stash 1\n")
    git("stash", "-q")

    (path / "f.txt").write_text("second commit\n")
    git("add", "f.txt")
    git("commit", "-q", "-m", "second")

    (path / "f.txt").write_text("stash 2\n")
    (path / "untracked.txt").write_text("untracked\n")
    git("stash", "-q", "-u")

    import pygit2
    class _Holder:
        pass
    holder = _Holder()
    holder.repo = pygit2.Repository(str(path))
    return holder
```

- [ ] **Step 2: Écrire les tests**

```python
# tests/core/test_stashes.py
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
```

- [ ] **Step 3: Vérifier l'échec**

Run: `.venv/bin/pytest tests/core/test_stashes.py -v`
Expected: FAIL — module introuvable.

- [ ] **Step 4: Implémenter**

```python
# src/tortoisepy/core/stashes.py
"""Rattachement des stashes — §6.1 étape 5.

Un commit de stash a deux ou trois parents : HEAD au moment du stash,
l'index, et éventuellement les fichiers non suivis. Seul le premier est
une vraie relation d'historique ; les autres créeraient des arêtes
parasites (§4.1). Les stashes ne participent donc ni au marquage des
commits significatifs ni à la réduction transitive.
"""

from __future__ import annotations

import pygit2

from tortoisepy.core.model import DisplayNode, GraphEdge, NodeKind, Ref, RefType


def collect_stashes(
    repo: pygit2.Repository,
) -> tuple[tuple[DisplayNode, GraphEdge], ...]:
    """Un nœud et une arête par stash."""
    try:
        entries = repo.listall_stashes()
    except (AttributeError, pygit2.GitError):
        return ()

    result: list[tuple[DisplayNode, GraphEdge]] = []

    for index, entry in enumerate(entries):
        oid = str(entry.commit_id)
        commit = repo.get(entry.commit_id)
        if commit is None or not commit.parents:
            continue

        name = f"stash@{{{index}}}"
        node = DisplayNode(
            oid=oid,
            kind=NodeKind.STASH,
            refs=(Ref(name=name, type=RefType.STASH, target=oid),),
        )
        edge = GraphEdge(
            ancestor=str(commit.parents[0].id),  # premier parent seulement
            descendant=oid,
            skipped=(),
        )
        result.append((node, edge))

    return tuple(result)
```

- [ ] **Step 5: Vérifier le succès**

Run: `.venv/bin/pytest tests/core/test_stashes.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 6: Commiter**

```bash
git add src/tortoisepy/core/stashes.py tests/core/test_stashes.py tests/conftest.py
git commit -m "feat: attach stashes via first parent only"
```

---

### Task 10: Assemblage du graphe

**Files:**
- Create: `src/tortoisepy/core/graph.py`
- Test: `tests/core/test_graph.py`

**Interfaces:**
- Consumes: toutes les tâches 4 à 9
- Produces: `build_graph(repo) -> DisplayGraph`

- [ ] **Step 1: Écrire les tests**

```python
# tests/core/test_graph.py
from tortoisepy.core.graph import build_graph
from tortoisepy.core.model import NodeKind


def test_diverged_graph_is_connected(repo_diverged):
    """Le test central : sans le merge-base, deux composantes séparées."""
    graph = build_graph(repo_diverged.repo)
    reachable = {graph.nodes[0].oid}
    changed = True
    while changed:
        changed = False
        for e in graph.edges:
            if e.ancestor in reachable and e.descendant not in reachable:
                reachable.add(e.descendant)
                changed = True
            elif e.descendant in reachable and e.ancestor not in reachable:
                reachable.add(e.ancestor)
                changed = True
    assert reachable == {n.oid for n in graph.nodes}


def test_merge_base_node_has_no_refs(repo_diverged):
    graph = build_graph(repo_diverged.repo)
    base = graph.node(repo_diverged.merge_base_expected)
    assert base is not None
    assert base.kind is NodeKind.JUNCTION or base.refs == ()


def test_ref_nodes_carry_their_refs(repo_diverged):
    graph = build_graph(repo_diverged.repo)
    tip = graph.node(repo_diverged.master_tip)
    assert any(r.name == "master" for r in tip.refs)


def test_each_oid_appears_once(repo_nested_merges):
    """§10.3 invariant."""
    graph = build_graph(repo_nested_merges.repo)
    oids = [n.oid for n in graph.nodes]
    assert len(oids) == len(set(oids))


def test_every_edge_connects_existing_nodes(repo_nested_merges):
    """§10.3 invariant."""
    graph = build_graph(repo_nested_merges.repo)
    known = {n.oid for n in graph.nodes}
    for e in graph.edges:
        assert e.ancestor in known
        assert e.descendant in known


def test_graph_is_acyclic(repo_nested_merges):
    """§10.3 invariant."""
    graph = build_graph(repo_nested_merges.repo)
    from collections import defaultdict
    succ = defaultdict(list)
    for e in graph.edges:
        succ[e.ancestor].append(e.descendant)

    state: dict[str, int] = {}

    def visit(node: str) -> bool:
        if state.get(node) == 1:
            return False
        if state.get(node) == 2:
            return True
        state[node] = 1
        for nxt in succ[node]:
            if not visit(nxt):
                return False
        state[node] = 2
        return True

    assert all(visit(n.oid) for n in graph.nodes)


def test_long_history_compresses_below_ten_nodes(repo_long_linear):
    graph = build_graph(repo_long_linear.repo)
    assert len(graph.nodes) < 10


def test_octopus_graph_keeps_four_incoming_edges(repo_octopus):
    graph = build_graph(repo_octopus.repo)
    incoming = [e for e in graph.edges if e.descendant == repo_octopus.octopus_oid]
    assert len(incoming) == 4


def test_empty_repository_yields_empty_graph(tmp_path):
    import pygit2
    repo = pygit2.init_repository(str(tmp_path / "empty"))
    graph = build_graph(repo)
    assert graph.nodes == ()
    assert graph.edges == ()


def test_build_is_deterministic(repo_nested_merges):
    """§10.4 : deux exécutions donnent le même résultat."""
    first = build_graph(repo_nested_merges.repo)
    second = build_graph(repo_nested_merges.repo)
    assert [n.oid for n in first.nodes] == [n.oid for n in second.nodes]
    assert [(e.ancestor, e.descendant) for e in first.edges] == [
        (e.ancestor, e.descendant) for e in second.edges
    ]
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/core/test_graph.py -v`
Expected: FAIL — module introuvable.

- [ ] **Step 3: Implémenter**

```python
# src/tortoisepy/core/graph.py
"""Assemblage du graphe affiché — pipeline complet de §6.1.

    refs → commits significatifs → compression → réduction → stashes
"""

from __future__ import annotations

import pygit2

from tortoisepy.core.compression import compress_linear_segments
from tortoisepy.core.model import DisplayGraph, DisplayNode, NodeKind
from tortoisepy.core.reduction import reduce_transitive_edges
from tortoisepy.core.refs import collect_refs, group_refs_by_oid
from tortoisepy.core.significance import significant_commits
from tortoisepy.core.stashes import collect_stashes


def build_graph(repo: pygit2.Repository) -> DisplayGraph:
    """Construit le graphe affiché d'un dépôt.

    Le tri par OID garantit le déterminisme exigé par §10.4.
    """
    refs = collect_refs(repo)
    significant = significant_commits(repo, refs)

    if not significant:
        return DisplayGraph(nodes=(), edges=())

    by_oid = group_refs_by_oid(refs)

    nodes = tuple(
        DisplayNode(
            oid=oid,
            kind=NodeKind.REF if oid in by_oid else NodeKind.JUNCTION,
            refs=by_oid.get(oid, ()),
        )
        for oid in sorted(significant)
    )

    edges = reduce_transitive_edges(compress_linear_segments(repo, significant))

    stash_nodes = []
    stash_edges = []
    known = set(significant)
    for node, edge in collect_stashes(repo):
        if edge.ancestor not in known:
            continue  # parent injoignable : le stash serait orphelin
        stash_nodes.append(node)
        stash_edges.append(edge)

    return DisplayGraph(
        nodes=nodes + tuple(stash_nodes),
        edges=edges + tuple(stash_edges),
    )
```

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/core/test_graph.py -v`
Expected: PASS, 10 tests.

- [ ] **Step 5: Commiter**

```bash
git add src/tortoisepy/core/graph.py tests/core/test_graph.py
git commit -m "feat: assemble display graph from full pipeline"
```

---

### Task 11: Fixtures restantes et invariants globaux

**Files:**
- Modify: `tests/conftest.py`
- Test: `tests/core/test_invariants.py`

**Interfaces:**
- Consumes: `build_graph` (tâche 10)
- Produces: fixtures `repo_multi_ref_commit`, `repo_tags`, `repo_remotes`,
  `repo_detached_head`, `repo_multiple_roots` ; suite d'invariants sur tous les
  dépôts.

- [ ] **Step 1: Ajouter les fixtures restantes**

```python
# à ajouter dans tests/conftest.py

@pytest.fixture
def repo_multi_ref_commit(tmp_path):
    """6 et 14. Un commit portant branche locale, distante et tag annoté."""
    b = RepoBuilder(tmp_path / "multiref")
    oid = b.commit("only")
    b.branch("develop", oid)
    b.remote_ref("origin", "develop", oid)
    b.tag_annotated("v1.0", oid)
    b.shared_oid = oid
    return b


@pytest.fixture
def repo_tags(tmp_path):
    """7. Tags légers et annotés."""
    b = RepoBuilder(tmp_path / "tags")
    first = b.commit("first")
    second = b.commit("second")
    b.tag_lightweight("light", first)
    b.tag_annotated("heavy", second)
    b.first_oid = first
    b.second_oid = second
    return b


@pytest.fixture
def repo_remotes(tmp_path):
    """8. Plusieurs remotes."""
    b = RepoBuilder(tmp_path / "remotes")
    oid = b.commit("c1")
    other = b.commit("c2")
    b.remote_ref("origin", "master", oid)
    b.remote_ref("github", "master", other)
    return b


@pytest.fixture
def repo_detached_head(tmp_path):
    """10. HEAD détaché sur un commit déjà porteur d'un tag."""
    b = RepoBuilder(tmp_path / "detached")
    first = b.commit("first")
    b.commit("second")
    b.tag_lightweight("v1.0", first)
    b.repo.set_head(pygit2.Oid(hex=first))
    b.detached_oid = first
    return b


@pytest.fixture
def repo_multiple_roots(tmp_path):
    """15. Deux historiques indépendants dans un même dépôt."""
    b = RepoBuilder(tmp_path / "roots")
    a1 = b.commit("a1", parents=[])
    a2 = b.commit("a2", parents=[a1])
    b1 = b.commit("b1", parents=[])
    b.branch("first", a2)
    b.branch("second", b1)
    b.root_a = a1
    b.root_b = b1
    return b
```

Ajouter `import pygit2` en tête de `tests/conftest.py` si absent.

- [ ] **Step 2: Écrire les tests d'invariants**

```python
# tests/core/test_invariants.py
"""Invariants de §10.3, vérifiés sur tous les dépôts de référence."""

from collections import defaultdict

import pytest

from tortoisepy.core.graph import build_graph

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
    """§4.1 : branche + remote + tag annoté sur un seul nœud."""
    graph = build_graph(repo_multi_ref_commit.repo)
    node = graph.node(repo_multi_ref_commit.shared_oid)
    names = {r.name for r in node.refs}
    assert {"develop", "origin/develop", "v1.0"} <= names


def test_multiple_roots_produce_two_components(repo_multiple_roots):
    """§10.4 : deux historiques indépendants restent séparés."""
    graph = build_graph(repo_multiple_roots.repo)
    assert graph.node(repo_multiple_roots.root_a) is not None
    assert graph.node(repo_multiple_roots.root_b) is not None


def test_detached_head_shares_node_with_tag(repo_detached_head):
    """§4.1 : HEAD détaché sur un commit tagué rejoint son nœud."""
    from tortoisepy.core.model import RefType
    graph = build_graph(repo_detached_head.repo)
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
```

- [ ] **Step 3: Exécuter**

Run: `.venv/bin/pytest tests/core/test_invariants.py -v`
Expected: PASS. Neuf tests × douze dépôts pour les paramétrés.

Si `test_each_ref_belongs_to_exactly_one_node` échoue sur
`repo_detached_head`, c'est que HEAD et le tag ne sont pas regroupés — vérifier
`group_refs_by_oid`.

- [ ] **Step 4: Commiter**

```bash
git add tests/conftest.py tests/core/test_invariants.py
git commit -m "test: add remaining fixtures and cross-repository invariants"
```

---

### Task 12: Sérialisation JSON et garde d'architecture

**Files:**
- Create: `src/tortoisepy/core/serialization.py`
- Test: `tests/core/test_serialization.py`
- Test: `tests/test_architecture.py`

**Interfaces:**
- Consumes: `DisplayGraph` (tâche 2), `build_graph` (tâche 10)
- Produces: `graph_to_dict(graph) -> dict` — **outil de test**, pas une commande
  publique (§10.1)

- [ ] **Step 1: Écrire les tests**

```python
# tests/core/test_serialization.py
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
```

```python
# tests/test_architecture.py
"""Garde d'architecture : core/ ne dépend jamais de Qt (§5)."""

import ast
from pathlib import Path

CORE = Path(__file__).parent.parent / "src" / "tortoisepy" / "core"
FORBIDDEN = ("PySide6", "PyQt6", "PyQt5", "tortoisepy.ui", "tortoisepy.layout")


def _imports_of(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def test_core_never_imports_qt_or_ui():
    offenders = []
    for path in CORE.rglob("*.py"):
        for name in _imports_of(path):
            if any(name.startswith(f) for f in FORBIDDEN):
                offenders.append(f"{path.name} importe {name}")
    assert not offenders, "core/ doit rester indépendant de Qt : " + "; ".join(offenders)
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/core/test_serialization.py -v`
Expected: FAIL — module introuvable. `tests/test_architecture.py` passe déjà
(aucun import interdit à ce stade) : c'est normal, il protège l'avenir.

- [ ] **Step 3: Implémenter**

```python
# src/tortoisepy/core/serialization.py
"""Sérialisation du graphe — outil de test (§10.1).

Volontairement absent de la CLI : une commande publique de plus serait à
maintenir sans bénéfice pour l'utilisateur.
"""

from __future__ import annotations

from tortoisepy.core.model import DisplayGraph


def graph_to_dict(graph: DisplayGraph) -> dict:
    """Forme comparable en test, ordonnée donc déterministe."""
    return {
        "nodes": [
            {
                "oid": node.oid,
                "kind": node.kind.value,
                "refs": [
                    {"name": ref.name, "type": ref.type.value}
                    for ref in sorted(node.refs, key=lambda r: (r.type.value, r.name))
                ],
            }
            for node in graph.nodes
        ],
        "edges": [
            {
                "ancestor": edge.ancestor,
                "descendant": edge.descendant,
                "skipped": edge.skipped_count,
            }
            for edge in graph.edges
        ],
    }
```

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/ -v`
Expected: PASS, suite complète.

- [ ] **Step 5: Commiter**

```bash
git add src/tortoisepy/core/serialization.py tests/core/test_serialization.py tests/test_architecture.py
git commit -m "feat: add graph serialization for tests and architecture guard"
```

---

### Task 13: Mesure de performance

**Files:**
- Test: `tests/test_performance.py`
- Modify: `docs/superpowers/specs/2026-09-11-tortoisepy-design.md` (§12.1)

**Interfaces:**
- Consumes: `build_graph` (tâche 10)
- Produces: mesures réelles confrontées aux cibles de §12.1

**Pourquoi cette tâche :** §6.1 affirme que l'approche par paires « reste
acceptable » pour 50 refs, sans mesure. On vérifie plutôt que de supposer.

- [ ] **Step 1: Écrire la fixture de charge et les mesures**

```python
# tests/test_performance.py
"""Confrontation aux cibles de §12.1. Non bloquant : informatif."""

import time

import pytest

from tests.fixtures.builder import RepoBuilder
from tortoisepy.core.graph import build_graph


@pytest.fixture(scope="module")
def repo_many_refs(tmp_path_factory):
    """Dépôt à 200 refs sur un historique de 2 000 commits."""
    path = tmp_path_factory.mktemp("manyrefs")
    b = RepoBuilder(path / "repo")
    previous = b.commit("root")
    tips = []
    for i in range(200):
        for _ in range(10):
            previous = b.commit(f"c{i}", parents=[previous])
        tips.append(previous)
    for i, oid in enumerate(tips):
        b.branch(f"branch{i}", oid)
    return b


def test_build_under_two_seconds(repo_many_refs):
    """§12.1 : construction < 2 s pour 200 refs."""
    start = time.perf_counter()
    graph = build_graph(repo_many_refs.repo)
    elapsed = time.perf_counter() - start
    print(f"\n200 refs / 2000 commits : {elapsed:.2f} s, "
          f"{len(graph.nodes)} nœuds, {len(graph.edges)} arêtes")
    assert elapsed < 2.0, (
        f"{elapsed:.2f} s dépasse la cible de §12.1. "
        "L'approche par paires de §6.1 doit être remplacée par un parcours "
        "unique avec marquage."
    )


def test_node_count_stays_under_target(repo_many_refs):
    """§12.1 : moins de 500 DisplayNode."""
    graph = build_graph(repo_many_refs.repo)
    assert len(graph.nodes) < 500
```

- [ ] **Step 2: Exécuter et consigner**

Run: `.venv/bin/pytest tests/test_performance.py -v -s`

Deux issues possibles, toutes deux acceptables :

- **PASS** — noter le temps mesuré dans §12.1 de la spec, en remplaçant la
  cible par la mesure réelle.
- **FAIL sur le temps** — c'est l'information recherchée. Consigner la mesure
  dans §6.1, et ouvrir une tâche de remplacement de l'étape 2 par un parcours
  unique avec marquage par ref. Ne pas optimiser dans cette tâche : la mesure
  d'abord, la décision ensuite.

- [ ] **Step 3: Mettre à jour la spec avec la mesure**

Remplacer dans §12.1 la ligne « Construction du graphe (dépôt à 200 refs) |
< 2 s » par la mesure constatée, et ajouter la date.

- [ ] **Step 4: Commiter**

```bash
git add tests/test_performance.py docs/superpowers/specs/2026-09-11-tortoisepy-design.md
git commit -m "test: measure graph build performance against spec targets"
```

---

## Fin de phase 1

À ce stade :

- `core/` construit un graphe correct sur douze dépôts de référence, dont les
  deux cas qui cassent les implémentations naïves (merge-bases multiples,
  octopus) ;
- les invariants de §10.3 sont vérifiés automatiquement ;
- aucune dépendance à Qt, vérifiée par un test ;
- la performance est mesurée, pas supposée.

**Phases suivantes**, à planifier séparément :

- **Phase 2 — `layout/`** : rangs, ordonnancement, coordonnées, invariants de
  §10.4.
- **Phase 3 — `core/operations.py` + `state.py`** : opérations Git,
  `OperationResult`, `RepositoryState`.
- **Phase 4 — `ui/`** : fenêtre, QGraphicsView, menu contextuel, mini-carte,
  surveillance de `.git`.
- **Phase 5 — `cli.py`** : point d'entrée `tgraph`, découverte du dépôt.
