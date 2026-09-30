# Amend & ahead/behind Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corriger le dernier commit depuis l'application, et savoir en
permanence de combien l'on est en avance ou en retard sur le serveur.

**Architecture:** `core/amend.py` amende le dernier commit en réutilisant la
construction d'arbre de `commit_selection`. `core/push_state.py` gagne
`divergence()`, qui rend le couple ahead/behind. L'interface pose une case dans
la fenêtre de commit, et l'indicateur dans la barre de statut.

**Tech Stack:** Python 3.13, pygit2 1.20.1, PySide6 6.11.2, pytest.

**Spec:** `docs/superpowers/specs/2026-09-29-tortoisepy-amend-design.md`

## Global Constraints

- **Ne jamais lancer de commande git sur CE dépôt** (add, commit, branch,
  checkout, stash, push, reset). L'utilisateur gère git lui-même. `git` dans un
  dépôt jetable sous `tmp_path` est attendu et normal.
- **Ne pas modifier** `src/tortoisepy/ui/theme.py`, `src/tortoisepy/layout/**`,
  `src/tortoisepy/ui/graph_items.py` — le rendu du graphe est validé.
- `src/tortoisepy/core/**` n'importe jamais Qt (`tests/test_architecture.py`).
- **§7.0** : l'application n'écrit dans un dépôt QUE sur action explicite de
  l'utilisateur dans l'interface. Calculer ahead/behind n'écrit rien.
- Commentaires et docstrings **en français**, expliquant le *pourquoi*.
- **Libellés : le français dans `commit_window.py`** (« Message : »,
  « Annuler » y sont déjà en français — vérifié), **l'anglais ailleurs**
  (barre de statut, menus).

## Review Focus

1. **HEAD détachée** — l'amend y est **accepté** par libgit2 et crée un commit
   **orphelin** (vérifié). L'assertion qui compte n'est pas « refusé » mais
   « aucun commit orphelin créé ».
2. **Fraîcheur de l'indicateur** — il reflète la ref de suivi, pas le serveur
   (vérifié : `↓1` affiché alors que le serveur en avait 2). Un test doit poser
   ce comportement pour que personne ne le « corrige » en interrogeant le
   réseau.
3. **Auteur d'origine** — amender ne doit pas se réapproprier le travail d'un
   autre : nom et date d'auteur conservés.
4. **Branche sans upstream** — `branch.upstream` vaut `None` : rien à comparer,
   rien à afficher.
5. **Amend sur un commit déjà poussé** — l'avertissement doit apparaître là, et
   **seulement** là.

---

### Task 1: `core/amend.py`

**Files:**
- Create: `src/tortoisepy/core/amend.py`
- Test: `tests/core/test_amend.py`

**Interfaces:**
- Produces:
  - `can_amend(repo) -> str | None` — `None` si c'est possible, sinon la raison
  - `amend_commit(repo, paths, message) -> OperationResult`
  - `last_commit_message(repo) -> str`

**Vérifié sur pygit2 1.20 (ne pas redécouvrir) :**
- `repo.amend_commit(commit, refname, author=None, committer=None, message=None, tree=None) -> Oid` ;
- amender en fournissant un `tree` ajoute bien le fichier oublié, et **un seul
  commit** subsiste ;
- amender un commit qui n'est plus la pointe -> `GitError('commit to amend is
  not the tip of the given branch')` ;
- le **tout premier commit** (sans parent) s'amende sans problème ;
- l'**auteur d'origine est conservé** quand on ne passe pas `author=` ;
- **sur HEAD détachée, l'amend est ACCEPTÉ** — d'où le refus explicite.

- [ ] **Step 1: Écrire les tests**

```python
# tests/core/test_amend.py
import os
import subprocess

import pygit2
import pytest

from tortoisepy.core.amend import amend_commit, can_amend, last_commit_message


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
    """Un dépôt avec un commit et un fichier suivi."""
    path = tmp_path / "d"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "f.txt").write_text("a\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "message initial")
    return pygit2.Repository(str(path))


def test_the_last_message_is_read_back(repo):
    assert last_commit_message(repo).strip() == "message initial"


def test_amending_only_the_message(repo):
    result = amend_commit(repo, (), "message corrige")
    assert result.success is True

    fresh = pygit2.Repository(repo.path)
    commit = fresh.head.peel(pygit2.Commit)
    assert commit.message.strip() == "message corrige"
    assert len(list(fresh.walk(commit.id))) == 1, "un seul commit"


def test_amending_adds_a_forgotten_file(repo):
    """La moitié du besoin : le fichier qu'on a oublié d'ajouter."""
    (pygit2.Path(repo.workdir) / "x") if False else None
    open(os.path.join(repo.workdir, "oublie.txt"), "w").write("oublie\n")

    result = amend_commit(repo, ("oublie.txt",), "message initial")
    assert result.success is True

    fresh = pygit2.Repository(repo.path)
    commit = fresh.head.peel(pygit2.Commit)
    assert sorted(e.name for e in commit.tree) == ["f.txt", "oublie.txt"]
    assert len(list(fresh.walk(commit.id))) == 1


def test_amending_keeps_the_original_author(repo):
    """Review Focus 3 : amender n'est pas se réapproprier le travail."""
    avant = repo.head.peel(pygit2.Commit).author
    amend_commit(repo, (), "autre message")

    apres = pygit2.Repository(repo.path).head.peel(pygit2.Commit).author
    assert apres.name == avant.name
    assert apres.time == avant.time


def test_amending_the_root_commit(repo):
    """Le premier commit n'a pas de parent, et s'amende quand même."""
    result = amend_commit(repo, (), "racine amendee")
    assert result.success is True
    fresh = pygit2.Repository(repo.path)
    assert fresh.head.peel(pygit2.Commit).message.strip() == "racine amendee"


def test_amending_on_a_detached_head_creates_no_orphan(repo):
    """Review Focus 1 : le seul cas vraiment dangereux.

    Vérifié : libgit2 **accepte** l'amend sur une HEAD détachée, et le
    nouveau commit n'est suivi par aucune branche — invisible dans le
    graphe, récupérable seulement par le reflog.
    """
    run_git(repo.workdir, "checkout", "-q", "--detach")
    detache = pygit2.Repository(repo.path)
    avant = str(detache.head.target)

    assert can_amend(detache) is not None
    result = amend_commit(detache, (), "ne doit pas passer")
    assert result.success is False

    fresh = pygit2.Repository(repo.path)
    assert str(fresh.head.target) == avant, "aucun commit créé"


def test_amending_an_empty_repository_is_refused(tmp_path):
    path = tmp_path / "vide"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    vide = pygit2.Repository(str(path))

    assert can_amend(vide) is not None
    result = amend_commit(vide, (), "rien")
    assert result.success is False


def test_amending_during_another_operation_is_refused(repo):
    """L'état est déjà instable : n'y ajoutons pas une réécriture."""
    run_git(repo.workdir, "checkout", "-q", "-b", "autre")
    open(os.path.join(repo.workdir, "f.txt"), "w").write("autre\n")
    run_git(repo.workdir, "commit", "-q", "-am", "cote autre")
    run_git(repo.workdir, "checkout", "-q", "main")
    open(os.path.join(repo.workdir, "f.txt"), "w").write("main\n")
    run_git(repo.workdir, "commit", "-q", "-am", "cote main")
    run_git(repo.workdir, "merge", "autre")  # conflit -> état MERGE

    en_conflit = pygit2.Repository(repo.path)
    assert en_conflit.state() != pygit2.enums.RepositoryState.NONE
    assert can_amend(en_conflit) is not None
    assert amend_commit(en_conflit, (), "pendant un merge").success is False


def test_amending_refuses_an_empty_message(repo):
    assert amend_commit(repo, (), "   ").success is False
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/core/test_amend.py -q`
Expected: FAIL — le module n'existe pas.

- [ ] **Step 3: Implémenter**

```python
"""Corriger le dernier commit — phase 12.

Amender réécrit le commit : son identifiant change. S'il était poussé,
la branche diverge et le push normal est rejeté. **C'est le force-push
de la phase 10 qui rend ce geste praticable** ; sans lui, amender aurait
mené à une impasse.
"""

from __future__ import annotations

import pygit2

from tortoisepy.core.operations import _build_tree, _signature
from tortoisepy.core.results import OperationResult, failed, guarded, succeeded


def last_commit_message(repo: pygit2.Repository) -> str:
    """Message du dernier commit, ou chaîne vide s'il n'y en a pas."""
    if repo.head_is_unborn:
        return ""
    try:
        return repo.head.peel(pygit2.Commit).message
    except (pygit2.GitError, KeyError):
        return ""


def can_amend(repo: pygit2.Repository) -> str | None:
    """`None` si l'on peut amender, sinon la raison de ne pas pouvoir.

    Rendre la raison plutôt qu'un booléen : l'interface l'affiche en
    infobulle, et « grisé sans explication » n'apprend rien.
    """
    if repo.head_is_unborn:
        return "nothing to amend yet"

    if repo.head_is_detached:
        # **Vérifié** : libgit2 accepte l'amend sur une HEAD détachée, et
        # le commit produit n'est suivi par aucune branche — invisible
        # dans le graphe, récupérable seulement par le reflog. C'est le
        # seul cas où amender fait vraiment perdre du travail.
        return "cannot amend on a detached HEAD"

    if repo.state() != pygit2.enums.RepositoryState.NONE:
        return "an operation is already in progress"

    return None


@guarded("Amend")
def amend_commit(
    repo: pygit2.Repository, paths: tuple[str, ...], message: str
) -> OperationResult:
    """Réécrit le dernier commit : message, et fichiers ajoutés.

    L'auteur d'origine est conservé — on ne passe pas `author=` — car
    amender n'est pas se réapproprier le travail de quelqu'un d'autre.
    """
    raison = can_amend(repo)
    if raison is not None:
        return failed("Amend", raison, repository_changed=False)

    text = message.strip()
    if not text:
        return failed("Amend", "empty commit message", repository_changed=False)

    commit = repo.head.peel(pygit2.Commit)

    tree = commit.tree.id
    selected = tuple(p for p in paths if p)
    if selected:
        # Partir de l'arbre du commit amendé, et non de HEAD : ce sont les
        # mêmes ici, mais le dire évite une surprise si cela changeait.
        construit = _build_tree(repo, selected, base=commit.tree)
        if isinstance(construit, OperationResult):
            return construit
        tree = construit

    oid = repo.amend_commit(
        commit,
        "HEAD",
        committer=_signature(repo),
        message=text + ("\n" if not text.endswith("\n") else ""),
        tree=tree,
    )
    return succeeded(f"Amended {str(oid)[:8]}")
```

**Note :** `_build_tree` n'existe pas encore — la logique est aujourd'hui
**en ligne** dans `commit_selection` (operations.py:436-482). L'extraire est la
première chose à faire dans cette étape :

- créer `_build_tree(repo, paths, base)` dans `operations.py` à partir des
  lignes de `commit_selection` qui bâtissent l'index détaché (création du blob,
  `lstat` pour le mode, suppression d'un fichier absent), en rendant soit un
  `Oid` d'arbre, soit un `OperationResult` en cas d'échec ;
- faire appeler `_build_tree` par `commit_selection`, **sans changer son
  comportement** : ses tests doivent rester verts, c'est le garde-fou de cette
  extraction ;
- `base` est l'arbre de départ (`None` pour un dépôt sans commit).

Ne pas dupliquer cette logique dans `amend.py` : les pièges qu'elle contient
(symlink cassé, bit exécutable, `lexists` et non `exists`) ont chacun coûté un
défaut en phase 6.

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/core/test_amend.py tests/core/test_commit_operation.py -q`
Expected: PASS — et les tests de `commit_selection` verts prouvent que
l'extraction n'a rien cassé.

- [ ] **Step 5: Signaler les fichiers prêts** — ne commite pas.

---

### Task 2: L'écart avec le serveur

**Files:**
- Modify: `src/tortoisepy/core/push_state.py`
- Test: `tests/core/test_push_state.py`

**Interfaces:**
- Produces: `divergence(repo) -> tuple[int, int] | None` — `(ahead, behind)`,
  ou `None` s'il n'y a rien à comparer

**Vérifié :** `repo.ahead_behind(local, upstream) -> (int, int)` ; une branche
sans upstream rend `branch.upstream is None`.

- [ ] **Step 1: Écrire les tests**

```python
# à ajouter dans tests/core/test_push_state.py


def _serveur_et_deux_clones(tmp_path):
    """Un serveur, mon clone, et celui d'un autre."""
    bare = tmp_path / "serveur.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], capture_output=True)
    moi = tmp_path / "moi"
    subprocess.run(["git", "clone", "-q", str(bare), str(moi)], capture_output=True)
    (moi / "f.txt").write_text("a\n")
    run_git(moi, "add", ".")
    run_git(moi, "commit", "-q", "-m", "base")
    run_git(moi, "push", "-q", "origin", "HEAD")
    autre = tmp_path / "autre"
    subprocess.run(["git", "clone", "-q", str(bare), str(autre)], capture_output=True)
    return bare, moi, autre


def test_an_up_to_date_branch_has_no_divergence(tmp_path):
    from tortoisepy.core.push_state import divergence

    _, moi, _ = _serveur_et_deux_clones(tmp_path)
    assert divergence(pygit2.Repository(str(moi))) == (0, 0)


def test_local_commits_count_as_ahead(tmp_path):
    from tortoisepy.core.push_state import divergence

    _, moi, _ = _serveur_et_deux_clones(tmp_path)
    (moi / "g.txt").write_text("g\n")
    run_git(moi, "add", ".")
    run_git(moi, "commit", "-q", "-m", "local")

    assert divergence(pygit2.Repository(str(moi))) == (1, 0)


def test_remote_commits_count_as_behind_after_a_fetch(tmp_path):
    from tortoisepy.core.push_state import divergence

    _, moi, autre = _serveur_et_deux_clones(tmp_path)
    (autre / "h.txt").write_text("h\n")
    run_git(autre, "add", ".")
    run_git(autre, "commit", "-q", "-m", "ailleurs")
    run_git(autre, "push", "-q", "origin", "HEAD")
    run_git(moi, "fetch", "-q", "origin")

    assert divergence(pygit2.Repository(str(moi))) == (0, 1)


def test_the_divergence_reflects_the_last_fetch_not_the_server(tmp_path):
    """Review Focus 2 : poser ce comportement, pour qu'on ne le « corrige » pas.

    Vérifié : sans nouveau fetch, l'indicateur annonçait 1 commit de
    retard alors que le serveur en avait 2. Interroger le réseau à chaque
    rafraîchissement serait lent et bavard (D22) : la limite est assumée,
    et l'infobulle la dit.
    """
    from tortoisepy.core.push_state import divergence

    _, moi, autre = _serveur_et_deux_clones(tmp_path)
    (autre / "h.txt").write_text("h\n")
    run_git(autre, "add", ".")
    run_git(autre, "commit", "-q", "-m", "un")
    run_git(autre, "push", "-q", "origin", "HEAD")
    run_git(moi, "fetch", "-q", "origin")

    # Le serveur avance ENCORE, sans que nous le sachions.
    (autre / "i.txt").write_text("i\n")
    run_git(autre, "add", ".")
    run_git(autre, "commit", "-q", "-m", "deux")
    run_git(autre, "push", "-q", "origin", "HEAD")

    assert divergence(pygit2.Repository(str(moi))) == (0, 1), (
        "la valeur reflète la ref de suivi, pas le serveur"
    )


def test_a_branch_without_upstream_has_no_divergence(tmp_path):
    """Review Focus 4 : rien à comparer, donc rien à afficher."""
    from tortoisepy.core.push_state import divergence

    _, moi, _ = _serveur_et_deux_clones(tmp_path)
    run_git(moi, "checkout", "-q", "-b", "orpheline")
    assert divergence(pygit2.Repository(str(moi))) is None


def test_divergence_on_a_detached_head_is_none(tmp_path):
    from tortoisepy.core.push_state import divergence

    _, moi, _ = _serveur_et_deux_clones(tmp_path)
    run_git(moi, "checkout", "-q", "--detach")
    assert divergence(pygit2.Repository(str(moi))) is None
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/core/test_push_state.py -q -k divergence`
Expected: FAIL — `divergence` n'existe pas.

- [ ] **Step 3: Implémenter**

Dans `push_state.py` :

```python
def divergence(repo: pygit2.Repository) -> tuple[int, int] | None:
    """Commits d'avance et de retard sur la branche de suivi.

    `None` quand il n'y a rien à comparer : HEAD détachée, dépôt sans
    commit, ou branche sans upstream — une branche purement locale n'est
    ni en avance ni en retard, elle est ailleurs.

    **La valeur reflète le dernier fetch, pas le serveur** (D22).
    Vérifié : sans nouveau fetch, on annonçait 1 commit de retard là où
    le serveur en avait 2. Interroger le réseau à chaque rafraîchissement
    serait lent et bavard ; l'infobulle dit donc « as of your last
    fetch ».
    """
    if repo.head_is_unborn or repo.head_is_detached:
        return None

    try:
        branch = repo.branches[repo.head.shorthand]
        upstream = branch.upstream
    except (KeyError, pygit2.GitError):
        return None

    if upstream is None:
        return None

    try:
        return repo.ahead_behind(repo.head.target, upstream.target)
    except (pygit2.GitError, KeyError, ValueError):
        return None
```

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/core/test_push_state.py -q`
Expected: PASS.

- [ ] **Step 5: Signaler les fichiers prêts** — ne commite pas.

---

### Task 3: L'interface

**Files:**
- Modify: `src/tortoisepy/ui/commit_window.py`
- Modify: `src/tortoisepy/ui/main_window.py`
- Test: `tests/ui/test_commit_window.py`, `tests/ui/test_main_window.py`

**Interfaces:**
- Consumes: `can_amend`, `amend_commit`, `last_commit_message` (tâche 1),
  `divergence` (tâche 2)

**Vérifié :** `commit_window.py` a `self._message` (QPlainTextEdit),
`self.commit_button`, `self.push_button`, et ses libellés sont **en français**.
`main_window.py` a `self.branch_label` et `_update_branch_label()`.

- [ ] **Step 1: Écrire les tests**

```python
# à ajouter dans tests/ui/test_commit_window.py


def test_ticking_amend_fills_in_the_last_message(window, repo):
    """Corriger une faute suppose de voir le message à corriger."""
    window.amend_box.setChecked(True)
    assert window.message().strip() == "message initial"


def test_unticking_amend_clears_the_borrowed_message(window, repo):
    """Le message emprunté ne doit pas se retrouver sur un commit neuf."""
    window.amend_box.setChecked(True)
    window.amend_box.setChecked(False)
    assert window.message().strip() == ""


def test_the_button_says_amend(window, repo):
    window.amend_box.setChecked(True)
    assert "Amender" in window.commit_button.text()
    window.amend_box.setChecked(False)
    assert window.commit_button.text() == "Commit"


def test_amend_is_disabled_on_a_detached_head(qtbot, tmp_path):
    """Et l'infobulle dit pourquoi, plutôt que de laisser deviner."""
    repo = _repo_with_one_commit(tmp_path)
    run_git(repo.workdir, "checkout", "-q", "--detach")

    fenetre = CommitWindow(pygit2.Repository(repo.path))
    qtbot.addWidget(fenetre)
    assert fenetre.amend_box.isEnabled() is False
    assert "detached" in fenetre.amend_box.toolTip().lower()


def test_amending_commits_through_the_core(window, repo, monkeypatch):
    from tortoisepy.ui import commit_window as module

    vus = []
    monkeypatch.setattr(
        module, "amend_commit",
        lambda repo, paths, message: vus.append((paths, message))
        or succeeded("Amended abc12345"),
    )
    window.amend_box.setChecked(True)
    window.set_message("corrige")
    window.commit()

    assert vus, "le cœur doit être appelé"
    assert vus[0][1] == "corrige"
```

```python
# à ajouter dans tests/ui/test_main_window.py


def test_the_status_bar_shows_the_divergence(window, monkeypatch):
    from tortoisepy.ui import main_window as module

    monkeypatch.setattr(module, "divergence", lambda repo: (2, 1))
    window.refresh()
    assert "↑2" in window.branch_label.text()
    assert "↓1" in window.branch_label.text()


def test_an_up_to_date_branch_shows_no_arrows(window, monkeypatch):
    """Une branche à jour n'a pas besoin d'être commentée."""
    from tortoisepy.ui import main_window as module

    monkeypatch.setattr(module, "divergence", lambda repo: (0, 0))
    window.refresh()
    assert "↑" not in window.branch_label.text()
    assert "↓" not in window.branch_label.text()


def test_the_tooltip_says_the_figure_may_be_stale(window, monkeypatch):
    """Review Focus 2 : un indicateur muet sur sa fraîcheur mentirait."""
    from tortoisepy.ui import main_window as module

    monkeypatch.setattr(module, "divergence", lambda repo: (1, 1))
    window.refresh()
    assert "fetch" in window.branch_label.toolTip().lower()
```

- [ ] **Step 2: Vérifier l'échec**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_commit_window.py tests/ui/test_main_window.py -q -k "amend or divergence or arrows or stale"`
Expected: FAIL — `amend_box` et l'indicateur n'existent pas.

- [ ] **Step 3: La fenêtre de commit**

Imports :

```python
from tortoisepy.core.amend import amend_commit, can_amend, last_commit_message
```

Dans `__init__`, après la création de `self._message` :

```python
        self.amend_box = QCheckBox("Amender le dernier commit")
        raison = can_amend(repository)
        self.amend_box.setEnabled(raison is None)
        if raison is not None:
            # Grisé sans explication n'apprend rien : dire pourquoi.
            self.amend_box.setToolTip(raison)
        self.amend_box.toggled.connect(self._on_amend_toggled)
```

et l'ajouter au `layout` du bas, **avant** le label « Message : ».

Le basculement :

```python
    def _on_amend_toggled(self, coche: bool) -> None:
        """Emprunte le message du dernier commit, ou le rend.

        Corriger une faute suppose de voir ce qu'on corrige. Et décocher
        doit rendre le message emprunté : le laisser le ferait passer
        pour le message d'un commit neuf.
        """
        if coche:
            self._emprunte = self._message.toPlainText()
            self._message.setPlainText(last_commit_message(self.repository))
        else:
            self._message.setPlainText(getattr(self, "_emprunte", ""))
        self.commit_button.setText("Amender" if coche else "Commit")
        self._update_buttons()
```

Initialiser `self._emprunte = ""` dans `__init__`.

`commit()` route :

```python
    def commit(self) -> None:
        paths = self.checked_paths()
        if self.amend_box.isChecked():
            result = amend_commit(self.repository, paths, self.message())
        else:
            result = operations.commit_selection(
                self.repository, paths, self.message()
            )
        if result.success:
            self._try_sync_index_after_commit(paths)
        self._after_commit(result, None)
```

**Attention :** `_update_buttons` exige aujourd'hui au moins un fichier coché.
En amend, **le message seul suffit** — corriger une faute ne touche aucun
fichier. Adapter la condition, sinon le bouton reste inactif dans le cas le
plus courant.

- [ ] **Step 4: L'indicateur**

Dans `main_window.py`, importer `divergence` depuis `core.push_state`, puis
dans `_update_branch_label`, après avoir composé `texte` :

```python
        ecart = divergence(self.repository)
        if ecart is not None and any(ecart):
            avance, retard = ecart
            morceaux = []
            if avance:
                morceaux.append(f"↑{avance}")
            if retard:
                morceaux.append(f"↓{retard}")
            texte += "  " + " ".join(morceaux)
            self.branch_label.setToolTip(
                f"{avance} ahead, {retard} behind — as of your last fetch"
            )
            self.branch_label.setText(texte)
            return
```

**Attention :** `_update_branch_label` se termine déjà par un `setText` et un
`setToolTip` — ne pas les dupliquer, et laisser le chemin sans écart poser
l'infobulle existante.

- [ ] **Step 5: Vérifier le succès**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/ -q`
Expected: PASS.

- [ ] **Step 6: Lecture seule et architecture**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/test_read_only.py tests/test_architecture.py -q`
Expected: PASS.

- [ ] **Step 7: Suite complète**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`
Expected: 886 + ~25 tests. **Deux échecs connus et sans rapport** :
`test_fetch_hides_the_bar_when_done` et `test_worker_reports_its_result`.

- [ ] **Step 8: Signaler les fichiers prêts** — ne commite pas. Donner le
décompte exact.

---

## Fin de phase 12

Le dernier commit se corrige depuis l'application, et la barre de statut dit en
permanence de combien l'on est en avance ou en retard — en disant aussi depuis
quand elle le sait.

**Hors périmètre**, conformément à la spec §7 : amender un ancêtre, changer
l'auteur, interroger le serveur pour l'indicateur, et amender depuis le graphe.
