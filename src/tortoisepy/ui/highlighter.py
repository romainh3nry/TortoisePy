"""Coloration syntaxique d'un champ de texte éditable.

`DiffView` colore ligne par ligne au moment de l'affichage : son contenu
est figé, posé une fois. L'éditeur de fusion, lui, a une colonne qu'on
modifie — un format posé une fois ne tiendrait pas, et dès la première
frappe le code saisi resterait incolore.

`QSyntaxHighlighter` est la réponse de Qt : il rappelle le surligneur à
chaque bloc modifié, et seulement sur celui-là.

Le découpage vient de `core.syntax`, commun avec le diff : une seule
grammaire de couleurs à apprendre, et les contrastes n'ont été mesurés
qu'une fois.
"""

from __future__ import annotations

from PySide6.QtGui import QSyntaxHighlighter, QTextCharFormat

from tortoisepy.core.syntax import highlight
from tortoisepy.ui import theme


class CodeHighlighter(QSyntaxHighlighter):
    """Colore un document selon le langage d'un fichier."""

    def __init__(self, document, language: str | None):
        super().__init__(document)
        self._language = language
        # Les couleurs sont relues à la construction : le thème du
        # système peut avoir basculé depuis le dernier affichage.
        self._couleurs = theme.syntax_colors()

    def highlightBlock(self, text: str) -> None:  # noqa: N802 (API Qt)
        """Appelé par Qt pour chaque ligne modifiée.

        Qt ne redemande que les blocs touchés : colorer tout le document
        à chaque frappe coûterait cher sur un gros fichier.
        """
        if self._language is None or not text:
            return

        position = 0
        for segment in highlight(text, self._language):
            couleur = self._couleurs.get(segment.kind.value)
            if couleur is not None:
                format_ = QTextCharFormat()
                format_.setForeground(couleur)
                self.setFormat(position, len(segment.text), format_)
            position += len(segment.text)
