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
from tortoisepy.core import stash_ops
from tortoisepy.core.model import DisplayNode, RefType
from tortoisepy.core.results import OperationResult, failed, succeeded
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

    chosen_branch: str | None = None
    """Branche désignée par le menu, quand le nœud en porte plusieurs."""

    @property
    def branch(self) -> str | None:
        """Branche locale sur laquelle agir.

        `chosen_branch` prime quand le menu l'a précisée : plusieurs
        branches peuvent partager un commit, donc un même nœud, et se
        rabattre sur la première rendait les autres inatteignables
        (signalé par l'utilisateur).
        """
        if self.chosen_branch is not None:
            return self.chosen_branch
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
    """Crée la branche **et bascule dessus**, comme `git checkout -b`.

    Demandé par l'utilisateur : créer une branche pour rester sur l'ancienne
    n'a pratiquement jamais d'intérêt — on la crée pour y travailler.

    Si le checkout échoue, la branche existe malgré tout : on rapporte
    l'échec du basculement sans laisser croire que rien n'a été fait.
    """
    name = ctx.ask_name(ctx.parent, "Create Branch", "Branch name:")
    if not name:
        return None

    created = operations.create_branch(ctx.repository, name, ctx.node.oid)
    if not created.success:
        return created

    switched = operations.checkout_branch(ctx.repository, name)
    if not switched.success:
        return failed(
            f"Création de « {name} »",
            f"branch created, but switching failed: {switched.git_error}",
        )
    return succeeded(f"Branche « {name} » créée, basculé dessus")


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


def _push_branch(ctx: ActionContext) -> OperationResult | None:
    """La fenêtre principale s'en charge : le push part en arrière-plan."""
    return None


def _pull_branch(ctx: ActionContext) -> OperationResult | None:
    """La fenêtre principale s'en charge : le pull part en arrière-plan."""
    return None


def _force_push_branch(ctx: ActionContext) -> OperationResult | None:
    """La fenêtre principale s'en charge : push en arrière-plan."""
    return None


def _rebase_branch(ctx: ActionContext) -> OperationResult | None:
    """La fenêtre principale s'en charge : elle doit demander la cible."""
    return None


def _open_conflicts(ctx: ActionContext) -> OperationResult | None:
    """La fenêtre principale s'en charge : elle ouvre une fenêtre."""
    return None


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


def _open_commit(ctx: ActionContext) -> OperationResult | None:
    """Ouvre la fenêtre de commit. La fenêtre principale s'en charge."""
    return None


def _not_available(ctx: ActionContext) -> OperationResult | None:
    """Actions prévues par le menu mais hors périmètre v1 (§11)."""
    return None


def _delete_remote_branch(ctx: ActionContext) -> OperationResult | None:
    """Supprime la branche sur le serveur ; la locale reste.

    La confirmation est posée par `execute_action` via
    `confirmation_for` — c'est la vraie porte, et non
    `MenuEntry.needs_confirmation`, qui n'est lu par personne.
    """
    cible = ctx.branch
    if cible is None or "/" not in cible:
        return None
    # Le menu donne « origin/feature » : le serveur et la branche sont
    # séparés ici, car `origin/x` et `upstream/x` sont deux cibles
    # différentes et l'action doit savoir à qui parler.
    remote, _, branch = cible.partition("/")
    return operations.delete_remote_branch(
        ctx.repository, branch, remote_name=remote
    )


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


ACTION_HANDLERS: dict[str, Callable[[ActionContext], OperationResult | None]] = {
    "checkout_branch": _checkout_branch,
    "create_branch": _create_branch,
    "create_tag": _create_tag,
    "rename_branch": _rename_branch,
    "delete_branch": _delete_branch,
    "delete_remote_branch": _delete_remote_branch,
    "merge_branch": _merge_branch,
    "rebase_branch": _rebase_branch,
    "open_conflicts": _open_conflicts,
    "cherry_pick": _cherry_pick,
    "revert_commit": _revert_commit,
    "reset_to": _reset_to,
    "fetch_remote": _fetch_remote,
    "push_branch": _push_branch,
    "force_push_branch": _force_push_branch,
    "pull_branch": _pull_branch,
    "abort_operation": _abort_operation,
    "copy_hash": _copy_hash,
    "show_log": _show_log,
    "open_commit": _open_commit,
    # Hors périmètre v1 : le diff visuel est délégué (§7.4, §11).
    "compare_revisions": _not_available,
    "show_log_of_differences": _not_available,
    "stash_changes": _stash_changes,
    "apply_stash": _apply_stash,
    "pop_stash": _pop_stash,
    "drop_stash": _drop_stash,
}
