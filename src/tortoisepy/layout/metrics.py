"""Dimensions des nœuds et structures de placement.

`layout/` ne connaît pas la police de rendu : la mesure est injectée via le
protocole `NodeMeasurer`. `ui/` en fournira une implémentation fondée sur
QFontMetrics ; `MonospaceMeasurer` suffit aux tests et à une police à chasse
fixe, celle qu'utilise la capture de référence (§4.4).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from tortoisepy.core.model import DisplayNode, Oid

SHORT_OID_LENGTH = 8
"""Longueur de l'étiquette d'un nœud de jonction (§4.3)."""


@dataclass(frozen=True)
class Size:
    width: float
    height: float


@dataclass(frozen=True)
class Placement:
    """Un nœud posé. `x`/`y` désignent son coin bas-gauche.

    `y` croît vers le haut : un descendant a un `y` supérieur à son ancêtre.
    La conversion vers la convention écran appartient à `ui/`.
    """

    oid: Oid
    x: float
    y: float
    size: Size

    @property
    def left(self) -> float:
        return self.x

    @property
    def right(self) -> float:
        return self.x + self.size.width

    @property
    def bottom(self) -> float:
        return self.y

    @property
    def top(self) -> float:
        return self.y + self.size.height


@dataclass(frozen=True)
class LayoutResult:
    placements: tuple[Placement, ...]
    width: float
    height: float

    def placement(self, oid: Oid) -> Placement | None:
        for p in self.placements:
            if p.oid == oid:
                return p
        return None


class NodeMeasurer(Protocol):
    """Contrat de mesure. `ui/` l'implémentera avec QFontMetrics."""

    def measure(self, node: DisplayNode) -> Size: ...


@dataclass(frozen=True)
class MonospaceMeasurer:
    """Mesure pour une police à chasse fixe.

    Les valeurs par défaut correspondent à une police ~13 px : elles servent
    de base cohérente, `ui/` les remplacera par les métriques réelles.
    """

    char_width: float = 8.0
    line_height: float = 18.0
    padding_x: float = 12.0
    padding_y: float = 6.0

    def measure(self, node: DisplayNode) -> Size:
        labels = [ref.name for ref in node.refs] or [node.oid[:SHORT_OID_LENGTH]]
        longest = max(len(label) for label in labels)
        return Size(
            width=longest * self.char_width + 2 * self.padding_x,
            height=len(labels) * self.line_height + 2 * self.padding_y,
        )
