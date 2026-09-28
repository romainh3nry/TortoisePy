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
