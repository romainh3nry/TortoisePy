"""Lister et résoudre les conflits — §6 de la spec phase 8.

Deux façons de résoudre :

  - **choisir un camp** (D12), qui couvre la majorité des cas ;
  - **composer un contenu** (`resolve_with_content`), pour les blocs que
    git marque en conflit alors qu'ils sont seulement voisins.

Le second cas a été signalé par l'utilisateur sur un rebase : deux clés
YAML sans rapport, `rate-limit:` et `twoFactorAuth:`, adjacentes dans le
fichier. Les garder toutes les deux était la bonne résolution, et aucun
camp seul ne convenait.
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


@dataclass(frozen=True)
class ConflictVersions:
    """Le texte des deux camps, pour les montrer côte à côte.

    `base` est l'ancêtre commun quand il existe : absent d'un conflit
    ajout/ajout, où aucun des deux camps ne part de quelque chose.
    """

    ours: str
    theirs: str
    base: str | None = None


def read_versions(
    repo: pygit2.Repository, path: str
) -> ConflictVersions | None:
    """Le contenu des deux camps d'un conflit, ou `None` s'il n'y en a pas.

    Sert à l'affichage en colonnes : l'interface montre « yours » et
    « theirs » et laisse composer le résultat entre les deux.

    Un camp absent (le fichier a été supprimé de ce côté) rend une chaîne
    vide plutôt que `None` : c'est bien ce que ce camp propose — rien —
    et l'afficher comme tel vaut mieux qu'une colonne manquante.
    """
    conflicts = repo.index.conflicts
    if conflicts is None:
        return None

    try:
        ancetre, notre, leur = conflicts[path]
    except KeyError:
        return None

    return ConflictVersions(
        ours=_texte(repo, notre),
        theirs=_texte(repo, leur),
        base=_texte(repo, ancetre) if ancetre is not None else None,
    )


def _texte(repo: pygit2.Repository, entree) -> str:
    """Le contenu d'une entrée d'index, décodé. Vide si elle est absente.

    `errors="replace"` : un fichier en conflit peut porter n'importe quel
    octet, et lever ici empêcherait d'afficher tout le reste.
    """
    if entree is None:
        return ""
    objet = repo.get(entree.id)
    if objet is None:
        return ""
    return objet.data.decode("utf-8", errors="replace")


@guarded("Résolution", changed_on_error=True)
def resolve_with_content(
    repo: pygit2.Repository, path: str, content: str
) -> OperationResult:
    """Résout un conflit avec un contenu composé par l'utilisateur.

    Signalé par l'utilisateur : deux blocs voisins mais indépendants
    (`rate-limit:` et `twoFactorAuth:`) que git marque en conflit. Les
    garder tous les deux est la bonne résolution, et ni « ours » ni
    « theirs » ne la permettait.

    Différence avec `resolve_with` : ce contenu **n'existe pas** dans la
    base d'objets, puisqu'il vient d'être écrit. Il faut donc créer le
    blob, sans quoi l'index référencerait un objet absent et le commit
    échouerait plus tard, loin de sa cause.

    Refuse un chemin qui n'est pas en conflit : écrire là écraserait un
    fichier que l'utilisateur n'a pas désigné (§7.0).
    """
    conflicts = repo.index.conflicts
    if conflicts is None:
        return failed("Résolution", "no conflict in progress")

    try:
        _, ours, theirs = conflicts[path]
    except KeyError:
        return failed("Résolution", f"no conflict on {path}")

    index = repo.index
    oid = repo.create_blob(content.encode("utf-8"))

    # Le mode vient du camp qui existe : un exécutable doit le rester, et
    # le deviner depuis le disque serait faux après une suppression.
    reference = ours or theirs
    mode = reference.mode if reference is not None else FileMode.BLOB

    del index.conflicts[path]
    index.add(pygit2.IndexEntry(path, oid, mode))

    full = os.path.join(repo.workdir or "", path)
    os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
    if os.path.lexists(full):
        # Jamais `open` sur un lien symbolique : il suivrait le lien et
        # écraserait sa cible, un fichier sans rapport avec le conflit.
        os.remove(full)
    with open(full, "wb") as handle:
        handle.write(content.encode("utf-8"))

    index.write()
    return succeeded(f"« {path} » résolu")


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

    # Sans `MERGE_HEAD`, le second parent est INCONNU. Signalé par
    # l'utilisateur : après avoir résolu ses conflits, « Resolve »
    # répondait « no merge in progress » et ses résolutions restaient
    # bloquées dans l'index — seul « Abort » restait, qui les aurait
    # détruites.
    #
    # On commite alors ordinairement, avec un seul parent : deviner le
    # second mentirait sur l'histoire du dépôt. Le travail est sauvé,
    # l'histoire reste honnête.
    if their_head is None:
        if not repo.status():
            return failed(
                "Fusion", "nothing to commit", repository_changed=False
            )

        signature = _signature(repo)
        tree = repo.index.write_tree()
        repo.create_commit(
            "HEAD", signature, signature,
            "Conflict resolution", tree, [repo.head.target],
        )
        repo.state_cleanup()
        return succeeded("Resolutions committed")

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
