"""Couleurs, police et métriques — §4.3, §4.4.

Un module unique, pour que les couleurs restent paramétrables sans toucher
au moteur de rendu.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPalette
from PySide6.QtWidgets import QApplication

from tortoisepy.core.model import DisplayNode, NodeKind, Ref, RefType
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

    current_branch: QColor = field(default_factory=lambda: QColor(190, 50, 40))     # rouge
    local_branch: QColor = field(default_factory=lambda: QColor(120, 200, 120))     # vert
    remote_branch: QColor = field(default_factory=lambda: QColor(250, 222, 180))    # beige / pêche
    tag: QColor = field(default_factory=lambda: QColor(250, 240, 130))              # jaune
    stash: QColor = field(default_factory=lambda: QColor(150, 150, 150))            # gris
    junction: QColor = field(default_factory=lambda: QColor(245, 245, 245))         # blanc cassé, discret
    selected: QColor = field(default_factory=lambda: QColor(160, 30, 30))           # rouge foncé
    selected_text: QColor = field(default_factory=lambda: QColor(255, 255, 255))
    text: QColor = field(default_factory=lambda: QColor(20, 20, 20))
    border: QColor = field(default_factory=lambda: QColor(110, 110, 110))
    edge: QColor = field(default_factory=lambda: QColor(30, 30, 30))
    background: QColor = field(default_factory=lambda: QColor(255, 255, 255))


PALETTE = Palette()


UNPUSHED_MARKER = QColor(230, 140, 30)
WORKING_FILL = QColor(248, 248, 248)
WORKING_BORDER = QColor(140, 140, 140)
WORKING_TEXT = QColor(90, 90, 90)
"""Nœud « Uncommitted changes » : gris clair, bordure pointillée.

Volontairement effacé — il signale, il ne réclame pas l'attention
comme une branche.
"""

"""Travail non commité sur la branche courante.

Bleu plutôt qu'orange : la pastille des commits non poussés est déjà
orange, et les deux peuvent apparaître sur le même nœud.
"""
"""Pastille des branches ayant des commits non poussés.

Orange : ni le vert de HEAD, ni le jaune des branches locales, ni le rouge
de la sélection — la marque doit se lire comme une information nouvelle,
pas comme un changement d'état du nœud."""

UNPUSHED_MARKER_RADIUS = 4.0


DIFF_ADDED = QColor(228, 245, 228)
"""Fond des lignes ajoutées, thème clair — vert pâle, lisible en texte noir."""

DIFF_REMOVED = QColor(250, 228, 228)
"""Fond des lignes supprimées, thème clair — rouge pâle."""

DIFF_ADDED_TEXT = QColor(22, 101, 52)
"""Texte des lignes ajoutées, thème clair — vert foncé (6.3:1 sur son fond)."""

DIFF_REMOVED_TEXT = QColor(140, 26, 30)
"""Texte des lignes supprimées, thème clair — rouge foncé (7.6:1)."""

DIFF_ADDED_DARK = QColor(26, 58, 34)
"""Fond des lignes ajoutées, thème sombre.

Les fonds pâles du thème clair sont inutilisables ici : mesuré, du texte
clair (238, 238, 238) sur (228, 245, 228) donne **1.02:1** — la ligne
ajoutée disparaît sous son propre surlignage. Ce vert sombre remonte à
10.8:1."""

DIFF_REMOVED_DARK = QColor(70, 28, 32)
"""Fond des lignes supprimées, thème sombre (12.5:1 en texte clair)."""

DIFF_ADDED_TEXT_DARK = QColor(126, 231, 135)
"""Texte des lignes ajoutées, thème sombre — vert vif (8.2:1 sur son fond)."""

DIFF_REMOVED_TEXT_DARK = QColor(255, 123, 114)
"""Texte des lignes supprimées, thème sombre — rouge vif (5.8:1)."""

DIFF_HEADER = QColor(110, 110, 122)
"""Couleur des en-têtes de hunk (`@@ -14,7 +14,9 @@`).

Écart avec la maquette d'origine (120, 120, 130) : son contraste sur fond
blanc est de 4.37:1, sous le seuil WCAG AA de 4.5:1 pour du texte normal.
(110, 110, 122) monte à 5.03:1 tout en restant visuellement gris — un
choix plus sûr, l'utilisateur ayant déjà rejeté une teinte trop pâle
ailleurs dans ce projet ("on voit rien")."""

DIFF_HEADER_DARK = QColor(150, 150, 162)
"""En-têtes de hunk, thème sombre — le gris du thème clair y est trop sombre."""


def is_dark_theme() -> bool:
    """Le système est-il en thème sombre ?

    Lu sur la palette Qt plutôt que codé en dur : macOS bascule le thème
    sans prévenir l'application, et une couleur pensée pour un fond blanc
    devient illisible sur fond noir (mesuré : 1.02:1).
    """
    app = QApplication.instance()
    if app is None:
        return False
    return app.palette().color(QPalette.ColorRole.Base).lightness() < 128


SYNTAX_CLAIR = {
    "keyword": QColor(140, 40, 160),
    "string": QColor(20, 110, 60),
    "comment": QColor(100, 100, 100),
    "number": QColor(30, 80, 180),
    "name": QColor(30, 70, 160),
}
"""Couleurs de syntaxe, thème clair.

**Mesurées sur les DEUX fonds de diff**, pas sur le fond de la fenêtre :
une ligne colorée porte déjà un vert ou un rouge pâle, et c'est là que
le texte doit rester lisible. Pire contraste de chaque teinte, sur fond
de suppression :

    keyword 5.9:1   string 5.2:1   number 6.0:1   name 7.1:1
    comment 4.9:1

Le commentaire est le plus discret des cinq, volontairement — il doit
s'effacer — mais reste au-dessus du seuil WCAG AA de 4.5:1. Une première
version à (110,110,110) tombait à 4.2:1.
"""

SYNTAX_SOMBRE = {
    "keyword": QColor(220, 150, 240),
    "string": QColor(140, 220, 170),
    "comment": QColor(160, 160, 160),
    "number": QColor(150, 190, 255),
    "name": QColor(150, 195, 255),
}
"""Couleurs de syntaxe, thème sombre.

Pire contraste sur fond d'ajout sombre :

    keyword 5.8:1   string 7.7:1   number 6.6:1   name 6.9:1
    comment 4.8:1
"""


TAB_EN_ESPACES = 4
"""Largeur d'une tabulation, en espaces.

Signalé par l'utilisateur : « des soucis d'indentation ». Qt place ses
taquets à 80 px, soit 8,9 espaces dans la police du code (mesuré) —
trois tabulations repoussaient le texte de 27 espaces, et un fichier PHP
indenté par tabulations partait hors de l'écran.

Quatre est la convention de PHP comme de Python. Le défaut précédait la
coloration syntaxique ; elle l'a seulement rendu visible.
"""


def apply_tab_width(widget) -> None:
    """Règle la largeur des tabulations sur la police du widget.

    En pixels et non en caractères : `setTabStopDistance` n'accepte que
    des pixels, et la largeur d'une espace dépend de la police.
    """
    metriques = QFontMetricsF(widget.font())
    widget.setTabStopDistance(
        TAB_EN_ESPACES * metriques.horizontalAdvance(" ")
    )


def syntax_colors() -> dict[str, QColor]:
    """Couleurs de syntaxe adaptées au thème courant.

    Cinq teintes seulement : dans un diff, l'information principale
    reste « ajouté » ou « supprimé », et une palette plus riche la
    noierait.
    """
    return SYNTAX_SOMBRE if is_dark_theme() else SYNTAX_CLAIR


def diff_colors() -> dict[str, QColor | None]:
    """Couleurs du diff adaptées au thème courant.

    Renvoie, pour chaque origine de ligne (`+`, `-`, contexte), le fond et
    la couleur du texte. Le contexte n'a pas de fond : le surligner
    attirerait l'œil sur ce qui n'a pas changé.
    """
    if is_dark_theme():
        return {
            "added_bg": DIFF_ADDED_DARK,
            "added_fg": DIFF_ADDED_TEXT_DARK,
            "removed_bg": DIFF_REMOVED_DARK,
            "removed_fg": DIFF_REMOVED_TEXT_DARK,
            "header_fg": DIFF_HEADER_DARK,
        }
    return {
        "added_bg": DIFF_ADDED,
        "added_fg": DIFF_ADDED_TEXT,
        "removed_bg": DIFF_REMOVED,
        "removed_fg": DIFF_REMOVED_TEXT,
        "header_fg": DIFF_HEADER,
    }


def node_color(node: DisplayNode, selected: bool) -> QColor:
    """Couleur de remplissage d'un nœud.

    La sélection prime sur le type : un nœud sélectionné est toujours rouge
    foncé, quelle que soit sa nature (§4.3).
    """
    # Le nœud de travail garde son fond clair MÊME sélectionné : son
    # `paint` l'impose de toute façon, et laisser la sélection renvoyer
    # du rouge faisait passer le texte en blanc — invisible sur clair
    # (signalé par l'utilisateur, capture à l'appui).
    if node.kind is NodeKind.WORKING:
        return WORKING_FILL

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


@dataclass(frozen=True)
class RefRow:
    """Une ligne d'un nœud : son texte et la couleur de sa bande."""

    label: str
    colour: QColor


def ref_rows(node: DisplayNode, current_branch: str | None = None) -> tuple[RefRow, ...]:
    """Les lignes d'un nœud, chacune colorée selon le type de sa ref.

    Vert pour une branche locale, **rouge** pour la branche courante,
    beige pour une distante, jaune pour un tag — demandé par
    l'utilisateur, capture de TortoiseGit à l'appui.

    `current_branch` est le nom de la branche courante, ou `None` si HEAD
    est détachée. Sans lui, les deux cas seraient **indiscernables** :
    vérifié sur de vrais dépôts, un nœud attaché porte
    `['develop', 'HEAD']` et un nœud détaché `['main', 'HEAD']` — même
    forme, sens opposé.
    """
    if node.kind is NodeKind.WORKING:
        # Jamais l'OID : c'est une sentinelle, elle n'apprendrait rien.
        return (RefRow(label="Uncommitted changes", colour=WORKING_FILL),)

    if not node.refs:
        return (RefRow(label=node.oid[:8], colour=_kind_colour(node)),)

    attachee = current_branch is not None and any(
        ref.type is RefType.LOCAL_BRANCH and ref.name == current_branch
        for ref in node.refs
    )

    rows: list[RefRow] = []
    for ref in node.refs:
        if ref.type is RefType.HEAD:
            # Masquée quand une branche locale porte déjà l'information.
            # En détaché, elle est le **seul** repère du nœud courant :
            # sans elle, `main` s'afficherait en vert comme une branche
            # ordinaire alors qu'on n'est pas dessus (vérifié).
            if attachee:
                continue
            rows.append(RefRow(label=ref.name, colour=PALETTE.current_branch))
            continue

        rows.append(RefRow(label=ref.name, colour=_ref_colour(ref, current_branch)))

    return tuple(rows)


def _ref_colour(ref: Ref, current_branch: str | None) -> QColor:
    """Couleur d'une ref selon son type, et selon qu'elle est courante."""
    if ref.type is RefType.LOCAL_BRANCH:
        if current_branch is not None and ref.name == current_branch:
            return PALETTE.current_branch
        return PALETTE.local_branch
    if ref.type is RefType.REMOTE_BRANCH:
        return PALETTE.remote_branch
    if ref.type is RefType.TAG:
        return PALETTE.tag
    if ref.type is RefType.STASH:
        return PALETTE.stash
    return PALETTE.junction


def _kind_colour(node: DisplayNode) -> QColor:
    """Couleur d'un nœud sans ref : jonction ou stash."""
    if node.kind is NodeKind.STASH:
        return PALETTE.stash
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

    def __init__(
        self, font: QFont | None = None, current_branch: str | None = None
    ):
        self._metrics = QFontMetricsF(font or node_font())
        # Même information que le dessin : sans elle, le nœud courant
        # réservait la place de sa ligne `HEAD` alors qu'elle est masquée
        # — 86 px pour 3 bandes, donc des bandes étirées (signalé par
        # l'utilisateur sur le nœud `develop` de vti).
        self._current_branch = current_branch

    def measure(self, node: DisplayNode) -> Size:
        labels = [row.label for row in ref_rows(node, self._current_branch)]
        widest = max(self._metrics.horizontalAdvance(label) for label in labels)
        line_height = self._metrics.height()
        return Size(
            width=widest + 2 * PADDING_X,
            height=len(labels) * line_height + 2 * PADDING_Y,
        )
