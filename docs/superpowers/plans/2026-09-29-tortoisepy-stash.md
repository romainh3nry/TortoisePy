# Stash Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mettre son travail de côté et le reprendre, depuis le graphe.

**Architecture:** Un module `core/stash_ops.py` sans Qt, désignant chaque stash
par son **OID** et non par son index (les index glissent). L'interface ajoute
une entrée sur la branche courante et trois entrées sur un nœud de stash ;
elles passent par `actions.py`, qui a déjà le nœud dans son contexte.

**Tech Stack:** Python 3.13, pygit2 1.20.1, PySide6 6.11.2, pytest.

**Spec:** `docs/superpowers/specs/2026-09-29-tortoisepy-stash-design.md`

## Global Constraints

- **Ne jamais lancer de commande git sur CE dépôt** (add, commit, branch,
  checkout, stash, push, reset). L'utilisateur gère git lui-même. `git` dans un
  dépôt jetable sous `tmp_path` est attendu et normal.
- **Ne pas modifier** `src/tortoisepy/ui/theme.py`, `src/tortoisepy/layout/**`,
  `src/tortoisepy/ui/graph_items.py` — le rendu du graphe est validé.
- **Ne pas modifier `core/stashes.py`** : il sert le graphe, pas les
  opérations. Ses tests restent verts.
- `src/tortoisepy/core/**` n'importe jamais Qt (`tests/test_architecture.py`).
- **§7.0** : l'application n'écrit dans un dépôt QUE sur action explicite de
  l'utilisateur dans l'interface. Lister les stashes n'écrit rien.
- Commentaires et docstrings **en français**, expliquant le *pourquoi* ;
  libellés visibles **en anglais**.

## Review Focus

1. **Index glissants** (§3) — agir par index appliquerait le mauvais stash. Tout
   passe par l'OID, et un OID absent refuse explicitement.
2. **Fichier non suivi seul** (D17) — sans `include_untracked`, `repo.stash()`
   lève `NotFoundError('nothing to stash')` alors qu'il y a du travail.
3. **Arbre propre** — `repo.stash()` lève ; l'entrée doit être grisée, et
   l'appel direct refuser proprement.
4. **`pop` en échec** — le stash doit **survivre** ; c'est ce qui rend Pop sans
   danger.
5. **Un nœud de stash n'est pas une branche** — les entrées de branche doivent
   rester grisées dessus, et les entrées de stash ne doivent pas apparaître
   ailleurs.

---

### Task 1: `core/stash_ops.py`

**Files:**
- Create: `src/tortoisepy/core/stash_ops.py`
- Test: `tests/core/test_stash_ops.py`

**Interfaces:**
- Produces:
  - `stash_changes(repo, message=None) -> OperationResult`
  - `apply_stash(repo, oid) -> OperationResult`
  - `pop_stash(repo, oid) -> OperationResult`
  - `drop_stash(repo, oid) -> OperationResult`
  - `index_of(repo, oid) -> int | None`

**Vérifié sur pygit2 1.20 (ne pas redécouvrir) :**
- `repo.stash(stasher, message=None, include_untracked=False, ...) -> Oid` ;
- `repo.stash_apply(index=0, ...)`, `stash_pop(index=0, ...)`,
  `stash_drop(index=0)` — **aucune ne rend de valeur**, elles lèvent ;
- `listall_stashes()` rend des entrées avec `.commit_id` et `.message`, **le
  plus récent en 0** ;
- arbre propre ou non suivi sans l'option ->
  `NotFoundError('cannot stash changes - there is nothing to stash.')` ;
- conflit -> `GitError('1 conflict prevents checkout')`, **dépôt intact**,
  `state()` à 0, stash conservé ;
- `stash_apply` **ne retire pas** le stash.

- [ ] **Step 1: Écrire les tests**

```python
# tests/core/test_stash_ops.py
import os
import subprocess

import pygit2
import pytest

from tortoisepy.core.stash_ops import (
    apply_stash,
    drop_stash,
    index_of,
    pop_stash,
    stash_changes,
)


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
    """Un dépôt avec un commit et deux fichiers suivis."""
    path = tmp_path / "d"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "f.txt").write_text("a\nb\n")
    (path / "g.txt").write_text("x\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "base")
    return pygit2.Repository(str(path))


def _sale(repo, contenu="a\nMODIF\n"):
    """Salit l'arbre de travail."""
    open(os.path.join(repo.workdir, "f.txt"), "w").write(contenu)


def test_stashing_cleans_the_tree(repo):
    _sale(repo)
    result = stash_changes(repo, "mon travail")
    assert result.success is True

    fresh = pygit2.Repository(repo.path)
    assert len(fresh.listall_stashes()) == 1
    assert open(os.path.join(fresh.workdir, "f.txt")).read() == "a\nb\n"


def test_stashing_a_clean_tree_is_refused(repo):
    """Vérifié : pygit2 lève « nothing to stash »."""
    result = stash_changes(repo, "rien")
    assert result.success is False
    assert "nothing to stash" in (result.git_error or "").lower()


def test_an_untracked_file_alone_is_stashed(repo):
    """D17 : sans `include_untracked`, rien ne partait (vérifié)."""
    open(os.path.join(repo.workdir, "neuf.txt"), "w").write("neuf\n")
    result = stash_changes(repo, "fichier neuf")
    assert result.success is True
    assert not os.path.exists(os.path.join(repo.workdir, "neuf.txt"))


def test_the_index_follows_the_oid_not_the_position(repo):
    """Le test central : les index glissent (§3).

    Trois stashes, on retire le premier, et l'OID doit toujours désigner
    le bon — sinon on applique le travail de quelqu'un d'autre.
    """
    oids = []
    for i in (1, 2, 3):
        _sale(repo, f"a\nmodif {i}\n")
        assert stash_changes(repo, f"travail {i}").success is True
        # Le plus récent est en 0 : on relit pour capturer son OID.
        oids.append(str(pygit2.Repository(repo.path).listall_stashes()[0].commit_id))

    fresh = pygit2.Repository(repo.path)
    # Le plus récent est en 0 : `oids[-1]` est donc `stash@{0}`.
    assert index_of(fresh, oids[-1]) == 0
    assert index_of(fresh, oids[0]) == 2

    drop_stash(fresh, oids[-1])

    fresh = pygit2.Repository(repo.path)
    assert index_of(fresh, oids[-1]) is None, "le stash retiré ne doit plus être trouvé"
    assert index_of(fresh, oids[0]) == 1, "l'index a glissé, l'OID doit suivre"


def test_acting_on_an_unknown_oid_is_refused(repo):
    """Plutôt que d'agir au hasard sur un index."""
    _sale(repo)
    stash_changes(repo, "un")
    fresh = pygit2.Repository(repo.path)
    for operation in (apply_stash, pop_stash, drop_stash):
        result = operation(fresh, "0" * 40)
        assert result.success is False
        assert "no longer" in (result.git_error or "").lower()


def test_apply_restores_and_keeps_the_stash(repo):
    _sale(repo)
    stash_changes(repo, "mon travail")
    fresh = pygit2.Repository(repo.path)
    oid = str(fresh.listall_stashes()[0].commit_id)

    result = apply_stash(fresh, oid)
    assert result.success is True
    assert open(os.path.join(fresh.workdir, "f.txt")).read() == "a\nMODIF\n"
    assert len(pygit2.Repository(repo.path).listall_stashes()) == 1, (
        "apply conserve le stash"
    )


def test_pop_restores_and_removes_the_stash(repo):
    _sale(repo)
    stash_changes(repo, "mon travail")
    fresh = pygit2.Repository(repo.path)
    oid = str(fresh.listall_stashes()[0].commit_id)

    result = pop_stash(fresh, oid)
    assert result.success is True
    assert open(os.path.join(fresh.workdir, "f.txt")).read() == "a\nMODIF\n"
    assert pygit2.Repository(repo.path).listall_stashes() == []


def test_a_failed_pop_keeps_the_stash(repo):
    """Review Focus 4 : c'est ce qui rend Pop sans danger."""
    _sale(repo, "a\nSTASH\n")
    stash_changes(repo, "mon travail")
    # On modifie la même ligne autrement : l'application ne peut pas passer.
    _sale(repo, "a\nAUTRE\n")

    fresh = pygit2.Repository(repo.path)
    oid = str(fresh.listall_stashes()[0].commit_id)
    result = pop_stash(fresh, oid)

    assert result.success is False
    fresh = pygit2.Repository(repo.path)
    assert len(fresh.listall_stashes()) == 1, "le stash doit survivre"
    assert open(os.path.join(fresh.workdir, "f.txt")).read() == "a\nAUTRE\n"
    assert int(fresh.state()) == 0, "aucun état conflictuel (§5)"


def test_drop_removes_without_restoring(repo):
    _sale(repo)
    stash_changes(repo, "mon travail")
    fresh = pygit2.Repository(repo.path)
    oid = str(fresh.listall_stashes()[0].commit_id)

    result = drop_stash(fresh, oid)
    assert result.success is True
    fresh = pygit2.Repository(repo.path)
    assert fresh.listall_stashes() == []
    assert open(os.path.join(fresh.workdir, "f.txt")).read() == "a\nb\n", (
        "drop ne restaure rien"
    )
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/core/test_stash_ops.py -q`
Expected: FAIL — le module n'existe pas.

- [ ] **Step 3: Implémenter**

```python
"""Mettre son travail de côté, et le reprendre — phase 11.

`core/stashes.py` dessine les stashes dans le graphe ; ce module agit
dessus. Séparés à dessein : l'un sert l'affichage, l'autre écrit.

**Chaque stash est désigné par son OID, jamais par son index.** Les index
glissent — retirer `stash@{0}` fait de l'ancien `stash@{1}` le nouveau
`stash@{0}` (vérifié). Entre l'affichage du graphe et le clic, la liste
peut avoir changé : agir par index appliquerait alors un autre stash que
celui montré, sans rien signaler.
"""

from __future__ import annotations

import pygit2

from tortoisepy.core.results import OperationResult, failed, guarded, succeeded

_ABSENT = "this stash no longer exists — the list changed since it was shown"


def index_of(repo: pygit2.Repository, oid: str) -> int | None:
    """Position actuelle du stash portant cet OID, ou `None`.

    Relue à chaque appel : c'est tout l'intérêt de passer par l'OID.
    """
    try:
        entries = repo.listall_stashes()
    except (AttributeError, pygit2.GitError):
        return None
    for index, entry in enumerate(entries):
        if str(entry.commit_id) == str(oid):
            return index
    return None


def _signature(repo: pygit2.Repository) -> pygit2.Signature:
    """Signature de l'utilisateur, ou un pis-aller.

    Un dépôt sans `user.name` configuré ne doit pas faire échouer un
    stash : Git lui-même s'en passe pour cette opération locale.

    **Vérifié** : un `user.name` vide lève `InvalidError('failed to parse
    signature')`, qui hérite de `GitError` — le `except` ci-dessous la
    couvre donc. Ne pas resserrer sur `KeyError` seul.
    """
    try:
        return repo.default_signature
    except (KeyError, pygit2.GitError):
        return pygit2.Signature("tortoisePy", "tortoisepy@localhost")


@guarded("Stash")
def stash_changes(
    repo: pygit2.Repository, message: str | None = None
) -> OperationResult:
    """Met de côté les modifications, y compris les fichiers non suivis.

    `include_untracked=True` (D17) : vérifié, sans lui un dossier ne
    contenant que des fichiers neufs répond « nothing to stash » alors
    que l'utilisateur a bien du travail en cours.
    """
    oid = repo.stash(
        _signature(repo), message=message or None, include_untracked=True
    )
    return succeeded(f"Stashed as {str(oid)[:8]}")


@guarded("Stash", changed_on_error=True)
def apply_stash(repo: pygit2.Repository, oid: str) -> OperationResult:
    """Restaure le contenu du stash **sans** le retirer.

    Garder le stash est la raison d'être d'`Apply` face à `Pop` : on peut
    l'appliquer ailleurs, sur une autre branche par exemple.
    """
    index = index_of(repo, oid)
    if index is None:
        return failed("Stash", _ABSENT, repository_changed=False)
    repo.stash_apply(index)
    return succeeded("Stash applied")


@guarded("Stash", changed_on_error=True)
def pop_stash(repo: pygit2.Repository, oid: str) -> OperationResult:
    """Restaure le contenu, puis retire le stash.

    En cas d'échec, **le stash survit** (vérifié) — c'est ce qui rend ce
    geste sans danger.
    """
    index = index_of(repo, oid)
    if index is None:
        return failed("Stash", _ABSENT, repository_changed=False)
    repo.stash_pop(index)
    return succeeded("Stash popped")


@guarded("Stash", changed_on_error=True)
def drop_stash(repo: pygit2.Repository, oid: str) -> OperationResult:
    """Retire le stash **sans** rien restaurer.

    Le seul geste qui détruit du travail sans le rendre : l'interface le
    fait confirmer.
    """
    index = index_of(repo, oid)
    if index is None:
        return failed("Stash", _ABSENT, repository_changed=False)
    repo.stash_drop(index)
    return succeeded("Stash dropped")
```

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/core/test_stash_ops.py tests/core/test_invariants.py -q`
Expected: PASS.

- [ ] **Step 5: Signaler les fichiers prêts** — ne commite pas.

---

### Task 2: Le menu et le routage

**Files:**
- Modify: `src/tortoisepy/ui/context_menu.py`
- Modify: `src/tortoisepy/ui/actions.py`
- Test: `tests/ui/test_context_menu.py`, `tests/ui/test_actions.py`

**Interfaces:**
- Consumes: `stash_changes`, `apply_stash`, `pop_stash`, `drop_stash` (tâche 1)
- Produces: actions `stash_changes`, `apply_stash`, `pop_stash`, `drop_stash`

**Vérifié :** `ActionContext` porte déjà `node` (actions.py:26), donc
`ctx.node.oid` donne l'OID du stash — aucune plomberie nouvelle n'est
nécessaire dans `main_window.py`. `_single_node_menu` expose déjà `dirty`,
`busy`, `is_current` et `node.kind`.

- [ ] **Step 1: Écrire les tests**

```python
# à ajouter dans tests/ui/test_context_menu.py


def _stash_node():
    """Un nœud de stash, comme `core/stashes.py` en produit."""
    oid = "c" * 40
    return DisplayNode(
        oid=oid,
        kind=NodeKind.STASH,
        refs=(Ref("stash@{0}", RefType.STASH, oid),),
    )


def _dirty_on_main():
    return RepositoryState(
        head_oid="a" * 40, head_branch="main", detached=False,
        has_unstaged_changes=True, has_staged_changes=False,
        has_conflicts=False, operation_in_progress=None, conflicted_paths=(),
    )


def test_stashing_is_offered_when_the_tree_is_dirty():
    entries = build_menu_model((_multi_branch_node(),), _dirty_on_main())
    entree = _find(entries, "Stash changes…")
    assert entree is not None
    assert entree.action == "stash_changes"
    assert entree.enabled is True


def test_stashing_is_greyed_out_on_a_clean_tree():
    """`repo.stash()` lèverait « nothing to stash » (vérifié)."""
    entries = build_menu_model((_multi_branch_node(),), _on_main())
    entree = _find(entries, "Stash changes…")
    assert entree is not None
    assert entree.enabled is False


def test_a_stash_node_offers_apply_pop_and_drop():
    entries = build_menu_model((_stash_node(),), _on_main())
    for label, action in (
        ("Apply stash", "apply_stash"),
        ("Pop stash", "pop_stash"),
        ("Drop stash", "drop_stash"),
    ):
        entree = _find(entries, label)
        assert entree is not None, label
        assert entree.action == action
        assert entree.enabled is True


def test_dropping_a_stash_is_confirmed():
    """Le seul geste qui détruit du travail sans le rendre."""
    entries = build_menu_model((_stash_node(),), _on_main())
    assert _find(entries, "Drop stash").needs_confirmation is True
    assert _find(entries, "Apply stash").needs_confirmation is False


def test_stash_entries_are_absent_from_an_ordinary_node():
    """Review Focus 5 : elles n'ont de sens que sur un stash."""
    entries = build_menu_model((_multi_branch_node(),), _on_main())
    for label in ("Apply stash", "Pop stash", "Drop stash"):
        assert _find(entries, label) is None, label
```

```python
# à ajouter dans tests/ui/test_actions.py


def test_the_stash_actions_use_the_node_oid(repo, monkeypatch):
    """Le piège de la phase : agir par index viserait un autre stash."""
    from tortoisepy.core.model import DisplayNode, NodeKind, Ref, RefType
    from tortoisepy.ui import actions as module

    vus = []
    for nom in ("apply_stash", "pop_stash", "drop_stash"):
        monkeypatch.setattr(
            module.stash_ops, nom,
            lambda repo, oid, _n=nom: vus.append((_n, oid)) or None,
        )

    oid = "c" * 40
    stash = DisplayNode(
        oid=oid, kind=NodeKind.STASH,
        refs=(Ref("stash@{0}", RefType.STASH, oid),),
    )
    for nom in ("apply_stash", "pop_stash", "drop_stash"):
        module.execute_action(nom, context(repo, node=stash))

    assert vus == [
        ("apply_stash", oid), ("pop_stash", oid), ("drop_stash", oid)
    ]


def test_every_stash_action_has_a_handler():
    """`test_every_menu_action_has_a_handler` part d'un nœud ordinaire.

    Les entrées de stash n'y apparaissent donc pas : sans ce test, une
    action de stash sans handler passerait inaperçue.
    """
    from tortoisepy.core.model import DisplayNode, NodeKind, Ref, RefType
    from tortoisepy.core.state import RepositoryState
    from tortoisepy.ui.context_menu import build_menu_model

    oid = "c" * 40
    stash = DisplayNode(
        oid=oid, kind=NodeKind.STASH,
        refs=(Ref("stash@{0}", RefType.STASH, oid),),
    )
    state = RepositoryState(
        head_oid="a" * 40, head_branch="main", detached=False,
        has_unstaged_changes=True, has_staged_changes=False,
        has_conflicts=False, operation_in_progress=None, conflicted_paths=(),
    )

    def declarees(entries):
        for entry in entries:
            if entry.action and not entry.is_separator:
                yield entry.action
            yield from declarees(entry.children)

    manquantes = set(declarees(build_menu_model((stash,), state))) - set(
        ACTION_HANDLERS
    )
    assert not manquantes, f"actions sans handler : {sorted(manquantes)}"
```

**Vérifié :** `tests/ui/test_actions.py` fournit `context(repo, **overrides)`
et la fixture `repo` — les tests ci-dessus s'en servent. `ACTION_HANDLERS` y
est déjà importé.

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/ui/test_context_menu.py tests/ui/test_actions.py -q -k stash`
Expected: FAIL — entrées et actions inexistantes.

- [ ] **Step 3: Le menu**

Dans `context_menu.py`, l'entrée de création — au voisinage de « Create », car
mettre de côté est un geste sur l'arbre de travail, pas sur une branche :

```python
        MenuEntry(
            "Stash changes…",
            "stash_changes",
            # Grisé sur un arbre propre : `repo.stash()` lèverait
            # « nothing to stash » (vérifié), et proposer une action qui
            # échouera toujours n'apprend rien.
            enabled=dirty and not busy,
        ),
```

Et, **seulement sur un nœud de stash**, un bloc dédié :

```python
    if node.kind is NodeKind.STASH:
        entries.append(SEPARATOR)
        entries.extend((
            MenuEntry("Apply stash", "apply_stash", enabled=not busy),
            MenuEntry("Pop stash", "pop_stash", enabled=not busy),
            MenuEntry(
                "Drop stash",
                "drop_stash",
                enabled=not busy,
                # Le seul des trois qui détruit du travail sans le rendre.
                needs_confirmation=True,
            ),
        ))
```

- [ ] **Step 4: Le routage**

Dans `actions.py`, importer le module puis :

```python
def _stash_changes(ctx: ActionContext) -> OperationResult | None:
    """Demande un message, puis met de côté."""
    message = ctx.ask_name(ctx.parent, "Stash", "Message (optional):")
    if message is None:
        return None
    return stash_ops.stash_changes(ctx.repository, message)


def _apply_stash(ctx: ActionContext) -> OperationResult | None:
    """Par l'OID du nœud, pas par un index : les index glissent (§3)."""
    return stash_ops.apply_stash(ctx.repository, ctx.node.oid)


def _pop_stash(ctx: ActionContext) -> OperationResult | None:
    return stash_ops.pop_stash(ctx.repository, ctx.node.oid)


def _drop_stash(ctx: ActionContext) -> OperationResult | None:
    return stash_ops.drop_stash(ctx.repository, ctx.node.oid)
```

et les enregistrer :

```python
    "stash_changes": _stash_changes,
    "apply_stash": _apply_stash,
    "pop_stash": _pop_stash,
    "drop_stash": _drop_stash,
```

**Attention :** `ask_name` rend `None` si l'utilisateur annule, et une chaîne
vide devient `None` (vérifié dans `dialogs.py`). Annuler ne doit **rien**
écrire (§7.0) — d'où le `return None` avant tout appel. Un message vide est
légitime pour un stash : `stash_changes` accepte `None`.

- [ ] **Step 5: Vérifier le succès**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/ -q`
Expected: PASS.

- [ ] **Step 6: Lecture seule et architecture**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/test_read_only.py tests/test_architecture.py -q`
Expected: PASS.

- [ ] **Step 7: Suite complète**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`
Expected: 846 + ~15 tests. **Deux échecs connus et sans rapport** :
`test_fetch_hides_the_bar_when_done` et `test_worker_reports_its_result`.

- [ ] **Step 8: Signaler les fichiers prêts** — ne commite pas. Donner le
décompte exact.

---

## Fin de phase 11

Mettre de côté et reprendre se font depuis le graphe, sur le stash qu'on
désigne — et non sur celui qui occupe sa place.

**Hors périmètre**, conformément à la spec §9 : `stash branch`, stash partiel,
`--keep-index`, et toute résolution de conflits (l'application refuse avant de
toucher au dépôt).
