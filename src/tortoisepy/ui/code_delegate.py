"""Peindre une cellule de tableau avec sa coloration syntaxique.

Le blâme affiche du code dans un `QTreeWidget`. Un `QTreeWidgetItem` ne
porte qu'**une** couleur de texte par cellule : impossible d'y distinguer
un mot-clé d'une chaîne, là où `DiffView` et l'éditeur de fusion le font
déjà.

Un délégué peint la cellule lui-même, jeton par jeton, et laisse Qt
dessiner le fond — qui porte dans le blâme la bande alternée par commit,
son information principale.

Le découpage vient de `core.syntax`, commun au diff et à l'éditeur : une
seule grammaire de couleurs, et des contrastes mesurés une seule fois.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from tortoisepy.core.syntax import highlight
from tortoisepy.ui import theme


class CodeDelegate(QStyledItemDelegate):
    """Dessine le texte d'une colonne avec sa coloration syntaxique."""

    def __init__(self, parent=None, language: str | None = None,
                 column: int = 0):
        super().__init__(parent)
        self._language = language
        self._column = column
        # Relues à la construction : le thème du système peut avoir
        # basculé depuis le dernier affichage.
        self._couleurs = theme.syntax_colors()

    def paint(self, painter, option, index) -> None:
        """Peint la cellule : fond par Qt, texte par nous.

        Hors de la colonne de code, ou sans langage connu, on laisse Qt
        faire — une coloration devinée serait pire que pas de
        coloration.
        """
        if self._language is None or index.column() != self._column:
            super().paint(painter, option, index)
            return

        texte = index.data(Qt.ItemDataRole.DisplayRole) or ""
        # Les tabulations sont développées AVANT de peindre : `drawText`
        # leur donne 80 px, soit plus de huit espaces, et un fichier
        # indenté par tabulations partait hors de l'écran (signalé).
        # `setTabStopDistance` ne s'applique qu'aux champs de texte, pas
        # à un délégué qui peint lui-même.
        texte = texte.expandtabs(theme.TAB_EN_ESPACES)
        if not texte.strip():
            super().paint(painter, option, index)
            return

        # Le fond est peint par le style : il porte la bande alternée par
        # commit, et la redessiner nous-mêmes perdrait aussi la
        # surbrillance de sélection.
        copie = QStyleOptionViewItem(option)
        self.initStyleOption(copie, index)
        copie.text = ""
        style = copie.widget.style() if copie.widget else None
        if style is not None:
            style.drawControl(
                QStyle.ControlElement.CE_ItemViewItem, copie, painter,
                copie.widget,
            )

        painter.save()
        painter.setClipRect(option.rect)
        metriques = painter.fontMetrics()
        # Une marge à gauche, comme en pose Qt lui-même : sans elle le
        # texte colle au bord de la cellule.
        x = float(option.rect.left()) + 4.0
        base = option.rect.top() + (
            option.rect.height() + metriques.ascent() - metriques.descent()
        ) / 2

        for segment in highlight(texte, self._language):
            couleur = self._couleurs.get(segment.kind.value)
            painter.setPen(
                couleur if couleur is not None else option.palette.text().color()
            )
            painter.drawText(QRectF(x, base - metriques.ascent(),
                                    metriques.horizontalAdvance(segment.text),
                                    metriques.height()),
                             Qt.AlignmentFlag.AlignLeft
                             | Qt.AlignmentFlag.AlignVCenter,
                             segment.text)
            x += metriques.horizontalAdvance(segment.text)

        painter.restore()
