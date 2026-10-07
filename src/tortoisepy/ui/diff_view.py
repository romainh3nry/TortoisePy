"""Affichage coloré d'un diff — §4.2.

Widget autonome : servira aussi au futur « Compare revisions » (§7.4).
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit

from tortoisepy.core.changes import FileDiff
from tortoisepy.core.syntax import highlight, language_for
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
        theme.apply_tab_width(self)

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

        # Le langage une seule fois par fichier : l'extension ne change
        # pas d'un hunk à l'autre, et `get_lexer_for_filename` coûte plus
        # que la coloration elle-même.
        langue = language_for(diff.path)
        syntaxe = theme.syntax_colors()

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
                    highlight(line.content, langue),
                    syntaxe,
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
        jetons: tuple = (),
        couleurs_syntaxe: dict | None = None,
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

        if segments is None and not jetons:
            cursor.insertText(text, fmt)
            self._lines += 1
            return

        # Le caractère d'origine (`+`, `-`) précède le contenu et
        # n'appartient ni aux mots changés ni au code : il garde le
        # format du diff. Le colorer selon le hasard du lexer
        # brouillerait son sens.
        cursor.insertText(text[:1], fmt)

        # Trois informations se superposent sur la même ligne : le FOND
        # dit ajouté/supprimé, le GRAS dit quel mot a changé, la COULEUR
        # dit quel genre de jeton. Les deux découpages — mots et jetons —
        # ne coïncident pas, d'où la fusion caractère par caractère.
        contenu = text[1:]
        changes = _positions_changees(segments, len(contenu))
        teintes = _teintes_par_position(jetons, couleurs_syntaxe,
                                        len(contenu))

        debut = 0
        while debut < len(contenu):
            fin = debut + 1
            while (
                fin < len(contenu)
                and changes[fin] == changes[debut]
                and teintes[fin] == teintes[debut]
            ):
                fin += 1

            morceau = QTextCharFormat(fmt)
            if changes[debut]:
                morceau.setFontWeight(QFont.Weight.Bold)
            if teintes[debut] is not None:
                morceau.setForeground(teintes[debut])
            cursor.insertText(contenu[debut:fin], morceau)
            debut = fin

        self._lines += 1


def _positions_changees(segments, longueur: int) -> list[bool]:
    """Pour chaque caractère : appartient-il à un mot changé ?

    `None` quand la ligne n'est pas appariée — une suppression sans
    contrepartie, par exemple : rien n'y est marqué.
    """
    marques = [False] * longueur
    if segments is None:
        return marques

    position = 0
    for segment in segments:
        fin = min(position + len(segment.text), longueur)
        if segment.changed:
            for index in range(position, fin):
                marques[index] = True
        position = fin
    return marques


def _teintes_par_position(jetons, couleurs, longueur: int) -> list:
    """Pour chaque caractère : la couleur de son jeton, ou `None`.

    `None` signifie « garder la couleur du diff » : c'est le cas du
    texte ordinaire et des fichiers sans lexer connu. Deviner un langage
    produirait une coloration fausse, pire que pas de coloration.
    """
    teintes = [None] * longueur
    if not jetons or not couleurs:
        return teintes

    position = 0
    for segment in jetons:
        fin = min(position + len(segment.text), longueur)
        couleur = couleurs.get(segment.kind.value)
        if couleur is not None:
            for index in range(position, fin):
                teintes[index] = couleur
        position = fin
    return teintes


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
