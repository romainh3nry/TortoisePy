"""État des fichiers modifiés et leurs diffs — §4.1, §4.2.

Lecture seule, sans Qt : `ui/` affiche ce que ce module décrit.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pygit2
from pygit2.enums import DeltaStatus, FileStatus

_UNTRACKED = FileStatus.WT_NEW
_DELETED = FileStatus.WT_DELETED | FileStatus.INDEX_DELETED
_CONFLICTED = FileStatus.CONFLICTED


class ChangeKind(Enum):
    MODIFIED = "M"
    ADDED = "A"
    DELETED = "D"
    UNTRACKED = "?"
    CONFLICTED = "!"


_DELTA_KINDS = {
    DeltaStatus.ADDED: ChangeKind.ADDED,
    DeltaStatus.DELETED: ChangeKind.DELETED,
    DeltaStatus.MODIFIED: ChangeKind.MODIFIED,
    # Un renommage reste une modification du point de vue de l'utilisateur :
    # le fichier existe avant et après.
    DeltaStatus.RENAMED: ChangeKind.MODIFIED,
    DeltaStatus.COPIED: ChangeKind.ADDED,
}
"""Statut d'un delta pygit2 -> nature du changement affichée.

Sert aux commits déjà faits (`changes_in_commit`), là où `_classify` sert à
l'arbre de travail : un commit n'a ni fichier « non suivi » ni conflit, donc
les deux tables ne se recouvrent pas.
"""


@dataclass(frozen=True)
class FileChange:
    path: str
    kind: ChangeKind
    is_binary: bool = False

    @property
    def selectable(self) -> bool:
        """Un conflit non résolu ne doit pas pouvoir être commité (§4.1)."""
        return self.kind is not ChangeKind.CONFLICTED

    @property
    def selected_by_default(self) -> bool:
        """Les fichiers non suivis sont affichés mais décochés (D8).

        Ils sont souvent du bruit — build, cache, `.env` — mais parfois le
        fichier qu'on vient de créer. Les montrer sans les cocher laisse
        décider sans risque d'ajout accidentel.
        """
        if not self.selectable:
            return False
        return self.kind is not ChangeKind.UNTRACKED


@dataclass(frozen=True)
class DiffLine:
    origin: str
    """`+` ajoutée, `-` supprimée, ` ` contexte."""

    content: str


@dataclass(frozen=True)
class DiffHunk:
    header: str
    lines: tuple[DiffLine, ...]


@dataclass(frozen=True)
class FileDiff:
    path: str
    hunks: tuple[DiffHunk, ...] = ()
    added: int = 0
    removed: int = 0
    is_binary: bool = False


def list_changes(repo: pygit2.Repository) -> tuple[FileChange, ...]:
    """Fichiers modifiés, triés par chemin.

    Le tri rend l'affichage stable d'une ouverture à l'autre.
    """
    try:
        status = repo.status()
    except pygit2.GitError:
        return ()

    changes = [
        FileChange(
            path=path,
            kind=_classify(code),
            is_binary=_is_binary(repo, path),
        )
        for path, code in status.items()
    ]
    return tuple(sorted(changes, key=lambda c: c.path))


def diff_for(repo: pygit2.Repository, path: str) -> FileDiff:
    """Diff d'un fichier par rapport au dernier commit.

    Indexé ou non : c'est l'état que l'utilisateur s'apprête à commiter.
    """
    patch = _patch_for(repo, path)
    if patch is None:
        return FileDiff(path=path)
    return _to_file_diff(path, patch)


def changes_in_commit(
    repo: pygit2.Repository, oid: str
) -> tuple[FileChange, ...]:
    """Fichiers touchés par un commit, triés par chemin.

    Le tri rend l'affichage stable d'une ouverture à l'autre, comme pour
    `list_changes`.
    """
    diff = _commit_diff(repo, oid)
    if diff is None:
        return ()

    changes = [
        FileChange(
            path=patch.delta.new_file.path or patch.delta.old_file.path,
            kind=_DELTA_KINDS.get(patch.delta.status, ChangeKind.MODIFIED),
            is_binary=patch.delta.is_binary,
        )
        for patch in diff
    ]
    return tuple(sorted(changes, key=lambda c: c.path))


def diff_in_commit(repo: pygit2.Repository, oid: str, path: str) -> FileDiff:
    """Diff d'un fichier tel que ce commit l'a changé.

    Distinct de `diff_for`, qui compare l'arbre de travail au dernier
    commit : ici la question porte sur un commit déjà fait.
    """
    diff = _commit_diff(repo, oid)
    if diff is None:
        return FileDiff(path=path)

    for patch in diff:
        if path in (patch.delta.new_file.path, patch.delta.old_file.path):
            return _to_file_diff(path, patch)
    return FileDiff(path=path)


def _commit_diff(repo: pygit2.Repository, oid: str):
    """Diff d'un commit contre son premier parent.

    Un commit de merge a plusieurs parents : on prend le premier, comme
    `git show`, ce qui montre ce que le merge a apporté à la branche
    d'accueil — c'est aussi ce qu'affiche TortoiseGit.

    Un commit racine n'a pas de parent. `swap=True` est indispensable :
    sans lui, ses fichiers apparaissent en suppressions plutôt qu'en
    ajouts (vérifié).
    """
    try:
        commit = repo.get(pygit2.Oid(hex=oid)).peel(pygit2.Commit)
    except (ValueError, KeyError, TypeError, AttributeError, pygit2.GitError):
        return None

    if not commit.parents:
        diff = commit.tree.diff_to_tree(swap=True)
    else:
        diff = repo.diff(commit.parents[0].tree, commit.tree)

    # Sans `find_similar`, pygit2 n'apparie jamais un renommage : un
    # `git mv` ressort en deux entrées sans rapport (`D ancien` + `A nouveau`)
    # alors que git et TortoiseGit montrent un seul `R ancien -> nouveau`.
    # Vérifié sur un dépôt réel. L'appel est fait ici plutôt que dans
    # `diff_for` : dans l'arbre de travail, un renommage non indexé n'est
    # de toute façon pas détectable.
    try:
        diff.find_similar()
    except pygit2.GitError:
        pass  # un diff sans appariement reste exploitable

    return diff


def _to_file_diff(path: str, patch) -> FileDiff:
    """Convertit un `Patch` pygit2 en `FileDiff`.

    Partagé par `diff_for` (arbre de travail) et `diff_in_commit` (commit
    déjà fait) : la conversion est la même, seule la provenance du patch
    change.
    """
    if patch.delta.is_binary:
        # Vérifié : un binaire a 0 hunk et des line_stats à zéro. Afficher
        # ses octets serait illisible.
        return FileDiff(path=path, is_binary=True)

    hunks = tuple(
        DiffHunk(
            header=hunk.header.rstrip("\n"),
            lines=tuple(
                DiffLine(origin=line.origin, content=line.content.rstrip("\n"))
                for line in hunk.lines
            ),
        )
        for hunk in patch.hunks
    )

    _, added, removed = patch.line_stats
    return FileDiff(path=path, hunks=hunks, added=added, removed=removed)


def _classify(code: int) -> ChangeKind:
    """Le conflit prime : il interdit toute sélection."""
    if code & _CONFLICTED:
        return ChangeKind.CONFLICTED
    if code & _UNTRACKED:
        return ChangeKind.UNTRACKED
    if code & _DELETED:
        return ChangeKind.DELETED
    if code & FileStatus.INDEX_NEW:
        return ChangeKind.ADDED
    return ChangeKind.MODIFIED


def _is_binary(repo: pygit2.Repository, path: str) -> bool:
    patch = _patch_for(repo, path)
    return bool(patch and patch.delta.is_binary)


def _patch_for(repo: pygit2.Repository, path: str):
    """Patch d'un fichier, fichiers non suivis inclus.

    `INCLUDE_UNTRACKED` est indispensable : sans lui, un fichier qu'on
    vient de créer n'apparaît dans aucun diff. `SHOW_UNTRACKED_CONTENT`
    génère les hunks pour les fichiers non suivis (sinon pygit2 en a 0).
    """
    flags = pygit2.enums.DiffOption.INCLUDE_UNTRACKED | pygit2.enums.DiffOption.SHOW_UNTRACKED_CONTENT
    try:
        diff = repo.diff(
            repo.revparse_single("HEAD").tree
            if not repo.head_is_unborn
            else None,
            flags=flags,
        )
    except (pygit2.GitError, KeyError):
        try:
            diff = repo.diff(flags=flags)
        except (pygit2.GitError, ValueError):
            return None

    for patch in diff:
        if patch.delta.new_file.path == path:
            return patch
        if patch.delta.old_file.path == path:
            return patch
    return None
