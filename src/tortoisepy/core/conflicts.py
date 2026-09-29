"""Lister et résoudre les conflits — §6 de la spec phase 8.

Résoudre, ici, c'est choisir un camp par fichier (D12) : ni éditeur de
fusion, ni choix ligne à ligne. Cela couvre la majorité des cas sans
ouvrir un chantier à soi seul.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from enum import Enum

import pygit2
from pygit2.enums import FileMode

from tortoisepy.core.results import OperationResult, failed, guarded, succeeded


class Side(Enum):
    OURS = "ours"
    THEIRS = "theirs"


@dataclass(frozen=True)
class ConflictedFile:
    path: str
    has_ours: bool
    has_theirs: bool
    is_binary: bool = False

    @property
    def is_delete_modify(self) -> bool:
        """Un côté a supprimé le fichier, l'autre l'a modifié.

        Choisir « le supprimé » revient à effacer le fichier ; l'interface
        doit le dire clairement plutôt que de proposer un contenu vide.
        """
        return self.has_ours != self.has_theirs


def list_conflicts(repo: pygit2.Repository) -> tuple[ConflictedFile, ...]:
    """Fichiers en conflit, triés par chemin."""
    conflicts = repo.index.conflicts
    if conflicts is None:
        return ()

    found = []
    for _, ours, theirs in conflicts:
        entry = ours or theirs
        if entry is None:
            continue
        found.append(
            ConflictedFile(
                path=entry.path,
                has_ours=ours is not None,
                has_theirs=theirs is not None,
                is_binary=_is_binary(repo, ours, theirs),
            )
        )
    return tuple(sorted(found, key=lambda c: c.path))


@guarded("Résolution", changed_on_error=True)
def resolve_with(
    repo: pygit2.Repository, path: str, side: Side
) -> OperationResult:
    """Retient un des deux camps pour ce fichier.

    Vérifié : retirer l'entrée de `index.conflicts`, ajouter l'`IndexEntry`
    du côté choisi, écrire l'index, puis récrire le fichier de travail.
    """
    conflicts = repo.index.conflicts
    if conflicts is None:
        return failed("Résolution", "no conflict in progress")

    try:
        _, ours, theirs = conflicts[path]
    except KeyError:
        return failed("Résolution", f"no conflict on {path}")

    kept = ours if side is Side.OURS else theirs
    index = repo.index
    del index.conflicts[path]

    full = os.path.join(repo.workdir or "", path)
    if kept is None:
        # Le camp retenu a supprimé le fichier : le retirer réellement.
        if path in index:
            index.remove(path)
        if os.path.lexists(full):
            os.remove(full)
    else:
        index.add(pygit2.IndexEntry(path, kept.id, kept.mode))
        os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
        _write_workdir_entry(repo, full, kept)

    index.write()
    return succeeded(f"Resolved {path} ({side.value})")


@guarded("Fusion", changed_on_error=True)
def conclude_merge(repo: pygit2.Repository) -> OperationResult:
    """Crée le commit de fusion une fois tout résolu.

    Refuse tant qu'il reste un conflit : le commit contiendrait des
    marqueurs `<<<<<<<` (règle de la phase 6).
    """
    remaining = list_conflicts(repo)
    if remaining:
        names = ", ".join(c.path for c in remaining)
        return failed(
            "Fusion", f"unresolved conflicts remain: {names}",
            repository_changed=False,
        )

    their_head = _merge_head(repo)
    if their_head is None:
        return failed(
            "Fusion", "no merge in progress", repository_changed=False
        )

    signature = _signature(repo)
    tree = repo.index.write_tree()
    repo.create_commit(
        "HEAD", signature, signature, "Merge remote-tracking branch",
        tree, [repo.head.target, their_head],
    )
    # Sans ce nettoyage, `MERGE_HEAD` traîne et l'interface croit la
    # fusion toujours en cours (leçon de la phase 7).
    repo.state_cleanup()
    return succeeded("Merge completed")


def _write_workdir_entry(repo: pygit2.Repository, full: str, kept) -> None:
    """Écrit le côté retenu dans l'arbre de travail.

    Deux pièges corrigés après revue :

    1. `open(full, "wb")` sur un lien symbolique existant SUIT le lien et
       écrase sa cible — un fichier sans rapport avec le conflit serait
       détruit. On retire donc systématiquement toute entrée existante
       (`lexists`, pas `exists` : un lien mort doit quand même être vu)
       avant d'écrire quoi que ce soit.
    2. Le mode du blob retenu doit être respecté explicitement : un lien
       symbolique se recrée avec `os.symlink` (le contenu du blob *est*
       le chemin cible), un exécutable garde son bit +x. Rien de tout ça
       ne doit être deviné depuis l'état précédent du fichier sur disque.
    """
    if os.path.lexists(full):
        os.remove(full)

    blob = repo.get(kept.id)
    if stat.S_ISLNK(kept.mode):
        os.symlink(blob.data.decode(), full)
        return

    with open(full, "wb") as handle:
        handle.write(blob.data)
    if kept.mode == FileMode.BLOB_EXECUTABLE:
        os.chmod(full, 0o755)
    else:
        os.chmod(full, 0o644)


def _merge_head(repo: pygit2.Repository):
    """Tête de la branche fusionnée, lue dans `MERGE_HEAD`."""
    try:
        with open(os.path.join(repo.path, "MERGE_HEAD")) as handle:
            return pygit2.Oid(hex=handle.read().strip())
    except (OSError, ValueError):
        return None


def _is_binary(repo: pygit2.Repository, ours, theirs) -> bool:
    """Un contenu binaire ne se fusionne pas ligne à ligne."""
    for entry in (ours, theirs):
        if entry is None:
            continue
        try:
            if repo.get(entry.id).is_binary:
                return True
        except (KeyError, AttributeError):
            continue
    return False


def _signature(repo: pygit2.Repository) -> pygit2.Signature:
    try:
        return repo.default_signature
    except (KeyError, ValueError):
        return pygit2.Signature("tortoisePy", "tortoisepy@localhost")
