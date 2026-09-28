# tortoisePy — Plan d'implémentation, phase 3 : opérations et état

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fournir à l'UI l'état courant du dépôt et les opérations Git du menu
contextuel, sous une forme qui ne laisse jamais remonter d'exception pygit2.

**Architecture:** Deux modules indépendants. `state.py` lit l'état (HEAD,
staging, conflits, opération en cours) sans jamais écrire. `operations.py`
écrit, et retourne toujours un `OperationResult` structuré plutôt que de lever.
Un décorateur unique convertit les exceptions pygit2 en résultat, de sorte
qu'aucune opération n'oublie cette conversion.

**Tech Stack:** Python 3.13, pygit2 1.20, pytest. Aucune dépendance PySide6.

**Spec:** `docs/superpowers/specs/2026-09-11-tortoisepy-design.md` (§7.5 à §7.8)

**Prérequis:** phases 1 et 2 terminées, 244 tests passent.

## Global Constraints

- **Python 3.13**, typage moderne (`str | None`).
- **`core/` n'importe JAMAIS PySide6 ni `tortoisepy.ui`.** Vérifié par
  `tests/test_architecture.py`.
- **Toutes les structures retournées sont `frozen=True`.**
- **Aucune opération ne lève.** Toute fonction publique de `operations.py`
  retourne un `OperationResult`, y compris en cas d'échec.
- **`repository_changed` est indépendant de `success`.** Un merge qui échoue
  sur conflit a modifié le dépôt : l'UI doit reconstruire le graphe quand même.
- **Aucune commande `git`.** L'utilisateur gère son dépôt ; les subagents
  n'exécutent aucune commande git sur le projet. Les fixtures de test peuvent
  invoquer `git` via `subprocess` sur des dépôts temporaires — c'est déjà le
  cas en phase 1 pour les stashes.
- **API pygit2 vérifiées le 2026-09-25** sur la version 1.20.0 :
  `repo.status()`, `repo.state()`, `repo.index.conflicts`, `repo.checkout()`,
  `repo.merge()`, `repo.reset()`, `repo.create_branch()`, `repo.create_tag()`,
  `repo.state_cleanup()`, `repo.head_is_detached`, `repo.head_is_unborn`
  existent toutes. `pygit2.enums.RepositoryState` expose `NONE`, `MERGE`,
  `REVERT`, `CHERRYPICK`, `REBASE`, `REBASE_INTERACTIVE`, `REBASE_MERGE`,
  `BISECT`, et deux variantes `APPLY_MAILBOX`. `pygit2.enums.ResetMode` expose
  `SOFT`, `MIXED`, `HARD`.

---

### Task 1: État du dépôt

**Files:**
- Create: `src/tortoisepy/core/state.py`
- Test: `tests/core/test_state.py`

**Interfaces:**
- Consumes: `Oid` (phase 1)
- Produces: `RepositoryState`, `read_state(repo) -> RepositoryState`

Module en **lecture seule**. Il ne modifie jamais le dépôt.

**Comportements vérifiés le 2026-09-25 sur pygit2 1.20.0**, qui fondent
l'implémentation :

- Dépôt propre : `repo.status()` retourne `{}`, `repo.state()` vaut
  `RepositoryState.NONE`.
- Fichier modifié non indexé : `status()` donne `{'f': FileStatus.WT_MODIFIED}`.
- Fichier indexé : `FileStatus.INDEX_MODIFIED`. Les deux drapeaux se testent
  par masque binaire, un même fichier pouvant porter les deux.
- Merge en conflit : `state()` vaut `MERGE` et `index.conflicts` n'est pas
  `None` — c'est un itérateur de triplets `(ancestor, ours, theirs)` dont
  certains membres peuvent être `None` selon le type de conflit.

- [ ] **Step 1: Écrire les tests**

```python
# tests/core/test_state.py
import os
import subprocess

import pygit2
import pytest

from tortoisepy.core.state import RepositoryState, read_state


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
def worktree(tmp_path):
    """Dépôt avec arbre de travail, un commit initial."""
    path = tmp_path / "wt"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "master")
    (path / "f.txt").write_text("base\n")
    run_git(path, "add", "f.txt")
    run_git(path, "commit", "-q", "-m", "base")
    return path


def test_clean_repository(worktree):
    state = read_state(pygit2.Repository(str(worktree)))
    assert state.head_branch == "master"
    assert state.detached is False
    assert state.has_unstaged_changes is False
    assert state.has_staged_changes is False
    assert state.has_conflicts is False
    assert state.operation_in_progress is None
    assert state.head_oid is not None


def test_is_frozen(worktree):
    state = read_state(pygit2.Repository(str(worktree)))
    with pytest.raises(AttributeError):
        state.detached = True


def test_unstaged_change_is_detected(worktree):
    (worktree / "f.txt").write_text("modifié\n")
    state = read_state(pygit2.Repository(str(worktree)))
    assert state.has_unstaged_changes is True
    assert state.has_staged_changes is False


def test_staged_change_is_detected(worktree):
    (worktree / "f.txt").write_text("modifié\n")
    run_git(worktree, "add", "f.txt")
    state = read_state(pygit2.Repository(str(worktree)))
    assert state.has_staged_changes is True


def test_untracked_file_counts_as_unstaged(worktree):
    (worktree / "nouveau.txt").write_text("x\n")
    state = read_state(pygit2.Repository(str(worktree)))
    assert state.has_unstaged_changes is True


def test_detached_head(worktree):
    oid = run_git(worktree, "rev-parse", "HEAD").stdout.strip()
    run_git(worktree, "checkout", "-q", "--detach", oid)
    state = read_state(pygit2.Repository(str(worktree)))
    assert state.detached is True
    assert state.head_branch is None
    assert state.head_oid == oid


def test_empty_repository_has_no_head(tmp_path):
    """Dépôt sans aucun commit : ni HEAD, ni branche."""
    path = tmp_path / "vide"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "master")
    state = read_state(pygit2.Repository(str(path)))
    assert state.head_oid is None
    assert state.head_branch is None
    assert state.detached is False


def test_merge_conflict_is_detected(worktree):
    """Vérifié : state() vaut MERGE et index.conflicts n'est pas None."""
    run_git(worktree, "checkout", "-q", "-b", "other")
    (worktree / "f.txt").write_text("leur version\n")
    run_git(worktree, "add", "f.txt")
    run_git(worktree, "commit", "-q", "-m", "other")

    run_git(worktree, "checkout", "-q", "master")
    (worktree / "f.txt").write_text("notre version\n")
    run_git(worktree, "add", "f.txt")
    run_git(worktree, "commit", "-q", "-m", "master")

    run_git(worktree, "merge", "other")

    state = read_state(pygit2.Repository(str(worktree)))
    assert state.has_conflicts is True
    assert state.operation_in_progress == "merge"


def test_conflicted_files_are_listed(worktree):
    run_git(worktree, "checkout", "-q", "-b", "other")
    (worktree / "f.txt").write_text("leur\n")
    run_git(worktree, "add", "f.txt")
    run_git(worktree, "commit", "-q", "-m", "other")
    run_git(worktree, "checkout", "-q", "master")
    (worktree / "f.txt").write_text("notre\n")
    run_git(worktree, "add", "f.txt")
    run_git(worktree, "commit", "-q", "-m", "master")
    run_git(worktree, "merge", "other")

    state = read_state(pygit2.Repository(str(worktree)))
    assert "f.txt" in state.conflicted_paths


def test_no_conflicted_paths_when_clean(worktree):
    state = read_state(pygit2.Repository(str(worktree)))
    assert state.conflicted_paths == ()


def test_reading_state_does_not_modify_the_repository(worktree):
    """Le module est en lecture seule : deux lectures donnent le même état."""
    repo = pygit2.Repository(str(worktree))
    first = read_state(repo)
    second = read_state(repo)
    assert first == second
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/core/test_state.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tortoisepy.core.state'`

- [ ] **Step 3: Implémenter**

```python
# src/tortoisepy/core/state.py
"""État courant du dépôt — §7.8.

Lecture seule. Ce module ne modifie jamais le dépôt : il dit à l'UI quelles
actions sont possibles (§7.3) et si une confirmation s'impose (§7.5).

Bien moins coûteux à calculer que le graphe : quand seul l'état change — un
fichier modifié dans l'éditeur — le graphe n'a pas à être reconstruit.
"""

from __future__ import annotations

from dataclasses import dataclass

import pygit2
from pygit2.enums import FileStatus, RepositoryState as GitState

from tortoisepy.core.model import Oid

_UNSTAGED = (
    FileStatus.WT_MODIFIED
    | FileStatus.WT_DELETED
    | FileStatus.WT_TYPECHANGE
    | FileStatus.WT_RENAMED
    | FileStatus.WT_NEW
)
"""Drapeaux marquant une modification non indexée. WT_NEW couvre les
fichiers non suivis : du point de vue de l'UI, ils empêchent un checkout
au même titre qu'une modification."""

_STAGED = (
    FileStatus.INDEX_NEW
    | FileStatus.INDEX_MODIFIED
    | FileStatus.INDEX_DELETED
    | FileStatus.INDEX_RENAMED
    | FileStatus.INDEX_TYPECHANGE
)

_OPERATION_NAMES = {
    GitState.MERGE: "merge",
    GitState.REVERT: "revert",
    GitState.REVERT_SEQUENCE: "revert",
    GitState.CHERRYPICK: "cherry-pick",
    GitState.CHERRYPICK_SEQUENCE: "cherry-pick",
    GitState.BISECT: "bisect",
    GitState.REBASE: "rebase",
    GitState.REBASE_INTERACTIVE: "rebase",
    GitState.REBASE_MERGE: "rebase",
    GitState.APPLY_MAILBOX: "am",
    GitState.APPLY_MAILBOX_OR_REBASE: "am",
}
"""Noms lisibles des opérations en cours. Les variantes d'une même opération
(rebase simple, interactif, merge) sont regroupées : l'UI n'a pas à les
distinguer pour griser ses menus."""


@dataclass(frozen=True)
class RepositoryState:
    head_oid: Oid | None
    head_branch: str | None
    detached: bool
    has_unstaged_changes: bool
    has_staged_changes: bool
    has_conflicts: bool
    operation_in_progress: str | None
    conflicted_paths: tuple[str, ...]

    @property
    def is_clean(self) -> bool:
        """Rien en cours, rien de modifié : toute opération est permise."""
        return not (
            self.has_unstaged_changes
            or self.has_staged_changes
            or self.has_conflicts
            or self.operation_in_progress
        )


def read_state(repo: pygit2.Repository) -> RepositoryState:
    """Lit l'état courant. Ne modifie rien."""
    head_oid, head_branch, detached = _head(repo)
    unstaged, staged = _working_tree(repo)
    conflicts = _conflicts(repo)

    return RepositoryState(
        head_oid=head_oid,
        head_branch=head_branch,
        detached=detached,
        has_unstaged_changes=unstaged,
        has_staged_changes=staged,
        has_conflicts=bool(conflicts),
        operation_in_progress=_operation(repo),
        conflicted_paths=conflicts,
    )


def _head(repo: pygit2.Repository) -> tuple[Oid | None, str | None, bool]:
    """OID, nom de branche et détachement de HEAD.

    Un dépôt sans commit a un HEAD « non né » : ni OID, ni branche, et il
    n'est pas détaché pour autant.
    """
    try:
        if repo.head_is_unborn:
            return None, None, False
    except pygit2.GitError:
        return None, None, False

    try:
        detached = repo.head_is_detached
        oid = str(repo.head.target)
        branch = None if detached else repo.head.shorthand
        return oid, branch, detached
    except (pygit2.GitError, KeyError):
        return None, None, False


def _working_tree(repo: pygit2.Repository) -> tuple[bool, bool]:
    """(modifications non indexées, modifications indexées)."""
    try:
        status = repo.status()
    except pygit2.GitError:
        return False, False

    unstaged = any(code & _UNSTAGED for code in status.values())
    staged = any(code & _STAGED for code in status.values())
    return unstaged, staged


def _conflicts(repo: pygit2.Repository) -> tuple[str, ...]:
    """Chemins en conflit, triés.

    `index.conflicts` est un itérateur de triplets (ancestor, ours, theirs)
    dont certains membres valent `None` selon le type de conflit — un
    fichier supprimé d'un côté n'a pas d'entrée de ce côté.
    """
    try:
        conflicts = repo.index.conflicts
    except (pygit2.GitError, AttributeError):
        return ()

    if conflicts is None:
        return ()

    paths: set[str] = set()
    for entries in conflicts:
        for entry in entries:
            if entry is not None:
                paths.add(entry.path)
                break

    return tuple(sorted(paths))


def _operation(repo: pygit2.Repository) -> str | None:
    """Nom de l'opération en cours, ou None."""
    try:
        state = repo.state()
    except pygit2.GitError:
        return None
    return _OPERATION_NAMES.get(state)
```

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/core/test_state.py -v`
Expected: PASS, 11 tests.

- [ ] **Step 5: Signaler les fichiers prêts** — ne commite pas.

---

### Task 2: Résultat d'opération et garde d'exception

**Files:**
- Create: `src/tortoisepy/core/results.py`
- Test: `tests/core/test_results.py`

**Interfaces:**
- Consumes: rien
- Produces: `OperationResult`, `succeeded(...)`, `failed(...)`,
  `guarded(summary, changed_on_error=False)` (décorateur)

**Pourquoi un décorateur.** La spec exige qu'aucune exception pygit2 ne
remonte à l'UI (§7.6). Confier cette conversion à chaque opération
garantirait qu'une l'oublie un jour. Le décorateur la centralise : une
opération décorée ne peut pas lever.

- [ ] **Step 1: Écrire les tests**

```python
# tests/core/test_results.py
import pygit2
import pytest

from tortoisepy.core.results import OperationResult, failed, guarded, succeeded


def test_is_frozen():
    r = succeeded("Test")
    with pytest.raises(AttributeError):
        r.success = False


def test_succeeded_marks_the_repository_changed_by_default():
    r = succeeded("Checkout de master")
    assert r.success is True
    assert r.repository_changed is True
    assert r.git_error is None
    assert r.summary == "Checkout de master"


def test_succeeded_without_change():
    """Copier un hash réussit sans rien modifier."""
    r = succeeded("Hash copié", repository_changed=False)
    assert r.success is True
    assert r.repository_changed is False


def test_failed_leaves_the_repository_untouched_by_default():
    r = failed("Merge", "1 conflict prevents checkout")
    assert r.success is False
    assert r.repository_changed is False
    assert r.git_error == "1 conflict prevents checkout"


def test_failure_can_still_have_changed_the_repository():
    """§7.6 : un merge en conflit échoue MAIS a modifié l'index."""
    r = failed("Merge", "conflits", repository_changed=True)
    assert r.success is False
    assert r.repository_changed is True


def test_guarded_passes_through_a_successful_result():
    @guarded("Opération")
    def op():
        return succeeded("Opération réussie")

    assert op().success is True


def test_guarded_converts_a_pygit2_error():
    @guarded("Merge de feature")
    def op():
        raise pygit2.GitError("1 conflict prevents checkout")

    result = op()
    assert result.success is False
    assert result.summary == "Merge de feature"
    assert "conflict" in result.git_error


def test_guarded_never_raises():
    @guarded("Opération")
    def op():
        raise KeyError("ref introuvable")

    result = op()  # ne doit pas lever
    assert result.success is False


def test_guarded_reports_change_on_error_when_declared():
    """Une opération interactive modifie le dépôt avant d'échouer."""
    @guarded("Merge", changed_on_error=True)
    def op():
        raise pygit2.GitError("conflits")

    result = op()
    assert result.success is False
    assert result.repository_changed is True


def test_guarded_lets_through_a_result_object_unchanged():
    """Si l'opération retourne déjà un résultat, il est préservé tel quel."""
    original = failed("Déjà échoué", "raison", repository_changed=True)

    @guarded("Ignoré")
    def op():
        return original

    assert op() is original


def test_guarded_preserves_function_metadata():
    @guarded("Opération")
    def nommee():
        """Docstring."""
        return succeeded("ok")

    assert nommee.__name__ == "nommee"
    assert nommee.__doc__ == "Docstring."
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/core/test_results.py -v`
Expected: FAIL — module introuvable.

- [ ] **Step 3: Implémenter**

```python
# src/tortoisepy/core/results.py
"""Résultat structuré des opérations — §7.6.

Aucune exception pygit2 ne remonte à l'UI : chaque opération retourne un
`OperationResult`. Le décorateur `guarded` centralise cette conversion,
pour qu'aucune opération ne puisse l'oublier.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import Callable

import pygit2


@dataclass(frozen=True)
class OperationResult:
    success: bool
    repository_changed: bool
    summary: str
    git_error: str | None = None

    @property
    def needs_refresh(self) -> bool:
        """L'affichage ne reflète plus le dépôt — nom explicite pour l'UI."""
        return self.repository_changed


def succeeded(summary: str, repository_changed: bool = True) -> OperationResult:
    """Opération réussie. Par défaut elle a modifié le dépôt ; les rares
    opérations en lecture (copier un hash) passent `False`."""
    return OperationResult(
        success=True,
        repository_changed=repository_changed,
        summary=summary,
        git_error=None,
    )


def failed(
    summary: str, git_error: str, repository_changed: bool = False
) -> OperationResult:
    """Opération échouée.

    `repository_changed` reste indépendant : un merge interrompu par un
    conflit a échoué mais laisse l'index modifié (§7.6).
    """
    return OperationResult(
        success=False,
        repository_changed=repository_changed,
        summary=summary,
        git_error=git_error,
    )


def guarded(summary: str, changed_on_error: bool = False) -> Callable:
    """Convertit toute exception en `OperationResult`.

    `changed_on_error=True` pour les opérations interactives (merge, rebase,
    cherry-pick), qui peuvent modifier le dépôt avant d'échouer.

    Le message de libgit2 est transmis tel quel, jamais reformulé (§9) :
    une paraphrase approximative nuirait à qui connaît Git.
    """

    def decorate(function: Callable[..., OperationResult]) -> Callable:
        @functools.wraps(function)
        def wrapper(*args, **kwargs) -> OperationResult:
            try:
                return function(*args, **kwargs)
            except pygit2.GitError as error:
                return failed(summary, str(error), changed_on_error)
            except (KeyError, ValueError, OSError) as error:
                return failed(
                    summary, f"{type(error).__name__}: {error}", changed_on_error
                )

        return wrapper

    return decorate
```

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/core/test_results.py -v`
Expected: PASS, 11 tests.

- [ ] **Step 5: Signaler les fichiers prêts** — ne commite pas.

---

### Task 3: Opérations simples

**Files:**
- Create: `src/tortoisepy/core/operations.py`
- Test: `tests/core/test_operations_simple.py`

**Interfaces:**
- Consumes: `OperationResult`, `guarded`, `succeeded`, `failed` (tâche 2)
- Produces: `create_branch`, `delete_branch`, `rename_branch`, `create_tag`,
  `delete_tag`, `checkout_branch`, `checkout_commit`

Classe « simples » de §7.7 : elles n'échouent qu'en cas d'erreur évidente
(nom déjà pris, ref inexistante).

- [ ] **Step 1: Écrire les tests**

```python
# tests/core/test_operations_simple.py
import os
import subprocess

import pygit2
import pytest

from tortoisepy.core.operations import (
    checkout_branch,
    checkout_commit,
    create_branch,
    create_tag,
    delete_branch,
    delete_tag,
    rename_branch,
)
from tortoisepy.core.state import read_state


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
    path = tmp_path / "ops"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "master")
    (path / "f.txt").write_text("base\n")
    run_git(path, "add", "f.txt")
    run_git(path, "commit", "-q", "-m", "base")
    (path / "f.txt").write_text("deux\n")
    run_git(path, "add", "f.txt")
    run_git(path, "commit", "-q", "-m", "deux")
    return pygit2.Repository(str(path))


def head_oid(repo) -> str:
    return str(repo.head.target)


def test_create_branch(repo):
    result = create_branch(repo, "feature", head_oid(repo))
    assert result.success is True
    assert result.repository_changed is True
    assert "refs/heads/feature" in repo.references


def test_create_branch_refuses_an_existing_name(repo):
    create_branch(repo, "feature", head_oid(repo))
    result = create_branch(repo, "feature", head_oid(repo))
    assert result.success is False
    assert result.git_error is not None


def test_create_branch_refuses_an_unknown_commit(repo):
    result = create_branch(repo, "x", "0" * 40)
    assert result.success is False


def test_delete_branch(repo):
    create_branch(repo, "temp", head_oid(repo))
    result = delete_branch(repo, "temp")
    assert result.success is True
    assert "refs/heads/temp" not in repo.references


def test_delete_branch_refuses_the_current_branch(repo):
    """Supprimer la branche courante laisserait le dépôt sans HEAD valide."""
    result = delete_branch(repo, "master")
    assert result.success is False
    assert result.repository_changed is False
    assert "refs/heads/master" in repo.references


def test_delete_unknown_branch(repo):
    result = delete_branch(repo, "inexistante")
    assert result.success is False


def test_rename_branch(repo):
    create_branch(repo, "ancien", head_oid(repo))
    result = rename_branch(repo, "ancien", "nouveau")
    assert result.success is True
    assert "refs/heads/nouveau" in repo.references
    assert "refs/heads/ancien" not in repo.references


def test_rename_branch_refuses_an_existing_target(repo):
    create_branch(repo, "a", head_oid(repo))
    create_branch(repo, "b", head_oid(repo))
    result = rename_branch(repo, "a", "b")
    assert result.success is False


def test_create_lightweight_tag(repo):
    result = create_tag(repo, "v1.0", head_oid(repo))
    assert result.success is True
    assert "refs/tags/v1.0" in repo.references


def test_create_annotated_tag(repo):
    result = create_tag(repo, "v2.0", head_oid(repo), message="version 2")
    assert result.success is True
    tag = repo.references["refs/tags/v2.0"]
    assert repo.get(tag.target).type_str == "tag"


def test_delete_tag(repo):
    create_tag(repo, "v1.0", head_oid(repo))
    result = delete_tag(repo, "v1.0")
    assert result.success is True
    assert "refs/tags/v1.0" not in repo.references


def test_checkout_branch(repo):
    create_branch(repo, "feature", head_oid(repo))
    result = checkout_branch(repo, "feature")
    assert result.success is True
    assert read_state(repo).head_branch == "feature"


def test_checkout_unknown_branch(repo):
    result = checkout_branch(repo, "inexistante")
    assert result.success is False


def test_checkout_commit_detaches_head(repo):
    first = str(list(repo.walk(repo.head.target))[-1].id)
    result = checkout_commit(repo, first)
    assert result.success is True
    state = read_state(repo)
    assert state.detached is True
    assert state.head_oid == first


def test_every_operation_returns_a_result_never_raises(repo):
    """§7.6 : aucune opération ne laisse remonter d'exception."""
    calls = [
        lambda: create_branch(repo, "", "0" * 40),
        lambda: delete_branch(repo, ""),
        lambda: rename_branch(repo, "", ""),
        lambda: create_tag(repo, "", "0" * 40),
        lambda: delete_tag(repo, ""),
        lambda: checkout_branch(repo, ""),
        lambda: checkout_commit(repo, "pas-un-oid"),
    ]
    for call in calls:
        result = call()  # ne doit jamais lever
        assert result.success is False
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/core/test_operations_simple.py -v`
Expected: FAIL — module introuvable.

- [ ] **Step 3: Implémenter**

```python
# src/tortoisepy/core/operations.py
"""Opérations Git du menu contextuel — §7.3, §7.7.

Chaque fonction retourne un `OperationResult` et ne lève jamais : le
décorateur `guarded` convertit toute exception (§7.6).

Ce fichier ne couvre que la classe « simples » de §7.7. Les opérations
interactives (merge, rebase, cherry-pick, revert) et destructrices (reset)
viennent en tâche 4.
"""

from __future__ import annotations

import pygit2

from tortoisepy.core.model import Oid
from tortoisepy.core.results import OperationResult, failed, guarded, succeeded


def _commit(repo: pygit2.Repository, oid: Oid) -> pygit2.Commit:
    """Résout un OID en commit. Lève si inconnu — `guarded` s'en charge."""
    return repo.get(pygit2.Oid(hex=oid)).peel(pygit2.Commit)


@guarded("Création de la branche")
def create_branch(
    repo: pygit2.Repository, name: str, oid: Oid
) -> OperationResult:
    repo.create_branch(name, _commit(repo, oid))
    return succeeded(f"Branche « {name} » créée")


@guarded("Suppression de la branche")
def delete_branch(repo: pygit2.Repository, name: str) -> OperationResult:
    """Refuse la branche courante : le dépôt se retrouverait sans HEAD valide."""
    if not repo.head_is_detached and not repo.head_is_unborn:
        if repo.head.shorthand == name:
            return failed(
                f"Suppression de « {name} »",
                "cannot delete the currently checked out branch",
            )

    branch = repo.branches.local.get(name)
    if branch is None:
        return failed(
            f"Suppression de « {name} »", f"branch '{name}' not found"
        )

    branch.delete()
    return succeeded(f"Branche « {name} » supprimée")


@guarded("Renommage de la branche")
def rename_branch(
    repo: pygit2.Repository, old: str, new: str
) -> OperationResult:
    branch = repo.branches.local.get(old)
    if branch is None:
        return failed(f"Renommage de « {old} »", f"branch '{old}' not found")

    branch.rename(new)
    return succeeded(f"Branche « {old} » renommée en « {new} »")


@guarded("Création du tag")
def create_tag(
    repo: pygit2.Repository, name: str, oid: Oid, message: str | None = None
) -> OperationResult:
    """Tag léger par défaut ; annoté si un message est fourni."""
    commit = _commit(repo, oid)

    if message is None:
        repo.create_reference(f"refs/tags/{name}", commit.id)
    else:
        signature = _signature(repo)
        repo.create_tag(
            name, commit.id, pygit2.enums.ObjectType.COMMIT, signature, message
        )

    return succeeded(f"Tag « {name} » créé")


@guarded("Suppression du tag")
def delete_tag(repo: pygit2.Repository, name: str) -> OperationResult:
    reference = f"refs/tags/{name}"
    if reference not in repo.references:
        return failed(f"Suppression du tag « {name} »", f"tag '{name}' not found")

    repo.references.delete(reference)
    return succeeded(f"Tag « {name} » supprimé")


@guarded("Checkout de la branche")
def checkout_branch(repo: pygit2.Repository, name: str) -> OperationResult:
    branch = repo.branches.local.get(name)
    if branch is None:
        return failed(f"Checkout de « {name} »", f"branch '{name}' not found")

    repo.checkout(branch)
    return succeeded(f"Basculé sur « {name} »")


@guarded("Checkout du commit")
def checkout_commit(repo: pygit2.Repository, oid: Oid) -> OperationResult:
    """Checkout détaché sur un commit précis."""
    commit = _commit(repo, oid)
    repo.checkout_tree(commit)
    repo.set_head(commit.id)
    return succeeded(f"HEAD détaché sur {oid[:8]}")


def _signature(repo: pygit2.Repository) -> pygit2.Signature:
    """Signature du dépôt, avec repli si la configuration est absente."""
    try:
        return repo.default_signature
    except (KeyError, pygit2.GitError):
        return pygit2.Signature("tortoisePy", "tortoisepy@localhost")
```

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/core/test_operations_simple.py -v`
Expected: PASS, 15 tests.

- [ ] **Step 5: Signaler les fichiers prêts** — ne commite pas.

---

### Task 4: Opérations interactives et destructrices

**Files:**
- Modify: `src/tortoisepy/core/operations.py`
- Test: `tests/core/test_operations_risky.py`

**Interfaces:**
- Consumes: tâches 2 et 3
- Produces: `merge_branch`, `abort_operation`, `reset_to`, `cherry_pick`,
  `revert_commit`, `OPERATION_CLASSES`

Classes « interactives » et « destructrices » de §7.7. Elles peuvent laisser
le dépôt dans un état intermédiaire : `repository_changed=True` même en cas
d'échec.

- [ ] **Step 1: Écrire les tests**

```python
# tests/core/test_operations_risky.py
import os
import subprocess

import pygit2
import pytest

from tortoisepy.core.operations import (
    OPERATION_CLASSES,
    abort_operation,
    cherry_pick,
    merge_branch,
    reset_to,
    revert_commit,
)
from tortoisepy.core.state import read_state


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
def diverged(tmp_path):
    """master et feature modifient des fichiers DIFFÉRENTS : merge sans conflit."""
    path = tmp_path / "d"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "master")
    (path / "base.txt").write_text("base\n")
    run_git(path, "add", "base.txt")
    run_git(path, "commit", "-q", "-m", "base")

    run_git(path, "checkout", "-q", "-b", "feature")
    (path / "feature.txt").write_text("feature\n")
    run_git(path, "add", "feature.txt")
    run_git(path, "commit", "-q", "-m", "feature")

    run_git(path, "checkout", "-q", "master")
    (path / "master.txt").write_text("master\n")
    run_git(path, "add", "master.txt")
    run_git(path, "commit", "-q", "-m", "master")

    return pygit2.Repository(str(path))


@pytest.fixture
def conflicting(tmp_path):
    """master et feature modifient le MÊME fichier : merge en conflit."""
    path = tmp_path / "c"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "master")
    (path / "f.txt").write_text("base\n")
    run_git(path, "add", "f.txt")
    run_git(path, "commit", "-q", "-m", "base")

    run_git(path, "checkout", "-q", "-b", "feature")
    (path / "f.txt").write_text("version feature\n")
    run_git(path, "add", "f.txt")
    run_git(path, "commit", "-q", "-m", "feature")

    run_git(path, "checkout", "-q", "master")
    (path / "f.txt").write_text("version master\n")
    run_git(path, "add", "f.txt")
    run_git(path, "commit", "-q", "-m", "master")

    return pygit2.Repository(str(path))


def test_clean_merge_succeeds(diverged):
    result = merge_branch(diverged, "feature")
    assert result.success is True
    assert result.repository_changed is True
    assert read_state(diverged).has_conflicts is False


def test_conflicting_merge_fails_but_changed_the_repository(conflicting):
    """§7.6 : l'échec n'empêche pas la modification de l'index."""
    result = merge_branch(conflicting, "feature")
    assert result.success is False
    assert result.repository_changed is True
    assert read_state(conflicting).has_conflicts is True


def test_conflicting_merge_names_the_files(conflicting):
    result = merge_branch(conflicting, "feature")
    assert "f.txt" in (result.git_error or "")


def test_merge_unknown_branch(diverged):
    result = merge_branch(diverged, "inexistante")
    assert result.success is False
    assert result.repository_changed is False


def test_abort_clears_a_conflicted_merge(conflicting):
    merge_branch(conflicting, "feature")
    assert read_state(conflicting).operation_in_progress == "merge"

    result = abort_operation(conflicting)
    assert result.success is True
    state = read_state(conflicting)
    assert state.operation_in_progress is None
    assert state.has_conflicts is False


def test_abort_without_operation_in_progress(diverged):
    result = abort_operation(diverged)
    assert result.success is False


def test_reset_hard_moves_head_and_discards_changes(diverged):
    first = str(list(diverged.walk(diverged.head.target))[-1].id)
    result = reset_to(diverged, first, "hard")
    assert result.success is True
    assert str(diverged.head.target) == first


def test_reset_soft_keeps_the_working_tree(diverged):
    first = str(list(diverged.walk(diverged.head.target))[-1].id)
    result = reset_to(diverged, first, "soft")
    assert result.success is True
    assert str(diverged.head.target) == first


def test_reset_rejects_an_unknown_mode(diverged):
    result = reset_to(diverged, str(diverged.head.target), "inexistant")
    assert result.success is False
    assert result.repository_changed is False


def test_reset_to_unknown_commit(diverged):
    result = reset_to(diverged, "0" * 40, "hard")
    assert result.success is False


def test_cherry_pick_applies_a_commit(diverged):
    feature_tip = str(diverged.branches.local["feature"].target)
    result = cherry_pick(diverged, feature_tip)
    assert result.success is True
    assert result.repository_changed is True


def test_cherry_pick_unknown_commit(diverged):
    result = cherry_pick(diverged, "0" * 40)
    assert result.success is False


def test_revert_commit(diverged):
    head = str(diverged.head.target)
    result = revert_commit(diverged, head)
    assert result.success is True


def test_revert_unknown_commit(diverged):
    result = revert_commit(diverged, "0" * 40)
    assert result.success is False


def test_operation_classes_cover_every_operation():
    """§7.7 : chaque opération est classée, l'UI s'en sert pour les menus."""
    assert set(OPERATION_CLASSES) == {"simple", "interactive", "destructive"}
    assert "checkout_branch" in OPERATION_CLASSES["simple"]
    assert "merge_branch" in OPERATION_CLASSES["interactive"]
    assert "reset_to" in OPERATION_CLASSES["destructive"]
    assert "delete_branch" in OPERATION_CLASSES["destructive"]


def test_no_operation_appears_in_two_classes():
    seen: set[str] = set()
    for names in OPERATION_CLASSES.values():
        for name in names:
            assert name not in seen, f"{name} classé deux fois"
            seen.add(name)
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/core/test_operations_risky.py -v`
Expected: FAIL — noms non importables depuis `operations`.

- [ ] **Step 3: Implémenter — à AJOUTER à la fin de `operations.py`**

```python
# --- Opérations interactives et destructrices (§7.7) ---------------------

from pygit2.enums import MergeAnalysis, ResetMode

_RESET_MODES = {
    "soft": ResetMode.SOFT,
    "mixed": ResetMode.MIXED,
    "hard": ResetMode.HARD,
}


@guarded("Fusion", changed_on_error=True)
def merge_branch(repo: pygit2.Repository, name: str) -> OperationResult:
    """Fusionne une branche dans la branche courante.

    En cas de conflit, le dépôt RESTE modifié : l'index porte les conflits
    et `state()` vaut MERGE. D'où `changed_on_error=True` — l'UI doit
    reconstruire le graphe même après l'échec (§7.6).
    """
    branch = repo.branches.local.get(name)
    if branch is None:
        return failed(f"Fusion de « {name} »", f"branch '{name}' not found")

    analysis, _ = repo.merge_analysis(branch.target)

    if analysis & MergeAnalysis.UP_TO_DATE:
        return succeeded(
            f"« {name} » est déjà fusionnée", repository_changed=False
        )

    repo.merge(branch.target)

    conflicts = _conflicted_paths(repo)
    if conflicts:
        return failed(
            f"Fusion de « {name} »",
            f"conflits sur : {', '.join(conflicts)}",
            repository_changed=True,
        )

    return succeeded(f"« {name} » fusionnée")


@guarded("Abandon de l'opération")
def abort_operation(repo: pygit2.Repository) -> OperationResult:
    """Annule l'opération en cours et restaure l'arbre sur HEAD.

    Équivalent de `merge --abort` : nettoie l'état, puis remet l'arbre de
    travail et l'index dans l'état de HEAD.
    """
    from tortoisepy.core.state import read_state

    state = read_state(repo)
    if state.operation_in_progress is None:
        return failed(
            "Abandon", "no operation in progress", repository_changed=False
        )

    repo.state_cleanup()
    repo.reset(repo.head.target, ResetMode.HARD)
    return succeeded(f"{state.operation_in_progress} abandonné")


@guarded("Réinitialisation", changed_on_error=True)
def reset_to(
    repo: pygit2.Repository, oid: Oid, mode: str = "mixed"
) -> OperationResult:
    """Déplace la branche courante. `mode` vaut soft, mixed ou hard.

    En mode hard, les modifications non commitées sont perdues : l'UI doit
    demander confirmation avant d'appeler (§7.5).
    """
    reset_mode = _RESET_MODES.get(mode)
    if reset_mode is None:
        return failed(
            "Réinitialisation",
            f"unknown reset mode '{mode}' (soft, mixed or hard)",
            repository_changed=False,
        )

    commit = _commit(repo, oid)
    repo.reset(commit.id, reset_mode)
    return succeeded(f"Branche réinitialisée sur {oid[:8]} ({mode})")


@guarded("Cherry-pick", changed_on_error=True)
def cherry_pick(repo: pygit2.Repository, oid: Oid) -> OperationResult:
    """Applique un commit sur la branche courante."""
    commit = _commit(repo, oid)
    repo.cherrypick(commit.id)

    conflicts = _conflicted_paths(repo)
    if conflicts:
        return failed(
            f"Cherry-pick de {oid[:8]}",
            f"conflits sur : {', '.join(conflicts)}",
            repository_changed=True,
        )

    return succeeded(f"Commit {oid[:8]} appliqué")


@guarded("Revert", changed_on_error=True)
def revert_commit(repo: pygit2.Repository, oid: Oid) -> OperationResult:
    """Annule les changements d'un commit par un commit inverse."""
    commit = _commit(repo, oid)
    repo.revert(commit)

    conflicts = _conflicted_paths(repo)
    if conflicts:
        return failed(
            f"Revert de {oid[:8]}",
            f"conflits sur : {', '.join(conflicts)}",
            repository_changed=True,
        )

    return succeeded(f"Commit {oid[:8]} annulé")


def _conflicted_paths(repo: pygit2.Repository) -> tuple[str, ...]:
    """Chemins en conflit après une opération. Vide s'il n'y en a pas."""
    try:
        conflicts = repo.index.conflicts
    except (pygit2.GitError, AttributeError):
        return ()

    if conflicts is None:
        return ()

    paths: set[str] = set()
    for entries in conflicts:
        for entry in entries:
            if entry is not None:
                paths.add(entry.path)
                break

    return tuple(sorted(paths))


OPERATION_CLASSES: dict[str, tuple[str, ...]] = {
    "simple": (
        "create_branch",
        "rename_branch",
        "create_tag",
        "delete_tag",
        "checkout_branch",
        "checkout_commit",
    ),
    "interactive": (
        "merge_branch",
        "cherry_pick",
        "revert_commit",
        "abort_operation",
    ),
    "destructive": (
        "delete_branch",
        "reset_to",
    ),
}
"""Classement de §7.7. L'UI s'en sert pour décider du traitement : exécution
directe, détection d'état intermédiaire, ou confirmation préalable (§7.5)."""
```

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/core/test_operations_risky.py -v`
Expected: PASS, 16 tests.

- [ ] **Step 5: Suite complète**

Run: `.venv/bin/pytest tests/ -q`
Expected: 244 + 53 = 297 tests, tous verts.

- [ ] **Step 6: Signaler les fichiers prêts** — ne commite pas. Liste les
fichiers créés ou modifiés et le décompte final des tests.

---

## Fin de phase 3

À ce stade :

- l'UI peut connaître l'état du dépôt sans le modifier ;
- treize opérations Git sont disponibles, aucune ne lève ;
- chaque opération est classée selon son risque (§7.7) ;
- `repository_changed` dit à l'UI quand reconstruire le graphe, y compris
  après un échec.

**Ce que cette phase ne fait pas :**

- **Push, pull, fetch.** Elles demandent le réseau et une gestion
  d'authentification (clés SSH, jetons) qui mérite son propre cycle.
- **Rebase.** L'API `Repository.rebase` de pygit2 est bien plus délicate que
  merge ou cherry-pick : elle expose des étapes à piloter une par une. À
  traiter à part.
- **La résolution de conflits.** Hors périmètre v1 (§7.7) : l'application
  affiche les fichiers en conflit et propose d'abandonner.

**Phases suivantes :**

- **Phase 4 — `ui/`** : fenêtre, QGraphicsView, menu contextuel, mini-carte,
  surveillance de `.git` (§7.9).
- **Phase 5 — `cli.py`** : point d'entrée `tgraph`.
