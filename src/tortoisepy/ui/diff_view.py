"""Affichage coloré d'un diff — §4.2.

Widget autonome : servira aussi au futur « Compare revisions » (§7.4).
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit

from tortoisepy.core.changes import FileDiff
from tortoisepy.core.word_diff import pair_lines, word_segments
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
            # Le mot changé ressort dans la ligne : sans cela, modifier
            # un mot dans une ligne longue affichait la ligne entière en
            # rouge puis en vert, et il fallait comparer à l'œil.
            marques = _marquer_les_mots(hunk.lines)
            for index, line in enumerate(hunk.lines):
                # Fond ET texte colorés : le fond seul ne suffit pas —
                # en thème sombre, du texte clair sur un fond pâle tombe à
                # 1.02:1 et la ligne ajoutée devient illisible.
                self._append(
                    f"{line.origin}{line.content}",
                    _foreground(line.origin, colors),
                    _background(line.origin, colors),
                    marques.get(index),
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
        segments: tuple | None = None,
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

        if segments is None:
            cursor.insertText(text, fmt)
        else:
            # Le caractère d'origine (`+`, `-`) précède le contenu et
            # n'appartient à aucun segment : il garde le format de base.
            cursor.insertText(text[:1], fmt)
            gras = QTextCharFormat(fmt)
            gras.setFontWeight(QFont.Weight.Bold)
            for segment in segments:
                cursor.insertText(
                    segment.text, gras if segment.changed else fmt
                )

        self._lines += 1


def _marquer_les_mots(lines) -> dict:
    """Pour chaque ligne modifiée, ses segments mot à mot.

    Les lignes `-` et `+` d'un même bloc sont appariées dans l'ordre :
    une suppression sans contrepartie, ou deux lignes trop
    dissemblables, ne reçoivent rien et s'affichent comme avant.

    Rendre une ligne entière en gras reviendrait à ne rien marquer : le
    gras doit rester le signe d'un changement DANS la ligne.
    """
    retirees = [(i, l) for i, l in enumerate(lines) if l.origin == "-"]
    ajoutees = [(i, l) for i, l in enumerate(lines) if l.origin == "+"]

    marques: dict[int, tuple] = {}
    paires = pair_lines(
        tuple(l.content for _, l in retirees),
        tuple(l.content for _, l in ajoutees),
    )
    for index_retiree, index_ajoutee in paires:
        position_avant, ligne_avant = retirees[index_retiree]
        position_apres, ligne_apres = ajoutees[index_ajoutee]
        avant, apres = word_segments(ligne_avant.content, ligne_apres.content)
        marques[position_avant] = avant
        marques[position_apres] = apres

    return marques


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
