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
    """`+` ajoutée, `-` supprimée, ` ` contexte, `=` fin de fichier
    sans saut de ligne."""

    content: str
    """Texte de la ligne, **sans** son saut de ligne — pour l'affichage."""

    raw: str = ""
    """Texte exact, saut de ligne compris.

    `content` est rogné pour l'affichage, ce qui efface une distinction
    que `core.staging` doit préserver : un fichier dont la dernière ligne
    n'a pas de saut de ligne ne doit pas en gagner un au commit.
    """


@dataclass(frozen=True)
class DiffHunk:
    header: str
    lines: tuple[DiffLine, ...]

    old_start: int = 0
    """Première ligne visée dans la version d'ORIGINE (1-indexée).

    Nécessaire pour recomposer un contenu à partir d'une partie des
    hunks seulement (`core.staging`) : l'en-tête la contient aussi
    (« @@ -120,7 +120,7 @@ »), mais la lire là serait fragile alors que
    pygit2 l'expose directement.
    """

    old_lines: int = 0
    """Nombre de lignes que ce hunk remplace dans la version d'origine."""


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

    # UN seul diff pour tous les fichiers : `_is_binary` le recalculait
    # par fichier, ce qui rendait l'ouverture de la fenêtre de commit
    # quadratique (14 s pour 300 fichiers, signalé par l'utilisateur).
    binaires = _binaires(
        _diff_en_cache(repo, contenu_non_suivi=False)
    )

    changes = [
        FileChange(
            path=path,
            kind=_classify(code),
            # Sans `SHOW_UNTRACKED_CONTENT`, le diff ne sait pas qu'un
            # fichier NON SUIVI est binaire : il n'en a pas lu le
            # contenu. On le détermine sur place — quelques octets par
            # fichier concerné, au lieu d'un scan de tout le dépôt.
            is_binary=(
                path in binaires
                or _binaire_sur_disque(repo, path, code)
            ),
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
                DiffLine(
                    origin=line.origin,
                    content=line.content.rstrip("\n"),
                    raw=line.content,
                )
                for line in hunk.lines
            ),
            old_start=hunk.old_start,
            old_lines=hunk.old_lines,
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


def _diff_du_depot(repo: pygit2.Repository, *, contenu_non_suivi: bool = True):
    """Diff complet de l'arbre de travail, fichiers non suivis inclus.

    **Deux diffs plutôt qu'un.** `tree.diff_to_workdir()` compare l'arbre
    directement au disque, et s'effondre sur un gros dépôt — mesuré sur
    un dépôt réel, pour UN seul fichier modifié :

        tree.diff_to_index(index)     5.9 ms
        index.diff_to_workdir()     431.8 ms
                                    ────────
                                      438 ms
        tree.diff_to_workdir()     5851.6 ms   <- 13x plus lent

    Passer par l'index est ce que fait `git status` lui-même (492 ms sur
    le même dépôt). Les deux diffs sont fusionnés par chemin : l'état du
    disque l'emporte, puisque c'est ce que l'utilisateur voit.

    `INCLUDE_UNTRACKED` est indispensable : sans lui, un fichier qu'on
    vient de créer n'apparaît nulle part. `SHOW_UNTRACKED_CONTENT` génère
    ses hunks (sinon pygit2 en a 0) — mesuré sans effet notable sur la
    durée, mais réservé aux appels qui affichent vraiment un contenu.
    """
    flags = pygit2.enums.DiffOption.INCLUDE_UNTRACKED
    if contenu_non_suivi:
        flags |= pygit2.enums.DiffOption.SHOW_UNTRACKED_CONTENT

    try:
        depuis_index = list(repo.index.diff_to_workdir(flags=flags))
    except (pygit2.GitError, ValueError):
        depuis_index = []

    if repo.head_is_unborn:
        return depuis_index

    try:
        arbre = repo.revparse_single("HEAD").tree
        indexes = list(arbre.diff_to_index(repo.index))
    except (pygit2.GitError, KeyError, ValueError):
        return depuis_index

    # Fusion par chemin : un fichier indexé PUIS modifié apparaît dans
    # les deux diffs. Le disque gagne — c'est l'état que l'utilisateur
    # voit et s'apprête à commiter.
    par_chemin = {_chemin_du_patch(p): p for p in indexes}
    par_chemin.update({_chemin_du_patch(p): p for p in depuis_index})
    return list(par_chemin.values())


def _chemin_du_patch(patch) -> str:
    """Chemin d'un patch — celui d'arrivée, ou de départ s'il est supprimé."""
    return patch.delta.new_file.path or patch.delta.old_file.path


_NON_SUIVI = (
    pygit2.enums.FileStatus.WT_NEW | pygit2.enums.FileStatus.INDEX_NEW
)


def _binaire_sur_disque(repo: pygit2.Repository, path: str, code: int) -> bool:
    """Un fichier NON SUIVI est-il binaire ?

    Même heuristique que git : un octet nul dans les premiers kilo-octets.
    Lu seulement pour les fichiers que `status()` signale comme nouveaux,
    donc jamais pour les milliers de fichiers ignorés d'un gros dépôt.
    """
    if not code & _NON_SUIVI:
        return False

    import os

    try:
        with open(os.path.join(repo.workdir or "", path), "rb") as fichier:
            return b"\0" in fichier.read(8000)
    except OSError:
        return False


def _binaires(diff) -> set[str]:
    """Chemins binaires d'un diff déjà calculé.

    Un seul parcours pour tous les fichiers : `_is_binary` recalculait le
    diff COMPLET à chaque appel, soit une fois par fichier. Mesuré sur
    300 fichiers modifiés — 26,5 ms par fichier, 14 s au total, alors
    qu'un diff seul coûte 24 ms.
    """
    if diff is None:
        return set()

    trouves = set()
    for patch in diff:
        if patch.delta.is_binary:
            trouves.add(patch.delta.new_file.path)
            trouves.add(patch.delta.old_file.path)
    return trouves


_cache_diff: tuple | None = None
"""(empreinte de l'arbre, diff). Mémoire d'un seul diff, le dernier.

`diff_for` recalculait le diff COMPLET du dépôt à chaque appel — donc à
chaque clic sur un fichier dans la fenêtre de commit. Mesuré sur 300
fichiers : 68 ms par clic, et le coût croît avec la taille du dépôt
(signalé par l'utilisateur sur un gros dépôt : « ça freeze »).
"""


def _empreinte_arbre(repo: pygit2.Repository) -> tuple:
    """Ce qui, en changeant, rend le diff périmé.

    `status()` ne suffit PAS : vérifié, il rend `WT_MODIFIED` aussi bien
    après la première qu'après la seconde modification d'un fichier. Un
    cache fondé sur lui seul servirait un diff périmé — pire qu'un diff
    lent, puisque l'utilisateur verrait de faux changements.

    On y ajoute donc la taille et la date de chaque fichier concerné :
    deux contenus différents ne les partagent qu'exceptionnellement, et
    le coût reste celui d'un `stat` par fichier modifié, pas par fichier
    du dépôt.
    """
    import os

    try:
        statut = sorted(repo.status().items())
    except pygit2.GitError:
        return (object(),)

    racine = repo.workdir or ""
    marques = []
    for chemin, code in statut:
        try:
            infos = os.stat(os.path.join(racine, chemin))
            marques.append((chemin, code, infos.st_size, infos.st_mtime_ns))
        except OSError:
            # Fichier supprimé entre `status()` et le `stat` : son absence
            # fait partie de l'empreinte.
            marques.append((chemin, code, None, None))

    return (tuple(marques), str(repo.path))


def _diff_en_cache(repo: pygit2.Repository, *, contenu_non_suivi: bool = True):
    """`_diff_du_depot`, mais réutilisé tant que l'arbre n'a pas bougé.

    Le diff est **matérialisé** en liste à la mise en cache : pygit2 lit
    les fichiers paresseusement, et un diff gardé tel quel lève
    « file changed before we could read it » dès qu'un fichier bouge
    sous lui (vérifié — c'est ce qui arrive en usage réel, entre deux
    clics de l'utilisateur).
    """
    global _cache_diff

    empreinte = (_empreinte_arbre(repo), contenu_non_suivi)
    if _cache_diff is not None and _cache_diff[0] == empreinte:
        return _cache_diff[1]

    diff = _diff_du_depot(repo, contenu_non_suivi=contenu_non_suivi)
    try:
        materialise = list(diff) if diff is not None else None
    except pygit2.GitError:
        # L'arbre a bougé pendant la lecture : on ne met rien en cache
        # et on laisse l'appelant retenter au prochain geste.
        _cache_diff = None
        return None

    _cache_diff = (empreinte, materialise)
    return materialise


def _patch_for(repo: pygit2.Repository, path: str):
    """Patch d'un seul fichier. Pour plusieurs, voir `_diff_du_depot`."""
    diff = _diff_en_cache(repo)
    if diff is None:
        return None

    for patch in diff:
        if patch.delta.new_file.path == path:
            return patch
        if patch.delta.old_file.path == path:
            return patch
    return None
