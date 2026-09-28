"""Lecture des commits pour l'affichage — §4.2.1.

La compression du graphe est visuelle : les commits masqués restent dans le
modèle, portés par les arêtes. Ce module les relit pour les présenter.

Aucune dépendance à Qt : `ui/` appelle ces fonctions, jamais pygit2
directement.
"""

from __future__ import annotations

from dataclasses import dataclass
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

    Ce sont ceux que l'arête entrante masque : exactement ce qu'annonce son
    étiquette (« 40 commits »), plus le commit du nœud lui-même.

    Un nœud sans arête entrante — une racine, ou un nœud dont la jonction
    amont est masquée — fait remonter son historique réel.
    """
    incoming = [e for e in graph.edges if e.descendant == oid]

    if not incoming:
        # Aucune arête entrante : soit c'est une racine, soit les jonctions
        # qui portaient les commits sautés ont été retirées de l'affichage.
        # Dans les deux cas on remonte l'historique réel, sinon les commits
        # deviendraient inatteignables — ce que §4.2.1 interdit.
        return _walk_back(repo, oid, graph)

    # Plusieurs arêtes entrantes (un merge) : on prend la plus chargée,
    # celle qui masque le plus de travail.
    edge = max(incoming, key=lambda e: e.skipped_count)
    return commits_on_edge(repo, edge)


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
