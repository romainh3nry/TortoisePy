"""Modèle du graphe affiché.

Voir §4 de la spec. Trois niveaux distincts :
  - le DAG Git réel (commits et parents), manipulé par graph.py ;
  - les refs, collectées par refs.py ;
  - le graphe affiché (DisplayNode / GraphEdge), défini ici.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

Oid = str
"""OID de commit sous forme hexadécimale. Alias pour la lisibilité."""


class RefType(Enum):
    LOCAL_BRANCH = "local_branch"
    REMOTE_BRANCH = "remote_branch"
    TAG = "tag"
    HEAD = "head"
    STASH = "stash"


class NodeKind(Enum):
    REF = "ref"
    """Nœud portant au moins une ref."""

    JUNCTION = "junction"
    """Point de jonction topologique sans ref : merge-base, racine, merge."""

    STASH = "stash"
    """Stash, rattaché hors du calcul topologique (§4.1)."""


@dataclass(frozen=True)
class Ref:
    name: str
    type: RefType
    target: Oid
    """OID du commit, tags annotés déjà déréférencés."""


@dataclass(frozen=True)
class DisplayNode:
    oid: Oid
    kind: NodeKind
    refs: tuple[Ref, ...]

    @property
    def is_junction(self) -> bool:
        return self.kind is NodeKind.JUNCTION


@dataclass(frozen=True)
class GraphEdge:
    """Arête du graphe compressé.

    Les champs sont nommés ancestor/descendant et non from/to : le modèle
    exprime une relation Git, pas une direction de dessin. Le sens de la
    flèche est une décision du rendu (§4.2).
    """

    ancestor: Oid
    descendant: Oid
    skipped: tuple[Oid, ...]
    """OID des commits compressés, du plus ancien au plus récent (§4.2.1)."""

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)


@dataclass(frozen=True)
class DisplayGraph:
    nodes: tuple[DisplayNode, ...]
    edges: tuple[GraphEdge, ...]

    def node(self, oid: Oid) -> DisplayNode | None:
        for node in self.nodes:
            if node.oid == oid:
                return node
        return None
