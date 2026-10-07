"""La coloration syntaxique dans la vue de diff.

Demandé par l'utilisateur, capture à l'appui : un diff PHP s'affichait en
vert uni, sans distinction entre mots-clés, chaînes et commentaires.

Le risque n'est pas technique mais visuel : le rendu du diff est validé,
et l'utilisateur a insisté pour ne pas le dégrader. Une coloration mal
dosée le rendrait MOINS lisible — trop de couleurs tuent la distinction
ajout / suppression, qui est l'information principale.

D'où le partage retenu, celui de GitHub et VSCode : **le fond reste au
diff**, vert ou rouge ; **le texte passe à la syntaxe**.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor

from tortoisepy.core.changes import DiffHunk, DiffLine, FileDiff
from tortoisepy.ui import theme
from tortoisepy.ui.diff_view import DiffView


def _ligne(origin: str, contenu: str) -> DiffLine:
    return DiffLine(origin=origin, content=contenu, raw=contenu + "\n")


def _diff(chemin: str, *lignes: DiffLine) -> FileDiff:
    return FileDiff(
        path=chemin,
        hunks=(DiffHunk(header="@@ -1,2 +1,2 @@", lines=lignes),),
    )


@pytest.fixture
def vue(qtbot):
    v = DiffView()
    qtbot.addWidget(v)
    return v


def _couleurs_du_texte(vue) -> dict[str, str]:
    """La couleur de chaque caractère non blanc, par fragment."""
    document = vue.document()
    resultat: dict[str, str] = {}
    courant, teinte = "", None
    for position in range(document.characterCount() - 1):
        curseur = QTextCursor(document)
        curseur.setPosition(position)
        curseur.movePosition(
            QTextCursor.MoveOperation.NextCharacter,
            QTextCursor.MoveMode.KeepAnchor,
        )
        couleur = curseur.charFormat().foreground().color().name()
        caractere = curseur.selectedText()
        if couleur == teinte:
            courant += caractere
        else:
            if courant.strip():
                resultat[courant.strip()] = teinte
            courant, teinte = caractere, couleur
    if courant.strip():
        resultat[courant.strip()] = teinte
    return resultat


def _fonds_par_ligne(vue) -> list[str | None]:
    document = vue.document()
    fonds = []
    bloc = document.firstBlock()
    while bloc.isValid():
        lecture = QTextCursor(bloc)
        lecture.select(QTextCursor.SelectionType.LineUnderCursor)
        arriere = lecture.charFormat().background()
        fonds.append(
            arriere.color().name()
            if arriere.style() != Qt.BrushStyle.NoBrush
            else None
        )
        bloc = bloc.next()
    return fonds


# --- le cas signalé ------------------------------------------------------


def test_a_keyword_is_coloured(vue):
    """L'assertion centrale : le mot-clé se distingue du reste."""
    vue.show_diff(_diff(
        "RateLimiter.php",
        _ligne("+", "class RateLimiter {"),
    ))

    couleurs = _couleurs_du_texte(vue)
    attendue = theme.syntax_colors()["keyword"].name()
    assert any(
        teinte == attendue for fragment, teinte in couleurs.items()
        if "class" in fragment
    ), f"« class » n'est pas coloré : {couleurs}"


def test_a_string_is_coloured(vue):
    """Les chaînes sont ce qu'on repère le plus du regard."""
    vue.show_diff(_diff(
        "RateLimiter.php",
        _ligne("+", "const PREFIX = 'rate-limit';"),
    ))

    teintes = set(_couleurs_du_texte(vue).values())
    assert theme.syntax_colors()["string"].name() in teintes


def test_a_comment_is_coloured(vue):
    """Un commentaire doit s'effacer, pas crier."""
    vue.show_diff(_diff(
        "module.py",
        _ligne("+", "# compteur par minute"),
    ))

    teintes = set(_couleurs_du_texte(vue).values())
    assert theme.syntax_colors()["comment"].name() in teintes


# --- le diff reste prioritaire ------------------------------------------


def test_the_diff_backgrounds_are_untouched(vue):
    """Le fond porte toujours « ajouté » ou « supprimé ».

    C'est l'information principale : la coloration s'y ajoute, elle ne
    la remplace pas. Le rendu du diff est validé et ne doit pas être
    dégradé.
    """
    vue.show_diff(_diff(
        "module.py",
        _ligne("-", "x = 1"),
        _ligne("+", "x = 2"),
    ))

    couleurs = theme.diff_colors()
    fonds = set(_fonds_par_ligne(vue))
    assert couleurs["added_bg"].name() in fonds
    assert couleurs["removed_bg"].name() in fonds


def test_the_origin_character_keeps_the_diff_colour(vue):
    """`+` et `-` restent au diff, pas à la syntaxe.

    Ils n'appartiennent pas au code : les colorer en mot-clé ou en
    chaîne selon le hasard du lexer brouillerait leur sens.
    """
    vue.show_diff(_diff(
        "module.py",
        _ligne("+", "class X:"),
    ))

    document = vue.document()
    curseur = QTextCursor(document)
    curseur.movePosition(QTextCursor.MoveOperation.Start)
    # Premier bloc = en-tête du hunk ; le second porte la ligne.
    curseur.movePosition(QTextCursor.MoveOperation.NextBlock)
    curseur.movePosition(
        QTextCursor.MoveOperation.NextCharacter,
        QTextCursor.MoveMode.KeepAnchor,
    )

    assert curseur.selectedText() == "+"
    assert (
        curseur.charFormat().foreground().color().name()
        == theme.diff_colors()["added_fg"].name()
    )


def test_an_unknown_extension_is_not_coloured(vue):
    """Sans lexer, le texte garde la couleur du diff.

    Deviner un langage produirait une coloration fausse, pire que pas
    de coloration du tout.
    """
    vue.show_diff(_diff(
        "donnees.inconnu",
        _ligne("+", "class RateLimiter {"),
    ))

    teintes = set(_couleurs_du_texte(vue).values())
    syntaxe = {c.name() for c in theme.syntax_colors().values()}
    assert not (teintes & syntaxe)


def test_the_text_is_complete(vue):
    """Rien ne doit se perdre au découpage.

    Une espace avalée suffit à décaler un diff et à le rendre faux.
    """
    ligne = "    if ($conf === null || !self::toBool($x)) {"
    vue.show_diff(_diff("RateLimiter.php", _ligne("+", ligne)))

    assert ligne in vue.text()


def test_the_hunk_header_is_not_coloured(vue):
    """L'en-tête « @@ … @@ » n'est pas du code."""
    vue.show_diff(_diff("module.py", _ligne("+", "x = 1")))

    document = vue.document()
    entete = document.firstBlock()
    lecture = QTextCursor(entete)
    lecture.select(QTextCursor.SelectionType.LineUnderCursor)

    assert (
        lecture.charFormat().foreground().color().name()
        == theme.diff_colors()["header_fg"].name()
    )


# --- robustesse ----------------------------------------------------------


def test_a_binary_file_still_says_so(vue):
    vue.show_diff(FileDiff(path="b.dat", is_binary=True))

    assert "binaire" in vue.text()


def test_an_empty_diff_still_says_so(vue):
    vue.show_diff(FileDiff(path="f.py"))

    assert "aucune modification" in vue.text()


def test_the_word_level_marking_still_works(vue):
    """La coloration ne doit pas effacer le gras du diff au mot.

    Les deux se superposent : la couleur dit « quel genre de jeton », le
    gras dit « ce mot a changé ». Perdre l'un pour l'autre reviendrait à
    défaire le travail précédent.
    """
    from PySide6.QtGui import QFont

    vue.show_diff(_diff(
        "module.py",
        _ligne("-", "resultat = charger(chemin)"),
        _ligne("+", "resultat = sauver(chemin)"),
    ))

    document = vue.document()
    gras = False
    for position in range(document.characterCount() - 1):
        curseur = QTextCursor(document)
        curseur.setPosition(position)
        curseur.movePosition(
            QTextCursor.MoveOperation.NextCharacter,
            QTextCursor.MoveMode.KeepAnchor,
        )
        if curseur.charFormat().fontWeight() >= QFont.Weight.Bold:
            gras = True
            break

    assert gras, "le marquage mot à mot a disparu"


# --- largeur des tabulations --------------------------------------------


def test_a_tab_is_four_spaces_wide(vue):
    """Signalé par l'utilisateur : « des soucis d'indentation ».

    Qt place ses taquets à 80 px, soit 8,9 espaces dans la police du
    diff : trois tabulations repoussaient le code de 27 espaces, et le
    fichier PHP de l'utilisateur partait hors de l'écran.

    Le défaut précède la coloration — elle l'a seulement rendu visible.
    Quatre espaces est la convention de PHP comme de Python.
    """
    from PySide6.QtGui import QFontMetricsF

    metriques = QFontMetricsF(vue.font())
    attendu = 4 * metriques.horizontalAdvance(" ")

    assert abs(vue.tabStopDistance() - attendu) < 1.0, (
        f"{vue.tabStopDistance():.0f} px au lieu de {attendu:.0f}"
    )


def test_tab_indented_code_stays_readable(vue):
    """Trois tabulations ne doivent pas valoir une demi-ligne.

    Mesuré avant correction : 240 px, soit 27 espaces.
    """
    from PySide6.QtGui import QFontMetricsF

    metriques = QFontMetricsF(vue.font())
    trois = 3 * vue.tabStopDistance()

    assert trois <= 13 * metriques.horizontalAdvance(" "), (
        f"trois tabulations occupent {trois:.0f} px"
    )
