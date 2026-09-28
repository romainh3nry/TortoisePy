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
    name = ctx.ask_name(ctx.parent, "Create Branch", "Branch name:")
    if not name:
        return None
    return operations.create_branch(ctx.repository, name, ctx.node.oid)


def _create_tag(ctx: ActionContext) -> OperationResult | None:
    name = ctx.ask_name(ctx.parent, "Create Tag", "Tag name:")
    if not name:
        return None
    return operations.create_tag(ctx.repository, name, ctx.node.oid)


def _rename_branch(ctx: ActionContext) -> OperationResult | None:
    if ctx.branch is None:
        return None
    name = ctx.ask_name(
        ctx.parent, "Rename Branch", "New name:", ctx.branch
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


def _fetch_remote(ctx: ActionContext) -> OperationResult | None:
    """Met à jour les refs distantes. Ne touche pas au travail local."""
    return operations.fetch_remote(ctx.repository)


def _abort_operation(ctx: ActionContext) -> OperationResult | None:
    return operations.abort_operation(ctx.repository)


def _copy_hash(ctx: ActionContext) -> OperationResult | None:
    """Copie l'OID complet. N'écrit rien dans le dépôt."""
    ctx.copy(ctx.node.oid)
    return succeeded(
        f"Copy SHA-1 of {ctx.node.oid[:8]}", repository_changed=False
    )


def _show_log(ctx: ActionContext) -> OperationResult | None:
    """Le panneau latéral affiche déjà les commits à la sélection."""
    return succeeded("Show log", repository_changed=False)


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
    "fetch_remote": _fetch_remote,
    "abort_operation": _abort_operation,
    "copy_hash": _copy_hash,
    "show_log": _show_log,
    # Hors périmètre v1 : le diff visuel est délégué (§7.4, §11).
    "compare_revisions": _not_available,
    "show_log_of_differences": _not_available,
}
