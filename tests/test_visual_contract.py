"""Le contrat visuel doit rester exact.

Demandé par l'utilisateur : « je voudrais que les specs permettent de
refaire exactement la même application, y compris le visuel ».

Un document de valeurs qui dérive du code est pire qu'absent : il
donnerait confiance en se trompant. Ces tests le vérifient à chaque
exécution de la suite.

Ils ne jugent pas si une valeur est BONNE — c'est l'œil de
l'utilisateur qui l'a décidé. Ils vérifient que le document dit ce
que le code fait.
"""

from __future__ import annotations

from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
CONTRAT = (
    RACINE / "docs" / "superpowers" / "specs"
    / "2026-10-23-tortoisepy-visual-contract.md"
)


@pytest.fixture(scope="module")
def document() -> str:
    assert CONTRAT.is_file(), f"contrat visuel absent : {CONTRAT}"
    return CONTRAT.read_text()


def test_the_contract_exists(document):
    assert document.strip()


def test_every_theme_constant_is_documented(document, qtbot):
    """Une constante ajoutée sans être écrite rend le contrat faux.

    C'est le défaut qui se produirait sans ce test : quelqu'un règle
    un espacement, le document continue d'annoncer l'ancien, et une
    reconstruction suit le document.
    """
    from tortoisepy.ui import theme

    # Les agrégats et les couleurs sont vérifiés par leurs VALEURS
    # plus bas, pas par leur nom : le tableau des diffs se lit mieux
    # avec « #e4f5e4 » qu'avec « DIFF_ADDED ».
    par_valeur = {"PALETTE", "SYNTAX_CLAIR", "SYNTAX_SOMBRE"}
    oubliees = [
        nom for nom in dir(theme)
        if nom.isupper() and nom not in par_valeur
        and not nom.startswith("_")
        and not nom.startswith("DIFF_")
        and not nom.startswith("WORKING_")
        and nom != "UNPUSHED_MARKER"
        and f"`{nom}`" not in document
    ]

    assert not oubliees, (
        f"constantes absentes du contrat visuel : {oubliees}"
    )


def test_the_documented_values_match_the_code(document, qtbot):
    """Le cœur du contrat : les nombres doivent correspondre.

    Vérifié à l'écriture — 39 valeurs exactes — mais c'est ici que la
    propriété se maintient.
    """
    from tortoisepy.layout import engine
    from tortoisepy.ui import graph_items, theme

    valeurs = {
        "NODE_FONT_SIZE": theme.NODE_FONT_SIZE,
        "NODE_RADIUS": theme.NODE_RADIUS,
        "NODE_BORDER_WIDTH": theme.NODE_BORDER_WIDTH,
        "PADDING_X": theme.PADDING_X,
        "PADDING_Y": theme.PADDING_Y,
        "EDGE_WIDTH": theme.EDGE_WIDTH,
        "ARROW_SIZE": theme.ARROW_SIZE,
        "TAB_EN_ESPACES": theme.TAB_EN_ESPACES,
        "UNPUSHED_MARKER_RADIUS": theme.UNPUSHED_MARKER_RADIUS,
        "GAP_X": engine.GAP_X,
        "GAP_Y": engine.GAP_Y,
        "COMPONENT_GAP": engine.COMPONENT_GAP,
        "SCENE_MARGIN": graph_items.SCENE_MARGIN,
        "TANGENT_SAMPLE": graph_items.TANGENT_SAMPLE,
        "STRAIGHT_THRESHOLD": graph_items.STRAIGHT_THRESHOLD,
        "LABEL_POSITION": graph_items.LABEL_POSITION,
        "LABEL_STEP": graph_items.LABEL_STEP,
        "LABEL_MAX_SHIFT": graph_items.LABEL_MAX_SHIFT,
        "LABEL_OFFSET": graph_items.LABEL_OFFSET,
    }

    faux = [
        f"{nom} vaut {valeur} dans le code"
        for nom, valeur in valeurs.items()
        if f"`{valeur}`" not in document
    ]

    assert not faux, (
        "le contrat visuel annonce autre chose que le code : "
        + "; ".join(faux)
    )


def test_the_palette_is_documented(document, qtbot):
    """Les couleurs du graphe, reconstituées de la capture d'origine.

    Les retrouver au jugé serait impossible : ce sont elles qui
    rendent le graphe lisible d'un coup d'œil.
    """
    from tortoisepy.ui import theme

    manquantes = []
    for champ in theme.PALETTE.__dataclass_fields__:
        r, v, b, _ = getattr(theme.PALETTE, champ).getRgb()
        if f"`{r}, {v}, {b}`" not in document:
            manquantes.append(f"{champ} = {r}, {v}, {b}")

    assert not manquantes, (
        f"couleurs de palette absentes du contrat : {manquantes}"
    )


def test_the_diff_colours_are_documented(document, qtbot):
    """Leurs contrastes ont été mesurés contre les deux fonds.

    Une reconstruction qui choisirait « un vert » et « un rouge » au
    jugé échouerait le seuil WCAG AA de 4,5:1.
    """
    from tortoisepy.ui import theme

    manquantes = [
        nom for nom in dir(theme)
        if nom.startswith("DIFF_")
        and getattr(theme, nom).name() not in document
    ]

    assert not manquantes, (
        f"couleurs de diff absentes du contrat : {manquantes}"
    )


def test_the_syntax_colours_are_documented(document, qtbot):
    """Deux jeux complets, clair et sombre."""
    from tortoisepy.ui import theme

    manquantes = []
    for jeu, nom in (
        (theme.SYNTAX_CLAIR, "clair"), (theme.SYNTAX_SOMBRE, "sombre")
    ):
        for jeton, couleur in jeu.items():
            r, v, b, _ = couleur.getRgb()
            if f"`{r}, {v}, {b}`" not in document:
                manquantes.append(f"{nom}/{jeton}")

    assert not manquantes, (
        f"couleurs de syntaxe absentes du contrat : {manquantes}"
    )


def test_the_unwritable_rules_are_stated(document):
    """Ce qui ne tient pas dans une constante doit être écrit.

    Sans ces règles, une reconstruction obtiendrait les bonnes
    couleurs dans une application qui se comporte autrement — le
    recentrage automatique refusé par l'utilisateur, par exemple,
    reviendrait aussitôt.
    """
    for regle in (
        "centrage sur HEAD",
        "compress",          # chaînes linéaires
        "40 %",              # proportion du panneau
    ):
        assert regle in document, (
            f"règle visuelle non chiffrable absente : « {regle} »"
        )


def test_the_remaining_colours_are_documented_by_value(document, qtbot):
    """Les couleurs exclues du contrôle par nom doivent l'être par
    valeur.

    `test_every_theme_constant_is_documented` écarte `WORKING_*` et
    `UNPUSHED_MARKER` parce que le document les présente par leur RGB
    plutôt que par leur nom. Sans ce test, cette exclusion deviendrait
    un trou : on pourrait les retirer du contrat sans que rien ne
    bronche.
    """
    from tortoisepy.ui import theme

    manquantes = []
    for nom in ("WORKING_FILL", "WORKING_BORDER", "WORKING_TEXT",
                "UNPUSHED_MARKER"):
        r, v, b, _ = getattr(theme, nom).getRgb()
        if f"`{r}, {v}, {b}`" not in document:
            manquantes.append(f"{nom} = {r}, {v}, {b}")

    assert not manquantes, manquantes
