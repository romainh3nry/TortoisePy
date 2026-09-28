# tortoisePy — Plan d'implémentation, phase 5 : câblage des actions

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rendre le menu contextuel opérant — Checkout, Merge, Reset, création
de branches et de tags — avec confirmations et messages d'erreur, sans jamais
écrire dans le dépôt sans clic explicite.

**Architecture:** Un module `ui/dialogs.py` pour les saisies et confirmations,
un `ui/actions.py` qui relie une entrée de menu à son opération `core`. La
fenêtre n'appelle jamais pygit2 : elle passe par `core.operations`, qui
retourne un `OperationResult`.

**Tech Stack:** Python 3.13, PySide6 6.11, pytest-qt.

**Spec:** `docs/superpowers/specs/2026-09-11-tortoisepy-design.md`
(§7.0, §7.3, §7.5, §7.6, §7.9, §9)

**Prérequis:** phases 1 à 4 terminées, 448 tests passent.

## Global Constraints

- **Rien ne s'écrit sans clic explicite (§7.0).** C'est l'exigence la plus
  forte du projet. Les tests de `tests/test_read_only.py` comparent
  l'empreinte de `.git` avant et après : ils doivent rester verts après cette
  phase. Ouvrir la fenêtre, naviguer, sélectionner, rafraîchir — rien de tout
  cela n'écrit.
- **Le rendu visuel actuel ne doit pas être dégradé.** Courbes de Bézier,
  flèches orientées sur la tangente, `GAP_X = 60` / `GAP_Y = 90`, colonne
  compacte, ouverture centrée sur HEAD, palette de §4.3. Aucune tâche de cette
  phase ne touche `layout/` ni le tracé des arêtes.
- **`ui/` n'appelle jamais pygit2 en écriture.** Une garde
  (`test_ui_never_calls_pygit2_directly_for_operations`) le vérifie.
- **Toute opération destructrice est confirmée (§7.5)** : `reset --hard`,
  suppression de branche, et toute opération sur un arbre de travail modifié.
  Le dialogue nomme la branche et ce qui sera perdu. Pas de case « ne plus
  demander ».
- **Les messages Git ne sont jamais reformulés (§9)** : le dialogue d'erreur
  a trois parties — titre, contexte (`OperationResult.summary`), détail brut
  (`OperationResult.git_error`).
- **Pendant une opération lancée par l'application**, la surveillance de
  `.git` est suspendue (`watcher.suspended()`) : le rafraîchissement est déjà
  assuré par `OperationResult.repository_changed` (§7.6).
- **Aucune commande `git`.** Les fixtures de test peuvent invoquer `git` via
  `subprocess` sur des dépôts temporaires.

---

### Task 1: Dialogues de saisie et de confirmation

**Files:**
- Create: `src/tortoisepy/ui/dialogs.py`
- Test: `tests/ui/test_dialogs.py`

**Interfaces:**
- Consumes: `RepositoryState`, `OperationResult`
- Produces: `ask_name`, `ask_reset_mode`, `confirm`, `show_error`,
  `ConfirmationRequest`

**Les dialogues sont testables sans interaction.** Chaque fonction accepte un
paramètre `parent` et délègue à Qt, mais la **décision** de confirmer — quel
texte, quel niveau de gravité — vit dans `ConfirmationRequest`, une structure
pure. C'est elle qu'on teste ; le widget n'est qu'un affichage.

- [ ] **Step 1: Écrire les tests**

```python
# tests/ui/test_dialogs.py
from tortoisepy.core.results import failed, succeeded
from tortoisepy.core.state import RepositoryState
from tortoisepy.ui.dialogs import (
    ConfirmationRequest,
    confirmation_for,
    error_text,
)


def state(**overrides) -> RepositoryState:
    defaults = dict(
        head_oid="b" * 40,
        head_branch="master",
        detached=False,
        has_unstaged_changes=False,
        has_staged_changes=False,
        has_conflicts=False,
        operation_in_progress=None,
        conflicted_paths=(),
    )
    defaults.update(overrides)
    return RepositoryState(**defaults)


def test_hard_reset_always_needs_confirmation():
    """§7.5 : reset --hard détruit du travail."""
    request = confirmation_for("reset_to", "feature", state(), mode="hard")
    assert request is not None
    assert request.destructive is True


def test_soft_reset_is_not_destructive():
    request = confirmation_for("reset_to", "feature", state(), mode="soft")
    assert request is None or request.destructive is False


def test_branch_deletion_needs_confirmation():
    request = confirmation_for("delete_branch", "feature", state())
    assert request is not None
    assert "feature" in request.message


def test_checkout_on_a_clean_tree_needs_no_confirmation():
    assert confirmation_for("checkout_branch", "feature", state()) is None


def test_checkout_on_a_dirty_tree_warns():
    """§7.5 : toute opération avec des modifications non commitées."""
    request = confirmation_for(
        "checkout_branch", "feature", state(has_unstaged_changes=True)
    )
    assert request is not None
    assert "modification" in request.message.lower()


def test_merge_on_a_dirty_tree_warns():
    request = confirmation_for(
        "merge_branch", "feature", state(has_staged_changes=True)
    )
    assert request is not None


def test_confirmation_names_what_is_lost():
    """Le dialogue doit dire ce qui sera perdu, pas seulement « confirmer ? »."""
    request = confirmation_for("reset_to", "abc1234", state(), mode="hard")
    assert len(request.message) > 30
    assert request.title


def test_creating_a_branch_needs_no_confirmation():
    assert confirmation_for("create_branch", "feature", state()) is None


def test_copying_a_hash_needs_no_confirmation():
    assert confirmation_for("copy_hash", "abc1234", state()) is None


def test_error_text_has_three_parts():
    """§9 : titre, contexte, message Git brut."""
    result = failed(
        "Fusion de « feature »", "1 conflict prevents checkout"
    )
    title, body = error_text(result)
    assert title
    assert "feature" in body
    assert "1 conflict prevents checkout" in body


def test_error_text_never_rewrites_the_git_message():
    """Le message de libgit2 est transmis mot pour mot."""
    raw = "cannot delete the currently checked out branch"
    _, body = error_text(failed("Suppression", raw))
    assert raw in body


def test_error_text_without_git_detail():
    _, body = error_text(failed("Opération", ""))
    assert body


def test_request_is_frozen():
    import pytest

    request = ConfirmationRequest(title="t", message="m", destructive=True)
    with pytest.raises(AttributeError):
        request.destructive = False
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/ui/test_dialogs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tortoisepy.ui.dialogs'`

- [ ] **Step 3: Implémenter**

```python
# src/tortoisepy/ui/dialogs.py
"""Saisies, confirmations et messages d'erreur — §7.5, §9.

La décision de confirmer vit dans `confirmation_for`, une fonction pure :
elle dit s'il faut demander, avec quel texte et quelle gravité. Les widgets
ne font que l'afficher. Cela rend la règle testable sans interaction.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtWidgets import QInputDialog, QMessageBox

from tortoisepy.core.results import OperationResult
from tortoisepy.core.state import RepositoryState

RESET_MODES = ("soft", "mixed", "hard")

_RESET_DESCRIPTIONS = {
    "soft": "déplace la branche, garde l'index et les fichiers",
    "mixed": "déplace la branche et vide l'index, garde les fichiers",
    "hard": "déplace la branche et ÉCRASE les fichiers modifiés",
}

_DIRTY_SENSITIVE = {"checkout_branch", "merge_branch", "cherry_pick"}
"""Opérations qui touchent l'arbre de travail : à confirmer s'il est sale."""


@dataclass(frozen=True)
class ConfirmationRequest:
    title: str
    message: str
    destructive: bool


def confirmation_for(
    action: str,
    target: str,
    state: RepositoryState,
    mode: str | None = None,
) -> ConfirmationRequest | None:
    """Faut-il confirmer cette action ? `None` si elle peut s'exécuter.

    Le message nomme toujours ce qui est en jeu (§7.5) : « confirmer ? »
    sans contexte ne permet pas de décider.
    """
    if action == "reset_to" and mode == "hard":
        return ConfirmationRequest(
            title="Réinitialisation destructive",
            message=(
                f"Réinitialiser « {state.head_branch or 'HEAD'} » sur "
                f"{target} en mode hard.\n\n"
                "Les modifications non commitées seront définitivement "
                "perdues, ainsi que les commits qui ne sont plus "
                "atteignables depuis une autre branche."
            ),
            destructive=True,
        )

    if action == "delete_branch":
        return ConfirmationRequest(
            title="Supprimer la branche",
            message=(
                f"Supprimer la branche « {target} ».\n\n"
                "Les commits qu'elle est seule à référencer deviendront "
                "inatteignables."
            ),
            destructive=True,
        )

    if action == "revert_commit":
        return ConfirmationRequest(
            title="Annuler le commit",
            message=(
                f"Créer un commit inverse de {target}.\n\n"
                "L'historique n'est pas réécrit : un nouveau commit annule "
                "les changements."
            ),
            destructive=False,
        )

    dirty = state.has_unstaged_changes or state.has_staged_changes
    if dirty and action in _DIRTY_SENSITIVE:
        return ConfirmationRequest(
            title="Modifications en cours",
            message=(
                f"L'arbre de travail contient des modifications non "
                f"commitées.\n\nPoursuivre l'opération sur « {target} » "
                "peut les écraser ou l'empêcher d'aboutir."
            ),
            destructive=False,
        )

    return None


def error_text(result: OperationResult) -> tuple[str, str]:
    """Titre et corps d'un dialogue d'erreur — §9, trois parties.

    Le message de libgit2 est transmis mot pour mot : une reformulation
    approximative nuirait à qui connaît Git.
    """
    title = "L'opération a échoué"
    body = f"{result.summary} n'a pas abouti."

    if result.git_error:
        body += f"\n\nDétail Git :\n{result.git_error}"

    return title, body


def ask_name(parent, title: str, label: str, default: str = "") -> str | None:
    """Demande un nom. `None` si l'utilisateur annule."""
    name, accepted = QInputDialog.getText(parent, title, label, text=default)
    if not accepted:
        return None
    name = name.strip()
    return name or None


def ask_reset_mode(parent) -> str | None:
    """Demande le mode de réinitialisation. `None` si annulé."""
    labels = [f"{mode} — {_RESET_DESCRIPTIONS[mode]}" for mode in RESET_MODES]
    choice, accepted = QInputDialog.getItem(
        parent, "Mode de réinitialisation", "Mode :", labels, 1, False
    )
    if not accepted:
        return None
    return choice.split(" — ", 1)[0]


def confirm(parent, request: ConfirmationRequest) -> bool:
    """Affiche la confirmation. Vrai si l'utilisateur accepte.

    Le bouton par défaut est « Annuler » : sur une action destructrice,
    une validation réflexe ne doit pas suffire.
    """
    box = QMessageBox(parent)
    box.setIcon(
        QMessageBox.Icon.Warning
        if request.destructive
        else QMessageBox.Icon.Question
    )
    box.setWindowTitle(request.title)
    box.setText(request.title)
    box.setInformativeText(request.message)
    box.setStandardButtons(
        QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel
    )
    box.setDefaultButton(QMessageBox.StandardButton.Cancel)
    return box.exec() == QMessageBox.StandardButton.Ok


def show_error(parent, result: OperationResult) -> None:
    title, body = error_text(result)
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle(title)
    box.setText(title)
    box.setInformativeText(body)
    box.exec()


def show_message(parent, title: str, message: str) -> None:
    QMessageBox.information(parent, title, message)
```

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/ui/test_dialogs.py -v`
Expected: PASS, 13 tests.

- [ ] **Step 5: Signaler les fichiers prêts** — ne commite pas.

---

### Task 2: Exécution des actions

**Files:**
- Create: `src/tortoisepy/ui/actions.py`
- Test: `tests/ui/test_actions.py`

**Interfaces:**
- Consumes: `core.operations`, `core.state`, dialogues (tâche 1)
- Produces: `ActionContext`, `execute_action`, `ACTION_HANDLERS`

**Le point sensible de toute la phase.** C'est ici que l'application écrit
dans le dépôt. Chaque handler reçoit un `ActionContext` qui porte le dépôt,
le nœud visé et l'état ; il retourne un `OperationResult` ou `None` quand
l'utilisateur annule.

- [ ] **Step 1: Écrire les tests**

```python
# tests/ui/test_actions.py
import os
import subprocess

import pygit2
import pytest

from tortoisepy.core.graph import build_graph
from tortoisepy.core.state import read_state
from tortoisepy.ui.actions import ACTION_HANDLERS, ActionContext, execute_action


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
    path = tmp_path / "actions"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "master")
    (path / "f.txt").write_text("base\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "base")
    run_git(path, "checkout", "-q", "-b", "feature")
    (path / "g.txt").write_text("feature\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "feature")
    run_git(path, "checkout", "-q", "master")
    return pygit2.Repository(str(path))


def context(repo, branch: str = "feature", **overrides) -> ActionContext:
    graph = build_graph(repo)
    node = next(
        n for n in graph.nodes if any(r.name == branch for r in n.refs)
    )
    defaults = dict(
        repository=repo,
        node=node,
        state=read_state(repo),
        parent=None,
        ask_name=lambda *a, **k: "nouvelle-branche",
        ask_mode=lambda *a, **k: "mixed",
        confirm=lambda *a, **k: True,
    )
    defaults.update(overrides)
    return ActionContext(**defaults)


def test_every_menu_action_has_a_handler():
    """Une entrée sans handler afficherait un menu mensonger."""
    from tortoisepy.ui.context_menu import build_menu_model
    from tortoisepy.core.model import DisplayNode, NodeKind, Ref, RefType
    from tortoisepy.core.state import RepositoryState

    node = DisplayNode(
        oid="a" * 40,
        kind=NodeKind.REF,
        refs=(Ref("feature", RefType.LOCAL_BRANCH, "a" * 40),),
    )
    state = RepositoryState(
        head_oid="b" * 40, head_branch="master", detached=False,
        has_unstaged_changes=False, has_staged_changes=False,
        has_conflicts=False, operation_in_progress=None, conflicted_paths=(),
    )

    def actions(entries):
        for entry in entries:
            if entry.action and not entry.is_separator:
                yield entry.action
            yield from actions(entry.children)

    declared = set(actions(build_menu_model((node,), state)))
    missing = declared - set(ACTION_HANDLERS)
    assert not missing, f"actions sans handler : {sorted(missing)}"


def test_checkout_switches_branch(repo):
    result = execute_action("checkout_branch", context(repo))
    assert result.success is True
    assert read_state(repo).head_branch == "feature"


def test_create_branch_uses_the_given_name(repo):
    result = execute_action(
        "create_branch", context(repo, ask_name=lambda *a, **k: "issue-42")
    )
    assert result.success is True
    assert "refs/heads/issue-42" in repo.references


def test_cancelling_a_name_does_nothing(repo):
    """Annuler la saisie ne doit RIEN écrire (§7.0)."""
    before = set(repo.references)
    result = execute_action(
        "create_branch", context(repo, ask_name=lambda *a, **k: None)
    )
    assert result is None
    assert set(repo.references) == before


def test_declining_a_confirmation_does_nothing(repo):
    """§7.5 : refuser la confirmation annule l'opération."""
    before = set(repo.references)
    result = execute_action(
        "delete_branch", context(repo, confirm=lambda *a, **k: False)
    )
    assert result is None
    assert set(repo.references) == before


def test_delete_branch_after_confirmation(repo):
    result = execute_action("delete_branch", context(repo))
    assert result.success is True
    assert "refs/heads/feature" not in repo.references


def test_create_tag_uses_the_given_name(repo):
    result = execute_action(
        "create_tag", context(repo, ask_name=lambda *a, **k: "v1.0")
    )
    assert result.success is True
    assert "refs/tags/v1.0" in repo.references


def test_reset_asks_for_a_mode(repo):
    asked = []
    execute_action(
        "reset_to",
        context(repo, ask_mode=lambda *a, **k: (asked.append(1), "soft")[1]),
    )
    assert asked, "le mode doit être demandé"


def test_cancelling_the_mode_does_nothing(repo):
    head = str(repo.head.target)
    result = execute_action(
        "reset_to", context(repo, ask_mode=lambda *a, **k: None)
    )
    assert result is None
    assert str(repo.head.target) == head


def test_merge_brings_the_branch_in(repo):
    result = execute_action("merge_branch", context(repo))
    assert result.repository_changed is True


def test_copy_hash_writes_nothing(repo):
    """Copier un hash ne touche pas au dépôt."""
    result = execute_action("copy_hash", context(repo))
    assert result is not None
    assert result.repository_changed is False


def test_unknown_action_returns_none(repo):
    assert execute_action("action_inexistante", context(repo)) is None


def test_failure_is_reported_not_raised(repo):
    """§7.6 : aucune exception ne remonte."""
    ctx = context(repo, branch="master")  # supprimer la branche courante
    result = execute_action("delete_branch", ctx)
    assert result is not None
    assert result.success is False
    assert result.git_error


def test_handlers_never_raise(repo):
    """Chaque handler doit survivre à un contexte hostile."""
    ctx = context(repo, ask_name=lambda *a, **k: "", ask_mode=lambda *a, **k: "")
    for action in ACTION_HANDLERS:
        execute_action(action, ctx)  # ne doit jamais lever
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/ui/test_actions.py -v`
Expected: FAIL — module introuvable.

- [ ] **Step 3: Implémenter**

```python
# src/tortoisepy/ui/actions.py
"""Exécution des actions du menu contextuel — §7.3, §7.5, §7.6.

C'est le seul endroit où l'application écrit dans le dépôt, et toujours
après un clic explicite (§7.0). Les saisies et confirmations sont injectées
(`ask_name`, `ask_mode`, `confirm`) plutôt qu'appelées directement : la
logique reste testable sans interaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pygit2

from tortoisepy.core import operations
from tortoisepy.core.model import DisplayNode, RefType
from tortoisepy.core.results import OperationResult, succeeded
from tortoisepy.core.state import RepositoryState
from tortoisepy.ui.dialogs import confirmation_for


@dataclass(frozen=True)
class ActionContext:
    repository: pygit2.Repository
    node: DisplayNode
    state: RepositoryState
    parent: object = None
    ask_name: Callable[..., str | None] = lambda *a, **k: None
    ask_mode: Callable[..., str | None] = lambda *a, **k: None
    confirm: Callable[..., bool] = lambda *a, **k: False
    copy: Callable[[str], None] = lambda text: None

    @property
    def branch(self) -> str | None:
        """Nom de la branche locale portée par le nœud, s'il y en a une."""
        for ref in self.node.refs:
            if ref.type is RefType.LOCAL_BRANCH:
                return ref.name
        return None

    @property
    def label(self) -> str:
        """Comment nommer ce nœud à l'utilisateur."""
        return self.branch or self.node.oid[:8]


def execute_action(action: str, ctx: ActionContext) -> OperationResult | None:
    """Exécute une action. `None` si elle est annulée ou inconnue.

    Distinguer « annulé » de « échoué » compte : la fenêtre n'affiche une
    erreur que dans le second cas.
    """
    handler = ACTION_HANDLERS.get(action)
    if handler is None:
        return None

    request = confirmation_for(action, ctx.label, ctx.state)
    if request is not None and not ctx.confirm(ctx.parent, request):
        return None

    return handler(ctx)


def _checkout_branch(ctx: ActionContext) -> OperationResult | None:
    if ctx.branch is None:
        return operations.checkout_commit(ctx.repository, ctx.node.oid)
    return operations.checkout_branch(ctx.repository, ctx.branch)


def _create_branch(ctx: ActionContext) -> OperationResult | None:
    name = ctx.ask_name(ctx.parent, "Créer une branche", "Nom de la branche :")
    if not name:
        return None
    return operations.create_branch(ctx.repository, name, ctx.node.oid)


def _create_tag(ctx: ActionContext) -> OperationResult | None:
    name = ctx.ask_name(ctx.parent, "Créer un tag", "Nom du tag :")
    if not name:
        return None
    return operations.create_tag(ctx.repository, name, ctx.node.oid)


def _rename_branch(ctx: ActionContext) -> OperationResult | None:
    if ctx.branch is None:
        return None
    name = ctx.ask_name(
        ctx.parent, "Renommer la branche", "Nouveau nom :", ctx.branch
    )
    if not name:
        return None
    return operations.rename_branch(ctx.repository, ctx.branch, name)


def _delete_branch(ctx: ActionContext) -> OperationResult | None:
    if ctx.branch is None:
        return None
    return operations.delete_branch(ctx.repository, ctx.branch)


def _merge_branch(ctx: ActionContext) -> OperationResult | None:
    if ctx.branch is None:
        return None
    return operations.merge_branch(ctx.repository, ctx.branch)


def _cherry_pick(ctx: ActionContext) -> OperationResult | None:
    return operations.cherry_pick(ctx.repository, ctx.node.oid)


def _revert_commit(ctx: ActionContext) -> OperationResult | None:
    return operations.revert_commit(ctx.repository, ctx.node.oid)


def _reset_to(ctx: ActionContext) -> OperationResult | None:
    """Le mode est demandé AVANT la confirmation du mode hard.

    `execute_action` a déjà confirmé l'action elle-même ; le mode hard
    demande sa propre confirmation, puisque c'est lui qui détruit (§7.5).
    """
    mode = ctx.ask_mode(ctx.parent)
    if not mode:
        return None

    if mode == "hard":
        request = confirmation_for("reset_to", ctx.label, ctx.state, mode="hard")
        if request is not None and not ctx.confirm(ctx.parent, request):
            return None

    return operations.reset_to(ctx.repository, ctx.node.oid, mode)


def _abort_operation(ctx: ActionContext) -> OperationResult | None:
    return operations.abort_operation(ctx.repository)


def _copy_hash(ctx: ActionContext) -> OperationResult | None:
    """Copie l'OID complet. N'écrit rien dans le dépôt."""
    ctx.copy(ctx.node.oid)
    return succeeded(
        f"Hash {ctx.node.oid[:8]} copié", repository_changed=False
    )


def _show_log(ctx: ActionContext) -> OperationResult | None:
    """Le panneau latéral affiche déjà les commits à la sélection."""
    return succeeded("Journal affiché", repository_changed=False)


def _not_available(ctx: ActionContext) -> OperationResult | None:
    """Actions prévues par le menu mais hors périmètre v1 (§11)."""
    return None


ACTION_HANDLERS: dict[str, Callable[[ActionContext], OperationResult | None]] = {
    "checkout_branch": _checkout_branch,
    "create_branch": _create_branch,
    "create_tag": _create_tag,
    "rename_branch": _rename_branch,
    "delete_branch": _delete_branch,
    "merge_branch": _merge_branch,
    "cherry_pick": _cherry_pick,
    "revert_commit": _revert_commit,
    "reset_to": _reset_to,
    "abort_operation": _abort_operation,
    "copy_hash": _copy_hash,
    "show_log": _show_log,
    # Hors périmètre v1 : le diff visuel est délégué (§7.4, §11).
    "compare_revisions": _not_available,
    "show_log_of_differences": _not_available,
}
```

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/ui/test_actions.py -v`
Expected: PASS, 14 tests.

- [ ] **Step 5: Signaler les fichiers prêts** — ne commite pas.

---

### Task 3: Branchement dans la fenêtre

**Files:**
- Modify: `src/tortoisepy/ui/main_window.py`
- Test: `tests/ui/test_main_window.py` (ajouts)

**Interfaces:**
- Consumes: tâches 1 et 2
- Produces: menu contextuel opérant

Remplace `_not_implemented` par l'exécution réelle, avec suspension de la
surveillance et rafraîchissement conditionnel.

- [ ] **Step 1: Écrire les tests**

```python
# à ajouter dans tests/ui/test_main_window.py


def test_menu_action_runs_the_operation(window, monkeypatch):
    """Le menu n'affiche plus « pas encore câblé »."""
    from tortoisepy.ui import actions

    called = []
    monkeypatch.setattr(
        actions, "execute_action",
        lambda action, ctx: called.append(action) or None,
    )

    node = next(
        n for n in window.graph.nodes
        if any(r.name == "feature" for r in n.refs)
    )
    window._run_action("checkout_branch", node)
    assert called == ["checkout_branch"]


def test_successful_action_refreshes_the_graph(window, monkeypatch):
    from tortoisepy.core.results import succeeded
    from tortoisepy.ui import actions

    monkeypatch.setattr(
        actions, "execute_action", lambda action, ctx: succeeded("fait")
    )
    before = window.view.scene()

    node = window.graph.nodes[0]
    window._run_action("checkout_branch", node)

    assert window.view.scene() is not before


def test_failed_action_still_refreshes_when_the_repo_changed(
    window, monkeypatch
):
    """§7.6 : un merge en conflit échoue mais a modifié le dépôt."""
    from tortoisepy.core.results import failed
    from tortoisepy.ui import actions

    monkeypatch.setattr(
        actions, "execute_action",
        lambda action, ctx: failed("Fusion", "conflits", repository_changed=True),
    )
    monkeypatch.setattr(
        "tortoisepy.ui.main_window.show_error", lambda parent, result: None
    )
    before = window.view.scene()

    window._run_action("merge_branch", window.graph.nodes[0])
    assert window.view.scene() is not before


def test_cancelled_action_does_not_refresh(window, monkeypatch):
    from tortoisepy.ui import actions

    monkeypatch.setattr(actions, "execute_action", lambda action, ctx: None)
    before = window.view.scene()

    window._run_action("create_branch", window.graph.nodes[0])
    assert window.view.scene() is before


def test_watcher_is_suspended_during_an_action(window, monkeypatch):
    """§7.9 : l'application ne doit pas se notifier elle-même."""
    from tortoisepy.core.results import succeeded
    from tortoisepy.ui import actions

    seen = []
    monkeypatch.setattr(
        actions, "execute_action",
        lambda action, ctx: seen.append(window.watcher._suspended)
        or succeeded("fait"),
    )

    window._run_action("checkout_branch", window.graph.nodes[0])
    assert seen == [True], "la surveillance doit être suspendue"
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/ui/test_main_window.py -k action -v`
Expected: FAIL — `_run_action` n'existe pas.

- [ ] **Step 3: Implémenter**

Remplacer `_not_implemented` et adapter `_fill_menu` :

```python
# dans src/tortoisepy/ui/main_window.py

# imports à ajouter
from PySide6.QtGui import QGuiApplication
from tortoisepy.ui.actions import ActionContext, execute_action
from tortoisepy.ui.dialogs import (
    ask_name,
    ask_reset_mode,
    confirm,
    show_error,
)


    def _fill_menu(self, menu: QMenu, entries: tuple[MenuEntry, ...]) -> None:
        for entry in entries:
            # `is_separator` repose sur `action == "separator"`, jamais sur
            # le label : celui-ci porte un caractère de remplissage qui ne
            # doit pas s'afficher.
            if entry.is_separator:
                menu.addSeparator()
            elif entry.children:
                submenu = menu.addMenu(entry.label)
                self._fill_menu(submenu, entry.children)
            else:
                action = menu.addAction(entry.label)
                action.setEnabled(entry.enabled)
                action.triggered.connect(
                    lambda checked=False, name=entry.action: self._run_action(
                        name, self._selected_node()
                    )
                )

    def _selected_node(self):
        """Le nœud sélectionné, ou None s'il n'y en a pas exactement un."""
        if self.graph is None:
            return None
        selected = self.view.selected_oids()
        if len(selected) != 1:
            return None
        return self.graph.node(selected[0])

    def _run_action(self, action: str | None, node) -> None:
        """Exécute une action du menu — le seul endroit qui écrit (§7.0).

        La surveillance est suspendue le temps de l'opération : le
        rafraîchissement est déjà assuré par `repository_changed`, et
        laisser le watcher réagir déclencherait une reconstruction de plus
        (§7.9).
        """
        if action is None or node is None or self.state is None:
            return

        context = ActionContext(
            repository=self.repository,
            node=node,
            state=self.state,
            parent=self,
            ask_name=ask_name,
            ask_mode=ask_reset_mode,
            confirm=confirm,
            copy=self._copy_to_clipboard,
        )

        with self.watcher.suspended():
            result = execute_action(action, context)

        if result is None:
            return  # annulé par l'utilisateur, ou action sans effet

        if result.repository_changed:
            self.refresh()

        if not result.success:
            show_error(self, result)

    def _copy_to_clipboard(self, text: str) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)
```

Supprimer la méthode `_not_implemented` devenue inutile.

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/ui/ -q`
Expected: PASS.

- [ ] **Step 5: Vérifier la lecture seule**

Run: `.venv/bin/pytest tests/test_read_only.py -v`
Expected: PASS, 7 tests. **C'est le contrôle le plus important de cette
phase** : ouvrir la fenêtre et naviguer ne doit toujours rien écrire.

- [ ] **Step 6: Suite complète**

Run: `.venv/bin/pytest tests/ -q`
Expected: 448 + ~32 tests, tous verts. **Attendre la fin.**

- [ ] **Step 7: Signaler les fichiers prêts** — ne commite pas.

---

### Task 4: Point d'entrée `tgraph`

**Files:**
- Create: `src/tortoisepy/cli.py`
- Test: `tests/test_cli.py`
- Modify: `run.py` (le réduire à un appel de la CLI)

**Interfaces:**
- Consumes: `MainWindow`
- Produces: `main`, `find_repository`

- [ ] **Step 1: Écrire les tests**

```python
# tests/test_cli.py
import os
import subprocess

import pytest

from tortoisepy.cli import find_repository


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
def repo_path(tmp_path):
    path = tmp_path / "cli"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "master")
    (path / "f.txt").write_text("base\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "base")
    return path


def test_finds_a_repository_at_its_root(repo_path):
    assert find_repository(str(repo_path)) is not None


def test_finds_a_repository_from_a_subdirectory(repo_path):
    """§8 : la commande marche depuis n'importe quel sous-dossier."""
    nested = repo_path / "src" / "deep"
    nested.mkdir(parents=True)
    assert find_repository(str(nested)) is not None


def test_returns_none_outside_a_repository(tmp_path):
    """Vérifié : discover_repository retourne None, elle ne lève pas."""
    outside = tmp_path / "rien"
    outside.mkdir()
    assert find_repository(str(outside)) is None


def test_returns_none_for_a_missing_path(tmp_path):
    assert find_repository(str(tmp_path / "inexistant")) is None


def test_finding_a_repository_writes_nothing(repo_path):
    """§7.0 : même la découverte ne touche pas au dépôt."""
    import hashlib

    def fingerprint():
        digest = hashlib.sha256()
        for path in sorted((repo_path / ".git").rglob("*")):
            if path.is_file():
                stat = path.stat()
                digest.update(f"{path}:{stat.st_mtime_ns}".encode())
        return digest.hexdigest()

    before = fingerprint()
    find_repository(str(repo_path))
    assert fingerprint() == before
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tortoisepy.cli'`

- [ ] **Step 3: Implémenter**

```python
# src/tortoisepy/cli.py
"""Point d'entrée `tgraph` — §8.

    tgraph              # dépôt du dossier courant
    tgraph /chemin      # dépôt à ce chemin
"""

from __future__ import annotations

import sys

import pygit2

__version__ = "0.1.0"


def find_repository(start: str) -> pygit2.Repository | None:
    """Remonte l'arborescence comme le fait Git.

    Vérifié sur pygit2 1.20 : `discover_repository` RETOURNE `None` quand
    elle ne trouve rien, elle ne lève pas. Le `try/except` couvre les
    versions qui levaient, et les chemins illisibles.
    """
    try:
        path = pygit2.discover_repository(start)
    except (pygit2.GitError, KeyError, ValueError):
        return None

    if not path:
        return None

    try:
        return pygit2.Repository(path)
    except (pygit2.GitError, KeyError, ValueError):
        return None


def main(argv: list[str] | None = None) -> int:
    """Ouvre la fenêtre sur le dépôt demandé."""
    arguments = list(sys.argv[1:] if argv is None else argv)

    if arguments and arguments[0] in ("--version", "-V"):
        print(f"tortoisePy {__version__}")
        return 0

    target = arguments[0] if arguments else "."

    repository = find_repository(target)
    if repository is None:
        print(f"Pas de dépôt Git trouvé dans {target}", file=sys.stderr)
        return 1

    # Les imports Qt restent ici : `--version` et le message d'erreur
    # ci-dessus ne doivent pas payer le chargement de PySide6.
    from PySide6.QtWidgets import QApplication

    from tortoisepy.ui.main_window import MainWindow

    # La QApplication doit exister avant toute opération de police :
    # sans elle, Qt abandonne le processus au lieu de lever (vérifié).
    app = QApplication(sys.argv[:1])

    window = MainWindow(repository)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
```

Réduire `run.py` :

```python
#!/usr/bin/env python3
"""Lanceur de développement — équivalent de la commande `tgraph`.

Utile avant `pip install -e .`, qui installe `tgraph` dans le PATH.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from tortoisepy.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 5: Vérifier la commande à la main**

```bash
.venv/bin/python run.py --version
.venv/bin/python run.py /tmp        # doit sortir en code 1
```

- [ ] **Step 6: Suite complète**

Run: `.venv/bin/pytest tests/ -q`
Expected: tous verts. **Attendre la fin.**

- [ ] **Step 7: Signaler les fichiers prêts** — ne commite pas.

---

## Fin de phase 5

À ce stade :

- le menu contextuel exécute réellement les opérations ;
- les actions destructrices demandent confirmation en nommant ce qui sera
  perdu ;
- les erreurs Git sont affichées en trois parties, sans reformulation ;
- `tgraph` est installable par `pip install -e .` ;
- **rien ne s'écrit sans clic explicite** — vérifié par
  `tests/test_read_only.py`.

**Ce qui reste hors périmètre v1 :**

- **Push, pull, fetch** — réseau et authentification, leur propre cycle.
- **Rebase** — l'API pygit2 expose des étapes à piloter une par une.
- **Le diff visuel** (§7.4) et le **Log Dialog** (§11).
- **La mini-carte** (§7.1).
- **Le nombre de nœuds sur les très gros dépôts** : `xpc` en affiche 336,
  `vti` 8282. Chantier à part, avec sa propre analyse.
