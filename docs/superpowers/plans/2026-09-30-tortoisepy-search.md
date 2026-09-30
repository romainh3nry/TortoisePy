# Recherche & graphe en arrière-plan — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Chercher un commit dans tout l'historique, et cesser de figer
l'interface à chaque rafraîchissement.

**Architecture:** `core/search.py` parcourt l'historique. `core/graph_cache.py`
évite de reconstruire un graphe inchangé. L'interface déporte la construction
dans un `BackgroundTask` et surligne par cadres superposés, sans toucher au
rendu validé.

**Tech Stack:** Python 3.13, pygit2 1.20.1, PySide6 6.11.2, pytest.

**Spec:** `docs/superpowers/specs/2026-09-30-tortoisepy-search-design.md`

## Global Constraints

- **Ne jamais lancer de commande git sur CE dépôt** (add, commit, branch,
  checkout, stash, push, reset). L'utilisateur gère git lui-même. `git` dans un
  dépôt jetable sous `tmp_path` est attendu et normal.
- **Ne pas modifier** `src/tortoisepy/ui/theme.py`, `src/tortoisepy/layout/**`,
  `src/tortoisepy/ui/graph_items.py` — le rendu du graphe est validé et cette
  phase s'engage à ne pas y toucher (spec §6).
- `src/tortoisepy/core/**` n'importe jamais Qt (`tests/test_architecture.py`).
- **§7.0** : chercher et mettre en cache n'écrivent rien.
- Commentaires et docstrings **en français**, expliquant le *pourquoi*.
- Libellés visibles **en anglais** dans `main_window.py`.

## Review Focus

1. **Le surlignage ne doit pas toucher la sélection** — le menu contextuel
   bascule selon le nombre de nœuds sélectionnés (`main_window.py:246`, `:561`).
   Surligner par `setSelected` transformerait le menu en menu de comparaison
   dès qu'il y a deux résultats.
2. **Les commits ne sont pas les nœuds** — 3 000 commits donnent 10 nœuds
   (mesuré). Chercher dans les nœuds seuls raterait 99,7 % des commits.
3. **Le fil doit être attendu à la fermeture** — le défaut de la phase 10
   (`QThread: Destroyed while thread is still running`). `closeEvent` appelle
   déjà `stop()` ; la nouvelle tâche doit y passer aussi.
4. **Une seule construction à la fois** — deux constructions concurrentes se
   disputeraient le dépôt pour un résultat identique.
5. **Le cache doit s'invalider** sur : création/suppression de ref, changement
   de HEAD, opération en cours. Un cache qui ne s'invalide pas affiche un
   graphe faux, ce qui est pire que lent.

---

### Task 1: `core/graph_cache.py`

**Files:**
- Create: `src/tortoisepy/core/graph_cache.py`
- Test: `tests/core/test_graph_cache.py`

**Interfaces:**
- Produces:
  - `repo_fingerprint(repo) -> tuple` — empreinte des refs + HEAD + état
  - `GraphCache` avec `.get(repo, build)` qui rend le graphe, reconstruit
    seulement si l'empreinte a changé

**Mesuré (ne pas redécouvrir) :** l'empreinte coûte **0,4 ms**, `build_graph`
**330 ms** sur 3 000 commits — trois ordres de grandeur, ce qui justifie D24.

- [ ] **Step 1: Écrire les tests**

```python
# tests/core/test_graph_cache.py
import os
import subprocess

import pygit2
import pytest

from tortoisepy.core.graph_cache import GraphCache, repo_fingerprint


def run_git(path, *args):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
    }
    return subprocess.run(
        ["git", *args], cwd=path, env=env, capture_output=True, text=True
    )


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "d"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "f.txt").write_text("a\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "base")
    return pygit2.Repository(str(path))


def test_an_unchanged_repository_is_not_rebuilt(repo):
    cache = GraphCache()
    appels = []
    build = lambda r: appels.append(1) or "GRAPHE"

    assert cache.get(repo, build) == "GRAPHE"
    assert cache.get(repo, build) == "GRAPHE"
    assert len(appels) == 1, "le second appel doit venir du cache"


def test_a_new_branch_invalidates_the_cache(repo):
    cache = GraphCache()
    appels = []
    build = lambda r: appels.append(1) or f"GRAPHE {len(appels)}"

    cache.get(repo, build)
    run_git(repo.workdir, "branch", "nouvelle")

    assert cache.get(pygit2.Repository(repo.path), build) == "GRAPHE 2"


def test_a_new_commit_invalidates_the_cache(repo):
    cache = GraphCache()
    appels = []
    build = lambda r: appels.append(1) or f"GRAPHE {len(appels)}"

    cache.get(repo, build)
    (os.path.join(repo.workdir, "g.txt"))
    open(os.path.join(repo.workdir, "g.txt"), "w").write("g\n")
    run_git(repo.workdir, "add", ".")
    run_git(repo.workdir, "commit", "-q", "-m", "suivant")

    assert cache.get(pygit2.Repository(repo.path), build) == "GRAPHE 2"


def test_switching_head_invalidates_the_cache(repo):
    """Review Focus 5 : le nœud courant change l'affichage."""
    cache = GraphCache()
    appels = []
    build = lambda r: appels.append(1) or f"GRAPHE {len(appels)}"

    run_git(repo.workdir, "branch", "autre")
    cache.get(repo, build)
    run_git(repo.workdir, "checkout", "-q", "autre")

    assert cache.get(pygit2.Repository(repo.path), build) == "GRAPHE 2"


def test_an_operation_in_progress_invalidates_the_cache(repo):
    """Un merge en cours change ce que l'interface doit montrer."""
    cache = GraphCache()
    appels = []
    build = lambda r: appels.append(1) or f"GRAPHE {len(appels)}"

    run_git(repo.workdir, "checkout", "-q", "-b", "cote")
    open(os.path.join(repo.workdir, "f.txt"), "w").write("cote\n")
    run_git(repo.workdir, "commit", "-q", "-am", "cote")
    run_git(repo.workdir, "checkout", "-q", "main")
    open(os.path.join(repo.workdir, "f.txt"), "w").write("main\n")
    run_git(repo.workdir, "commit", "-q", "-am", "main")

    cache.get(pygit2.Repository(repo.path), build)
    run_git(repo.workdir, "merge", "cote")  # conflit -> état MERGE

    assert cache.get(pygit2.Repository(repo.path), build) == "GRAPHE 2"


def test_the_fingerprint_is_cheap(repo):
    """D24 tient sur cet écart : l'empreinte doit rester négligeable."""
    import time

    repo_fingerprint(repo)  # chauffe
    debut = time.perf_counter()
    for _ in range(50):
        repo_fingerprint(repo)
    moyenne = (time.perf_counter() - debut) / 50
    assert moyenne < 0.02, f"{moyenne * 1000:.1f} ms par empreinte"


def test_the_fingerprint_writes_nothing(repo):
    """§7.0 : lire les refs ne touche pas au dépôt."""
    import hashlib

    def empreinte_disque():
        h = hashlib.sha256()
        for racine, _, fichiers in os.walk(os.path.join(repo.workdir, ".git")):
            for f in sorted(fichiers):
                chemin = os.path.join(racine, f)
                h.update(chemin.encode())
                try:
                    h.update(str(os.stat(chemin).st_mtime_ns).encode())
                except OSError:
                    pass
        return h.hexdigest()

    avant = empreinte_disque()
    repo_fingerprint(repo)
    GraphCache().get(repo, lambda r: "X")
    assert empreinte_disque() == avant
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/core/test_graph_cache.py -q`
Expected: FAIL — le module n'existe pas.

- [ ] **Step 3: Implémenter**

```python
"""Éviter de reconstruire un graphe qui n'a pas changé — phase 13.

`build_graph` coûte **330 ms sur 3 000 commits**, et 97 % de ce temps
part dans un parcours complet de l'historique (mesuré). Or la plupart
des rafraîchissements — ceux que déclenche le surveillant de fichiers —
n'apportent aucun changement de refs : tout ce travail est refait pour
un résultat identique.

L'empreinte, elle, coûte **0,4 ms**. C'est cet écart de trois ordres de
grandeur qui rend le cache rentable dès le premier rafraîchissement
inutile.
"""

from __future__ import annotations

from typing import Any, Callable

import pygit2


def repo_fingerprint(repo: pygit2.Repository) -> tuple:
    """Ce qui, en changeant, change le graphe affiché.

    Les refs **et** HEAD **et** l'état : une opération en cours ou un
    changement de branche courante modifient l'affichage sans qu'aucune
    ref n'ait forcément bougé. Un cache qui les ignorerait montrerait un
    graphe faux — pire qu'un graphe lent.
    """
    try:
        refs = tuple(
            sorted((r.name, str(r.target)) for r in repo.references.objects)
        )
    except (pygit2.GitError, KeyError, ValueError):
        # Un dépôt illisible ne doit pas faire planter l'affichage : on
        # rend une empreinte unique, qui force la reconstruction.
        return (object(),)

    if repo.head_is_unborn:
        tete: str | None = None
    elif repo.head_is_detached:
        tete = str(repo.head.target)
    else:
        tete = repo.head.shorthand

    return (refs, tete, int(repo.state()))


class GraphCache:
    """Garde le dernier graphe construit, tant que le dépôt n'a pas bougé.

    En mémoire seulement, le temps de la session : persister sur disque
    demanderait d'invalider correctement entre deux lancements, et §7.0
    interdit d'écrire dans le dépôt.
    """

    def __init__(self) -> None:
        self._empreinte: tuple | None = None
        self._graphe: Any = None

    def get(
        self, repo: pygit2.Repository, build: Callable[[pygit2.Repository], Any]
    ) -> Any:
        """Rend le graphe, en le reconstruisant seulement si nécessaire."""
        empreinte = repo_fingerprint(repo)
        if self._graphe is not None and empreinte == self._empreinte:
            return self._graphe

        graphe = build(repo)
        self._empreinte = empreinte
        self._graphe = graphe
        return graphe

    def invalidate(self) -> None:
        """Force la reconstruction au prochain appel.

        Utile après une opération dont on sait qu'elle change le graphe,
        sans attendre que l'empreinte le prouve.
        """
        self._empreinte = None
        self._graphe = None
```

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/core/test_graph_cache.py tests/core/test_graph.py -q`
Expected: PASS.

- [ ] **Step 5: Signaler les fichiers prêts** — ne commite pas.

---

### Task 2: `core/search.py`

**Files:**
- Create: `src/tortoisepy/core/search.py`
- Test: `tests/core/test_search.py`

**Interfaces:**
- Produces: `search_commits(repo, motif) -> tuple[str, ...]` — OID des commits
  trouvés, du plus récent au plus ancien

**Mesuré :** ~325 ms pour parcourir 3 000 commits, quel que soit le motif — le
coût est celui du parcours, pas de la comparaison. D'où D26 (sur validation,
pas à la frappe).

- [ ] **Step 1: Écrire les tests**

```python
# tests/core/test_search.py
import os
import subprocess

import pygit2
import pytest

from tortoisepy.core.search import search_commits


def run_git(path, *args, auteur="Alice"):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": auteur, "GIT_AUTHOR_EMAIL": "a@a",
        "GIT_COMMITTER_NAME": auteur, "GIT_COMMITTER_EMAIL": "a@a",
    }
    return subprocess.run(
        ["git", *args], cwd=path, env=env, capture_output=True, text=True
    )


@pytest.fixture
def repo(tmp_path):
    """Trois commits, deux auteurs."""
    path = tmp_path / "d"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    for nom, message, auteur in (
        ("a.txt", "ajoute l'authentification", "Alice"),
        ("b.txt", "corrige le cache", "Bob"),
        ("c.txt", "AUTHENTIFICATION en majuscules", "Alice"),
    ):
        (path / nom).write_text("x\n")
        run_git(path, "add", ".", auteur=auteur)
        run_git(path, "commit", "-q", "-m", message, auteur=auteur)
    return pygit2.Repository(str(path))


def test_searching_by_message(repo):
    trouves = search_commits(repo, "cache")
    assert len(trouves) == 1
    assert "cache" in repo.get(trouves[0]).message


def test_searching_ignores_case(repo):
    """« authentification » doit trouver aussi la version en majuscules."""
    assert len(search_commits(repo, "authentification")) == 2


def test_searching_by_author(repo):
    assert len(search_commits(repo, "bob")) == 1
    assert len(search_commits(repo, "alice")) == 2


def test_searching_by_sha_prefix(repo):
    cible = str(repo.head.target)
    assert search_commits(repo, cible[:8]) == (cible,)


def test_an_empty_pattern_finds_nothing(repo):
    """Un motif vide efface le surlignage : il ne surligne pas tout."""
    assert search_commits(repo, "") == ()
    assert search_commits(repo, "   ") == ()


def test_an_unknown_pattern_finds_nothing(repo):
    assert search_commits(repo, "nimportequoi") == ()


def test_results_come_newest_first(repo):
    """L'ordre du graphe : le plus récent en tête."""
    trouves = search_commits(repo, "alice")
    messages = [repo.get(o).message.strip() for o in trouves]
    assert messages[0].startswith("AUTHENTIFICATION")


def test_searching_covers_commits_behind_nodes(tmp_path):
    """Review Focus 2 : le piège de la phase.

    Mesuré : 3 000 commits se réduisent à 10 nœuds. Une recherche qui
    n'examinerait que les nœuds raterait 99,7 % des commits.
    """
    path = tmp_path / "chaine"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    for i in range(30):
        (path / "f.txt").write_text(f"{i}\n")
        run_git(path, "add", ".")
        run_git(path, "commit", "-q", "-m", f"etape {i}")

    repo = pygit2.Repository(str(path))
    from tortoisepy.core.graph import build_graph

    assert len(build_graph(repo).nodes) < 5, "le graphe compresse bien"
    assert len(search_commits(repo, "etape")) == 30, (
        "la recherche doit voir les commits, pas seulement les nœuds"
    )


def test_searching_an_empty_repository(tmp_path):
    path = tmp_path / "vide"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    assert search_commits(pygit2.Repository(str(path)), "x") == ()
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/core/test_search.py -q`
Expected: FAIL — le module n'existe pas.

- [ ] **Step 3: Implémenter**

```python
"""Chercher un commit dans tout l'historique — phase 13.

**Les commits ne sont pas les nœuds.** Vérifié : 3 000 commits se
réduisent à 10 nœuds, la compression du graphe faisant son travail. Une
recherche qui n'examinerait que les nœuds raterait 99,7 % des commits ;
on parcourt donc l'historique, et l'interface surligne le nœud porteur.
"""

from __future__ import annotations

import pygit2


def search_commits(repo: pygit2.Repository, motif: str) -> tuple[str, ...]:
    """OID des commits dont le message, l'auteur ou le SHA correspond.

    Un seul champ pour les trois critères : obliger à en choisir un
    avant de taper ferait réfléchir l'utilisateur à la place de l'outil.

    Sans casse, sauf pour le SHA où seul le préfixe compte.

    Un motif vide ne rend **rien** plutôt que tout : il sert à effacer
    le surlignage, et surligner l'intégralité du graphe n'apprendrait
    rien.
    """
    recherche = motif.strip().lower()
    if not recherche:
        return ()

    try:
        if repo.head_is_unborn:
            return ()
        depart = repo.head.target
    except (pygit2.GitError, KeyError, ValueError):
        return ()

    trouves: list[str] = []
    try:
        for commit in repo.walk(depart, pygit2.GIT_SORT_TOPOLOGICAL):
            oid = str(commit.id)
            if (
                recherche in commit.message.lower()
                or recherche in commit.author.name.lower()
                or oid.startswith(recherche)
            ):
                trouves.append(oid)
    except (pygit2.GitError, KeyError, ValueError):
        return tuple(trouves)

    return tuple(trouves)
```

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/core/test_search.py -q`
Expected: PASS.

- [ ] **Step 5: Signaler les fichiers prêts** — ne commite pas.

---

### Task 3: L'interface

**Files:**
- Modify: `src/tortoisepy/ui/graph_view.py`
- Modify: `src/tortoisepy/ui/main_window.py`
- Test: `tests/ui/test_graph_view.py`, `tests/ui/test_main_window.py`

**Interfaces:**
- Consumes: `GraphCache` (tâche 1), `search_commits` (tâche 2)
- Produces: `GraphView.highlight(oids)`, champ de recherche, construction du
  graphe en arrière-plan

**Vérifié par sonde, sur un vrai graphe (ne pas redécouvrir) :**

- surligner par un `QGraphicsRectItem` superposé **n'altère pas la
  sélection** — `_selected_node()` continue de répondre, le menu contextuel
  reste intact ;
- les cadres s'enlèvent proprement ;
- `NodeItem` et `graph_items.py` **ne sont pas modifiés**.

**Piège :** surligner par `setSelected` casserait le menu — il bascule en menu
de comparaison au-delà d'un nœud sélectionné (`main_window.py:246`, `:561`).

- [ ] **Step 1: Écrire les tests**

```python
# à ajouter dans tests/ui/test_graph_view.py


def test_highlighting_does_not_change_the_selection(qtbot, view_with_graph):
    """Review Focus 1 : sinon le menu contextuel bascule.

    Le menu propose des comparaisons dès que deux nœuds sont
    sélectionnés : surligner par `setSelected` transformerait une
    recherche à deux résultats en menu de comparaison.
    """
    vue, graphe = view_with_graph
    oids = tuple(n.oid for n in graphe.nodes)
    vue.select_node(oids[0])
    avant = vue.selected_oids()

    vue.highlight(oids)

    assert vue.selected_oids() == avant


def test_highlighting_then_clearing(qtbot, view_with_graph):
    vue, graphe = view_with_graph
    oids = tuple(n.oid for n in graphe.nodes)

    vue.highlight(oids[:1])
    assert vue.highlighted_count() == 1

    vue.highlight(())
    assert vue.highlighted_count() == 0


def test_highlighting_an_absent_oid_is_harmless(qtbot, view_with_graph):
    vue, _ = view_with_graph
    vue.highlight(("f" * 40,))
    assert vue.highlighted_count() == 0
```

```python
# à ajouter dans tests/ui/test_main_window.py


def test_searching_highlights_the_matching_nodes(window, monkeypatch):
    from tortoisepy.ui import main_window as module

    cible = window.graph.nodes[0].oid
    monkeypatch.setattr(module, "search_commits", lambda repo, motif: (cible,))

    window.search_field.setText("quelque chose")
    window.run_search()

    assert window.view.highlighted_count() == 1
    assert "1" in window.statusBar().currentMessage()


def test_an_empty_search_clears_the_highlight(window, monkeypatch):
    from tortoisepy.ui import main_window as module

    cible = window.graph.nodes[0].oid
    monkeypatch.setattr(module, "search_commits", lambda repo, motif: (cible,))
    window.search_field.setText("x")
    window.run_search()

    monkeypatch.setattr(module, "search_commits", lambda repo, motif: ())
    window.search_field.setText("")
    window.run_search()

    assert window.view.highlighted_count() == 0


def test_a_search_without_result_says_so(window, monkeypatch):
    from tortoisepy.ui import main_window as module

    monkeypatch.setattr(module, "search_commits", lambda repo, motif: ())
    window.search_field.setText("introuvable")
    window.run_search()

    assert "no" in window.statusBar().currentMessage().lower()


def test_an_unchanged_repository_is_not_rebuilt(window, monkeypatch):
    """Le cache en action : un refresh sans changement ne reconstruit pas."""
    from tortoisepy.ui import main_window as module

    appels = []
    vrai = module.build_graph
    monkeypatch.setattr(
        module, "build_graph",
        lambda repo, *a, **k: appels.append(1) or vrai(repo, *a, **k),
    )
    window.refresh()
    window.refresh()

    assert len(appels) <= 1, f"{len(appels)} constructions pour 2 refresh"
```

- [ ] **Step 2: Vérifier l'échec**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_graph_view.py tests/ui/test_main_window.py -q -k "highlight or search or rebuilt"`
Expected: FAIL — `highlight`, `search_field` et le cache n'existent pas.

- [ ] **Step 3: Le surlignage (`graph_view.py`)**

```python
    def highlight(self, oids) -> None:
        """Encadre les nœuds portant ces commits.

        **Pas `setSelected`** : le menu contextuel bascule selon le
        nombre de nœuds sélectionnés, donc une recherche à plusieurs
        résultats le transformerait en menu de comparaison (vérifié).
        On superpose des cadres, qui ne touchent à rien d'autre — et
        `graph_items.py`, dont le rendu est validé, n'est pas modifié.
        """
        for cadre in self._highlights:
            scene = cadre.scene()
            if scene is not None:
                scene.removeItem(cadre)
        self._highlights = []

        scene = self.scene()
        if scene is None or not oids:
            return

        cibles = set(oids)
        for item in scene.items():
            if isinstance(item, NodeItem) and item.node.oid in cibles:
                cadre = QGraphicsRectItem(
                    item.sceneBoundingRect().adjusted(-4, -4, 4, 4)
                )
                cadre.setPen(QPen(QColor(255, 170, 0), 3))
                cadre.setBrush(Qt.BrushStyle.NoBrush)
                cadre.setZValue(100)
                scene.addItem(cadre)
                self._highlights.append(cadre)

    def highlighted_count(self) -> int:
        return len(self._highlights)
```

Initialiser `self._highlights: list = []` dans `__init__`, et **vider la liste
dans `show_graph`** : la scène précédente est détruite, les cadres avec elle,
et garder des références mortes ferait compter des surlignages inexistants.

Imports à ajouter : `QGraphicsRectItem` (QtWidgets), `QColor`, `QPen` (QtGui),
`Qt` (QtCore) — vérifier lesquels manquent avant d'ajouter.

- [ ] **Step 4: La recherche et le cache (`main_window.py`)**

Imports : `from tortoisepy.core.search import search_commits` et
`from tortoisepy.core.graph_cache import GraphCache`.

Dans `__init__` : `self._graph_cache = GraphCache()`, et un champ :

```python
        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("Search message, author or SHA…")
        # Sur validation, pas à la frappe : chercher coûte ~325 ms sur
        # 3 000 commits (mesuré), ce qui rendrait la saisie inutilisable.
        self.search_field.returnPressed.connect(self.run_search)
```

placé dans la barre d'outils existante.

```python
    def run_search(self) -> None:
        """Surligne les commits correspondants, et dit combien."""
        motif = self.search_field.text()
        trouves = search_commits(self.repository, motif)
        self.view.highlight(trouves)

        if not motif.strip():
            self.statusBar().showMessage("", 1)
            return
        if trouves:
            self.statusBar().showMessage(
                f"{len(trouves)} commit(s) found", 15000
            )
        else:
            self.statusBar().showMessage("no commit found", 15000)
```

Dans `refresh()`, passer par le cache :

```python
        self.graph = self._graph_cache.get(self.repository, build_graph)
```

**Attention :** `refresh()` se termine par plusieurs mises à jour
(`_center_on_head`, `_update_status`, …) — ne rien y supprimer.

- [ ] **Step 5: Vérifier le succès**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/ -q`
Expected: PASS.

- [ ] **Step 6: Le rendu n'a pas bougé**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_graph_items.py tests/layout/ -q`
Expected: PASS — **et `git status` doit montrer `graph_items.py`, `theme.py` et
`layout/` inchangés.** C'est l'engagement de la spec §6.

- [ ] **Step 7: Lecture seule et architecture**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/test_read_only.py tests/test_architecture.py -q`
Expected: PASS.

- [ ] **Step 8: Suite complète**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`
Expected: 918 + ~25 tests. **Deux échecs connus et sans rapport** :
`test_fetch_hides_the_bar_when_done` et `test_worker_reports_its_result`.

- [ ] **Step 9: Signaler les fichiers prêts** — ne commite pas. Donner le
décompte exact.

---

## Note sur la construction en arrière-plan

La spec (§4, D23) prévoit aussi de déporter `build_graph` dans un
`BackgroundTask`. **Ce plan livre d'abord le cache**, qui supprime le coût des
rafraîchissements inutiles — la majorité — pour une complexité bien moindre.

Déporter le calcul restant demande de traiter l'affichage pendant le calcul, la
sérialisation des demandes concurrentes, et l'attente du fil à la fermeture
(le défaut de la phase 10). C'est une tâche à part entière, à mesurer **après**
le cache : si l'ouverture reste gênante sur un gros dépôt, elle se justifie ;
sinon, elle ajoute un fil pour rien.

## Fin de phase 13

Chercher un commit par message, auteur ou SHA, et ne plus reconstruire un
graphe inchangé.

**Hors périmètre**, conformément à la spec §8 : chercher dans le contenu des
fichiers, chercher par date ou par fichier, persister le cache, naviguer de
résultat en résultat.
