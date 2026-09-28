"""Modèle du menu contextuel — §7.3, §7.4, §7.5.

Ce module ne construit aucun widget : il décide **quelles entrées existent
et lesquelles sont actives**, en fonction du type de nœud et de l'état du
dépôt. Le widget Qt traduit ensuite ce modèle. Séparer les deux rend la
logique testable sans interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tortoisepy.core.model import DisplayNode, NodeKind, RefType
from tortoisepy.core.state import RepositoryState


@dataclass(frozen=True)
class MenuEntry:
    label: str
    action: str | None = None
    enabled: bool = True
    needs_confirmation: bool = False
    children: tuple["MenuEntry", ...] = field(default_factory=tuple)

    @property
    def is_separator(self) -> bool:
        return self.action == "separator"


SEPARATOR = MenuEntry(label="—", action="separator")


def build_menu_model(
    nodes: tuple[DisplayNode, ...], state: RepositoryState
) -> tuple[MenuEntry, ...]:
    """Menu correspondant à la sélection courante.

    Une sélection vide ne produit aucun menu ; deux nœuds activent les
    actions de comparaison (§7.4).
    """
    if not nodes:
        return ()

    if len(nodes) >= 2:
        return _comparison_menu(nodes)

    return _single_node_menu(nodes[0], state)


def _comparison_menu(nodes: tuple[DisplayNode, ...]) -> tuple[MenuEntry, ...]:
    """§7.4 : menu de deux nœuds sélectionnés."""
    return (
        MenuEntry("Comparer les révisions…", "compare_revisions"),
        MenuEntry("Journal des différences…", "show_log_of_differences"),
        SEPARATOR,
        MenuEntry("Copier les hash", "copy_hash"),
    )


def _single_node_menu(
    node: DisplayNode, state: RepositoryState
) -> tuple[MenuEntry, ...]:
    """§7.3 : menu hiérarchisé d'un nœud."""
    busy = state.operation_in_progress is not None
    dirty = state.has_unstaged_changes or state.has_staged_changes

    is_branch = _has_local_branch(node)
    is_current = _is_current(node, state)
    actionable = node.kind is not NodeKind.STASH and not busy

    can_checkout = is_branch and not is_current and not busy
    can_merge = is_branch and not is_current and not busy
    can_modify_branch = is_branch and not busy

    entries: list[MenuEntry] = [
        MenuEntry(
            "Checkout / Basculer",
            "checkout_branch",
            enabled=can_checkout,
            needs_confirmation=dirty,
        ),
        SEPARATOR,
        MenuEntry(
            "Créer",
            children=(
                MenuEntry("Branche ici…", "create_branch", enabled=actionable),
                MenuEntry("Tag ici…", "create_tag", enabled=actionable),
            ),
        ),
        MenuEntry(
            "Intégrer",
            children=(
                MenuEntry(
                    "Fusionner dans la branche courante…",
                    "merge_branch",
                    enabled=can_merge,
                    needs_confirmation=dirty,
                ),
                MenuEntry(
                    "Cherry-pick ce commit…",
                    "cherry_pick",
                    enabled=actionable,
                    needs_confirmation=dirty,
                ),
            ),
        ),
        MenuEntry(
            "Annuler",
            children=(
                MenuEntry(
                    "Réinitialiser la branche courante ici…",
                    "reset_to",
                    enabled=actionable,
                    needs_confirmation=True,
                ),
                MenuEntry(
                    "Revert ce commit…",
                    "revert_commit",
                    enabled=actionable,
                    needs_confirmation=True,
                ),
            ),
        ),
        MenuEntry(
            "Branche",
            children=(
                MenuEntry(
                    "Renommer…", "rename_branch", enabled=can_modify_branch
                ),
                MenuEntry(
                    "Supprimer",
                    "delete_branch",
                    enabled=can_modify_branch and not is_current,
                    needs_confirmation=True,
                ),
            ),
        ),
    ]

    if busy:
        entries.append(SEPARATOR)
        entries.append(
            MenuEntry(
                f"Abandonner le {state.operation_in_progress}",
                "abort_operation",
                enabled=True,
                needs_confirmation=True,
            )
        )

    entries.append(SEPARATOR)
    entries.append(MenuEntry("Afficher le journal", "show_log"))
    entries.append(MenuEntry("Copier le hash", "copy_hash"))

    return tuple(entries)


def _has_local_branch(node: DisplayNode) -> bool:
    return any(ref.type is RefType.LOCAL_BRANCH for ref in node.refs)


def _is_current(node: DisplayNode, state: RepositoryState) -> bool:
    """Le nœud porte-t-il la branche courante ?"""
    if any(ref.type is RefType.HEAD for ref in node.refs):
        return True
    if state.head_branch is None:
        return False
    return any(
        ref.type is RefType.LOCAL_BRANCH and ref.name == state.head_branch
        for ref in node.refs
    )
