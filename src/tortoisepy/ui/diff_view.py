"""Affichage coloré d'un diff — §4.2.

Widget autonome : servira aussi au futur « Compare revisions » (§7.4).
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit

from tortoisepy.core.changes import FileDiff
from tortoisepy.ui import theme


class DiffView(QPlainTextEdit):
    """Diff en lecture seule, lignes colorées selon leur nature."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        font = QFont(theme.NODE_FONT_FAMILY, 11)
        font.setFixedPitch(True)
        self.setFont(font)

        self._lines = 0

    def show_diff(self, diff: FileDiff) -> None:
        """Remplace le contenu par le diff donné.

        Les couleurs sont relues à chaque affichage : le système peut avoir
        basculé entre thème clair et sombre depuis la dernière fois.
        """
        self.clear()
        colors = theme.diff_colors()

        if diff.is_binary:
            self._append(
                "fichier binaire — diff non affiché", colors["header_fg"]
            )
            return

        if not diff.hunks:
            self._append("aucune modification à afficher", colors["header_fg"])
            return

        for hunk in diff.hunks:
            self._append(hunk.header, colors["header_fg"])
            for line in hunk.lines:
                # Fond ET texte colorés : le fond seul ne suffit pas —
                # en thème sombre, du texte clair sur un fond pâle tombe à
                # 1.02:1 et la ligne ajoutée devient illisible.
                self._append(
                    f"{line.origin}{line.content}",
                    _foreground(line.origin, colors),
                    _background(line.origin, colors),
                )

    def clear(self) -> None:
        super().clear()
        self._lines = 0

    def line_count(self) -> int:
        return self._lines

    def text(self) -> str:
        return self.toPlainText()

    def _append(
        self,
        text: str,
        colour: QColor | None = None,
        background: QColor | None = None,
    ) -> None:
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        fmt = QTextCharFormat()
        if colour is not None:
            fmt.setForeground(colour)
        if background is not None:
            fmt.setBackground(background)

        if self._lines:
            cursor.insertBlock()
        cursor.insertText(text, fmt)
        self._lines += 1


def _background(origin: str, colors: dict) -> QColor | None:
    """Fond d'une ligne selon son origine. Le contexte reste neutre."""
    if origin == "+":
        return colors["added_bg"]
    if origin == "-":
        return colors["removed_bg"]
    return None


def _foreground(origin: str, colors: dict) -> QColor | None:
    """Couleur du texte : vert pour un ajout, rouge pour une suppression.

    Le contexte garde la couleur par défaut du widget, qui suit déjà le
    thème du système.
    """
    if origin == "+":
        return colors["added_fg"]
    if origin == "-":
        return colors["removed_fg"]
    return None
