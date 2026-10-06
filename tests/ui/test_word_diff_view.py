"""Le mot changé ressort dans la ligne colorée.

Dernière limite du README : modifier un mot dans une ligne longue
affichait la ligne entière en rouge puis en vert, et il fallait comparer
à l'œil.

Le marquage passe par le **gras**, sur le fond déjà coloré, plutôt que
par une teinte nouvelle : une couleur de plus demanderait de mesurer son
contraste dans les deux thèmes, pour un gain que le gras donne
immédiatement.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QTextCursor

from tortoisepy.core.changes import DiffHunk, DiffLine, FileDiff
from tortoisepy.ui.diff_view import DiffView


def _ligne(origin: str, contenu: str) -> DiffLine:
    return DiffLine(origin=origin, content=contenu, raw=contenu + "\n")


def _diff(*lignes: DiffLine) -> FileDiff:
    return FileDiff(
        path="f.py",
        hunks=(DiffHunk(header="@@ -1,2 +1,2 @@", lines=lignes),),
    )


@pytest.fixture
def vue(qtbot):
    v = DiffView()
    qtbot.addWidget(v)
    return v


def _mots_gras(vue) -> list[str]:
    """Les caractères affichés en gras, regroupés en fragments.

    Lu caractère par caractère via le curseur : `block.layout().formats()`
    rend une liste vide tant que la vue n'a pas été peinte, ce qui
    n'arrive jamais en test sans écran (déjà constaté sur l'éditeur de
    fusion).
    """
    gras = []
    document = vue.document()
    courant = ""
    for position in range(document.characterCount() - 1):
        curseur = QTextCursor(document)
        curseur.setPosition(position)
        curseur.movePosition(
            QTextCursor.MoveOperation.NextCharacter,
            QTextCursor.MoveMode.KeepAnchor,
        )
        if curseur.charFormat().fontWeight() >= QFont.Weight.Bold:
            courant += curseur.selectedText()
        elif courant:
            gras.append(courant)
            courant = ""
    if courant:
        gras.append(courant)
    return [fragment for fragment in gras if fragment.strip()]


# --- le cas qui motive la fonctionnalité ---------------------------------


def test_only_the_changed_word_is_bold(vue):
    """L'assertion centrale : un mot change, un mot ressort."""
    vue.show_diff(_diff(
        _ligne("-", "    resultat = charger(chemin)"),
        _ligne("+", "    resultat = sauver(chemin)"),
    ))

    gras = " ".join(_mots_gras(vue))
    assert "charger" in gras
    assert "sauver" in gras
    assert "resultat" not in gras, (
        "la partie commune a été mise en évidence"
    )


def test_the_whole_text_is_still_displayed(vue):
    """Le marquage ne doit rien faire disparaître.

    Une espace avalée suffirait à rendre le diff faux.
    """
    vue.show_diff(_diff(
        _ligne("-", "le chat dort"),
        _ligne("+", "le chien dort"),
    ))

    texte = vue.text()
    assert "le chat dort" in texte
    assert "le chien dort" in texte


def test_context_lines_are_never_bold(vue):
    """Une ligne inchangée n'a rien à mettre en évidence."""
    vue.show_diff(_diff(
        _ligne(" ", "contexte avant"),
        _ligne("-", "le chat dort"),
        _ligne("+", "le chien dort"),
        _ligne(" ", "contexte apres"),
    ))

    gras = " ".join(_mots_gras(vue))
    assert "contexte" not in gras


def test_an_unpaired_removal_is_not_bold(vue):
    """Une suppression pure n'a pas de contrepartie à comparer.

    Tout marquer en gras reviendrait à ne rien marquer : le gras doit
    rester le signe d'un changement DANS la ligne.
    """
    vue.show_diff(_diff(
        _ligne("-", "ligne supprimee"),
        _ligne(" ", "contexte"),
    ))

    assert _mots_gras(vue) == []


def test_dissimilar_lines_are_not_marked(vue):
    """Deux lignes sans rapport : pas de marquage en confettis.

    Mesuré sur de vrais diffs — découper mot à mot des lignes
    étrangères l'une à l'autre rend le bloc moins lisible que la ligne
    entière colorée.
    """
    vue.show_diff(_diff(
        _ligne("-", "import os"),
        _ligne("+", "def charger(self, chemin, mode): return None"),
    ))

    assert _mots_gras(vue) == []


def test_several_changed_lines_are_each_marked(vue):
    """Un bloc peut contenir plusieurs lignes modifiées."""
    vue.show_diff(_diff(
        _ligne("-", "le chat dort"),
        _ligne("-", "la souris court"),
        _ligne("+", "le chien dort"),
        _ligne("+", "la souris marche"),
    ))

    gras = " ".join(_mots_gras(vue))
    assert "chien" in gras
    assert "marche" in gras


# --- ce qui ne doit pas changer -----------------------------------------


def test_the_colours_are_unchanged(vue):
    """Le fond et la couleur du texte restent ceux d'avant.

    Le rendu du diff est validé : le gras s'y ajoute, il ne le remplace
    pas.
    """
    from tortoisepy.ui import theme

    vue.show_diff(_diff(
        _ligne("-", "le chat dort"),
        _ligne("+", "le chien dort"),
    ))

    couleurs = theme.diff_colors()
    curseur = QTextCursor(vue.document())
    curseur.movePosition(QTextCursor.MoveOperation.Start)
    fonds = set()
    while True:
        bloc = curseur.block()
        lecture = QTextCursor(bloc)
        lecture.select(QTextCursor.SelectionType.LineUnderCursor)
        arriere = lecture.charFormat().background()
        if arriere.style() != Qt.BrushStyle.NoBrush:
            fonds.add(arriere.color().name())
        if not curseur.movePosition(QTextCursor.MoveOperation.NextBlock):
            break

    assert couleurs["added_bg"].name() in fonds
    assert couleurs["removed_bg"].name() in fonds


def test_a_binary_file_still_says_so(vue):
    """Comportement d'origine à préserver."""
    vue.show_diff(FileDiff(path="b.dat", is_binary=True))

    assert "binaire" in vue.text()


def test_an_empty_diff_still_says_so(vue):
    """Et le cas « aucune modification »."""
    vue.show_diff(FileDiff(path="f.py"))

    assert "aucune modification" in vue.text()


def test_the_origin_character_is_kept(vue):
    """`+` et `-` restent en tête de ligne.

    Trouvé par mutation : les supprimer passait inaperçu. Ils portent
    pourtant le sens — sans eux, on ne distingue plus un ajout d'une
    suppression dans le texte copié, et le diff perd sa grammaire.
    """
    vue.show_diff(_diff(
        _ligne("-", "le chat dort"),
        _ligne("+", "le chien dort"),
    ))

    lignes = vue.text().splitlines()
    assert any(l.startswith("-") for l in lignes), "le « - » a disparu"
    assert any(l.startswith("+") for l in lignes), "le « + » a disparu"
