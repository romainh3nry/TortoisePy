"""Couleurs, police et métriques — §4.3, §4.4.

Un module unique, pour que les couleurs restent paramétrables sans toucher
au moteur de rendu.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtGui import QColor, QFont, QFontMetricsF

from tortoisepy.core.model import DisplayNode, NodeKind, RefType
from tortoisepy.layout.metrics import Size

NODE_FONT_FAMILY = "Menlo"
"""Police à chasse fixe, conformément à la capture (§4.4). Qt retombe sur
une police équivalente si elle est absente."""

NODE_FONT_SIZE = 12
NODE_RADIUS = 6.0
"""Rayon des coins arrondis (§4.4)."""

NODE_BORDER_WIDTH = 1.0
EDGE_WIDTH = 1.5
ARROW_SIZE = 9.0

PADDING_X = 12.0
PADDING_Y = 6.0


@dataclass(frozen=True)
class Palette:
    """Couleurs des nœuds, reconstituées de la capture TortoiseGit (§4.3)."""

    current_branch: QColor = field(default_factory=lambda: QColor(120, 200, 120))   # vert
    local_branch: QColor = field(default_factory=lambda: QColor(250, 240, 130))     # jaune
    remote_branch: QColor = field(default_factory=lambda: QColor(250, 222, 180))    # beige / pêche
    tag: QColor = field(default_factory=lambda: QColor(250, 240, 130))              # jaune, comme les locales
    stash: QColor = field(default_factory=lambda: QColor(150, 150, 150))            # gris
    junction: QColor = field(default_factory=lambda: QColor(245, 245, 245))         # blanc cassé, discret
    selected: QColor = field(default_factory=lambda: QColor(160, 30, 30))           # rouge foncé
    selected_text: QColor = field(default_factory=lambda: QColor(255, 255, 255))
    text: QColor = field(default_factory=lambda: QColor(20, 20, 20))
    border: QColor = field(default_factory=lambda: QColor(110, 110, 110))
    edge: QColor = field(default_factory=lambda: QColor(30, 30, 30))
    background: QColor = field(default_factory=lambda: QColor(255, 255, 255))


PALETTE = Palette()


def node_color(node: DisplayNode, selected: bool) -> QColor:
    """Couleur de remplissage d'un nœud.

    La sélection prime sur le type : un nœud sélectionné est toujours rouge
    foncé, quelle que soit sa nature (§4.3).
    """
    if selected:
        return PALETTE.selected

    if node.kind is NodeKind.STASH:
        return PALETTE.stash
    if node.kind is NodeKind.JUNCTION:
        return PALETTE.junction

    types = {ref.type for ref in node.refs}

    # HEAD d'abord : un nœud portant HEAD est le nœud courant, même s'il
    # porte aussi une branche locale.
    if RefType.HEAD in types:
        return PALETTE.current_branch
    if RefType.LOCAL_BRANCH in types:
        return PALETTE.local_branch
    if RefType.TAG in types:
        return PALETTE.tag
    if RefType.REMOTE_BRANCH in types:
        return PALETTE.remote_branch

    return PALETTE.junction


def text_color(selected: bool) -> QColor:
    return PALETTE.selected_text if selected else PALETTE.text


def node_font() -> QFont:
    return QFont(NODE_FONT_FAMILY, NODE_FONT_SIZE)


def node_labels(node: DisplayNode) -> tuple[str, ...]:
    """Lignes affichées dans le nœud : ses refs, ou son OID court (§4.3)."""
    if node.refs:
        return tuple(ref.name for ref in node.refs)
    return (node.oid[:8],)


class QtMeasurer:
    """Mesure réelle, avec la police effective.

    Implémente le protocole `NodeMeasurer` de la phase 2 : `layout/` obtient
    des dimensions exactes sans jamais importer Qt.
    """

    def __init__(self, font: QFont | None = None):
        self._metrics = QFontMetricsF(font or node_font())

    def measure(self, node: DisplayNode) -> Size:
        labels = node_labels(node)
        widest = max(self._metrics.horizontalAdvance(label) for label in labels)
        line_height = self._metrics.height()
        return Size(
            width=widest + 2 * PADDING_X,
            height=len(labels) * line_height + 2 * PADDING_Y,
        )
