"""Lecture des commits pour l'affichage — §4.2.1.

La compression du graphe est visuelle : les commits masqués restent dans le
modèle, portés par les arêtes. Ce module les relit pour les présenter.

Aucune dépendance à Qt : `ui/` appelle ces fonctions, jamais pygit2
directement.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

import pygit2

from tortoisepy.core.model import DisplayGraph, GraphEdge, Oid


@dataclass(frozen=True)
class CommitInfo:
    """Un commit, prêt à être affiché."""

    oid: Oid
    summary: str
    """Première ligne du message."""

    message: str
    author_name: str
    author_email: str
    when: datetime
    parent_count: int

    own: bool = True
    """Ce commit a-t-il été ajouté par la branche cliquée ?

    Vrai pour les commits situés entre ce nœud et le précédent du graphe —
    exactement ce que l'étiquette de l'arête annonce. Faux pour
    l'historique plus ancien, hérité des branches en dessous."""

    @property
    def short_oid(self) -> str:
        return self.oid[:8]

    @property
    def is_merge(self) -> bool:
        return self.parent_count >= 2


def read_commit(repo: pygit2.Repository, oid: Oid) -> CommitInfo | None:
    """Lit un commit. Retourne `None` s'il est introuvable ou illisible."""
    try:
        commit = repo.get(pygit2.Oid(hex=oid)).peel(pygit2.Commit)
    except (pygit2.GitError, ValueError, KeyError, AttributeError, TypeError):
        return None

    return CommitInfo(
        oid=str(commit.id),
        summary=_first_line(commit.message),
        message=commit.message.strip(),
        author_name=commit.author.name,
        author_email=commit.author.email,
        when=_when(commit.author),
        parent_count=len(commit.parents),
    )


def commits_on_edge(
    repo: pygit2.Repository, edge: GraphEdge
) -> tuple[CommitInfo, ...]:
    """Commits masqués par une arête, du plus récent au plus ancien.

    Le nœud descendant est inclus en tête : c'est le commit que porte la
    branche, celui que l'utilisateur voit. Les `skipped` suivent, dans
    l'ordre inverse de leur stockage (qui va du plus ancien au plus récent).
    """
    oids = [edge.descendant, *reversed(edge.skipped)]
    return tuple(
        info for oid in oids if (info := read_commit(repo, oid)) is not None
    )


def commits_for_node(
    repo: pygit2.Repository, graph: DisplayGraph, oid: Oid
) -> tuple[CommitInfo, ...]:
    """Commits à afficher au double-clic sur un nœud.

    **Tout** l'historique de la branche est retourné, du plus récent au
    plus ancien — pas seulement ce que la branche a ajouté. Les commits
    qui lui sont propres portent `own=True` : ce sont ceux que l'arête
    entrante masque, exactement ce qu'annonce son étiquette. Les plus
    anciens, hérités des branches en dessous, portent `own=False`.

    Voir un commit ancien sans pouvoir le distinguer serait trompeur ; ne
    pas le voir du tout obligerait à cliquer chaque nœud pour reconstituer
    l'historique.
    """
    own = _own_oids(graph, oid)
    return _history(repo, oid, own)


def _first_line(message: str) -> str:
    line = message.strip().split("\n", 1)[0]
    return line.strip() or "(sans message)"


def _when(signature: pygit2.Signature) -> datetime:
    """Date du commit dans son fuseau d'origine.

    `offset` est en minutes ; le convertir garde l'heure telle que l'auteur
    l'a vécue, plutôt qu'une heure UTC qui surprendrait.
    """
    try:
        tz = timezone(timedelta(minutes=signature.offset))
        return datetime.fromtimestamp(signature.time, tz)
    except (ValueError, OSError, OverflowError):
        return datetime.fromtimestamp(0, timezone.utc)


def _walk_back(
    repo: pygit2.Repository, oid: Oid, graph: DisplayGraph, limit: int = 200
) -> tuple[CommitInfo, ...]:
    """Remonte l'historique depuis un commit, jusqu'au nœud affiché suivant.

    Sert aux nœuds sans arête entrante : une racine, ou un nœud dont la
    jonction amont a été masquée. `limit` évite de parcourir tout un
    historique de plusieurs milliers de commits pour un panneau latéral.
    """
    others = {node.oid for node in graph.nodes} - {oid}
    collected: list[CommitInfo] = []

    try:
        walker = repo.walk(pygit2.Oid(hex=oid), pygit2.GIT_SORT_TOPOLOGICAL)
    except (pygit2.GitError, ValueError, KeyError):
        info = read_commit(repo, oid)
        return (info,) if info is not None else ()

    for commit in walker:
        current = str(commit.id)
        if current != oid and current in others:
            break  # on a rejoint un autre nœud du graphe
        info = read_commit(repo, current)
        if info is not None:
            collected.append(info)
        if len(collected) >= limit:
            break

    return tuple(collected)


def _own_oids(graph: DisplayGraph, oid: Oid) -> set[Oid]:
    """OID des commits propres à ce nœud : lui-même et ses `skipped`.

    Sur un merge, l'arête la plus chargée est retenue — celle qui masque
    le plus de travail.
    """
    own = {oid}

    incoming = [e for e in graph.edges if e.descendant == oid]
    if incoming:
        edge = max(incoming, key=lambda e: e.skipped_count)
        own.update(edge.skipped)

    return own


def _history(
    repo: pygit2.Repository,
    oid: Oid,
    own: set[Oid],
    limit: int = 500,
) -> tuple[CommitInfo, ...]:
    """Historique complet depuis un commit, chaque entrée marquée.

    `limit` borne le parcours : un panneau latéral n'a pas à charger
    plusieurs milliers de commits, et personne ne les lira.
    """
    try:
        walker = repo.walk(pygit2.Oid(hex=oid), pygit2.GIT_SORT_TOPOLOGICAL)
    except (pygit2.GitError, ValueError, KeyError):
        info = read_commit(repo, oid)
        return (info,) if info is not None else ()

    collected: list[CommitInfo] = []
    for commit in walker:
        current = str(commit.id)
        info = read_commit(repo, current)
        if info is None:
            continue
        collected.append(replace(info, own=current in own))
        if len(collected) >= limit:
            break

    return tuple(collected)
