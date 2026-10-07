"""Coloration syntaxique du code affiché dans les diffs.

Demandé par l'utilisateur, capture à l'appui : un diff PHP s'affichait
en vert uni, sans distinction entre mots-clés, chaînes et commentaires.

Le module est **pur** — il rend des segments, pas des widgets — donc il
se teste sans Qt, exhaustivement, là où un rendu ne se vérifie que par
échantillons.

Le point délicat n'est pas la coloration elle-même, que Pygments fait
très bien, mais sa **superposition au diff** : la ligne porte déjà un
fond vert ou rouge, et l'information principale reste « ajouté » ou
« supprimé ». Une palette trop vive la noierait.
"""

from __future__ import annotations

import pytest

from tortoisepy.core.syntax import TokenKind, highlight, language_for


# --- reconnaissance du langage ------------------------------------------


@pytest.mark.parametrize(
    "chemin, attendu",
    [
        ("public/classes/RateLimiter.php", "php"),
        ("conf-dist/feature-switch.yaml", "yaml"),
        ("src/tortoisepy/ui/diff_view.py", "python"),
        ("scripts/install.sh", "bash"),
        ("README.md", "markdown"),
    ],
)
def test_the_language_is_deduced_from_the_extension(chemin, attendu):
    """Pygments connaît l'extension : rien à deviner nous-mêmes."""
    assert language_for(chemin) == attendu


def test_an_unknown_extension_has_no_language():
    """Un fichier sans lexer doit s'afficher tel quel, pas échouer."""
    assert language_for("donnees.inconnu") is None


def test_a_file_without_extension_has_no_language():
    """`Makefile` et consorts : mieux vaut rien que se tromper."""
    assert language_for("fichier-sans-extension") is None


# --- découpage en segments ----------------------------------------------


def test_a_keyword_is_recognised():
    """L'assertion centrale : le mot-clé se distingue du reste."""
    segments = highlight("class RateLimiter {", "php")

    genres = {s.kind for s in segments if s.text.strip() == "class"}
    assert TokenKind.KEYWORD in genres


def test_a_string_is_recognised():
    """Les chaînes sont ce qu'on repère le plus souvent du regard."""
    segments = highlight("$prefix = 'rate-limit';", "php")

    chaines = [s.text for s in segments if s.kind is TokenKind.STRING]
    assert any("rate-limit" in texte for texte in chaines)


def test_a_comment_is_recognised():
    """Un commentaire doit s'effacer, pas crier."""
    segments = highlight("# compteur par minute", "python")

    assert any(s.kind is TokenKind.COMMENT for s in segments)


def test_a_number_is_recognised():
    segments = highlight("max_connections = 40000", "python")

    assert any(s.kind is TokenKind.NUMBER for s in segments)


def test_plain_text_stays_plain():
    """Le texte ordinaire ne doit pas être teinté au hasard."""
    segments = highlight("resultat", "python")

    assert all(s.kind is TokenKind.PLAIN for s in segments)


# --- ce qui ne doit jamais se perdre ------------------------------------


def test_the_text_is_recomposable():
    """Recomposer les segments doit redonner la ligne EXACTE.

    Une espace avalée suffit à décaler un diff et à le rendre faux.
    C'est la garantie la plus importante du module.
    """
    ligne = "    if ($conf === null || !self::toBool($conf->get('x'))) {"
    segments = highlight(ligne, "php")

    assert "".join(s.text for s in segments) == ligne


def test_indentation_survives():
    """L'indentation porte du sens en Python, et se lit dans un diff."""
    ligne = "        return $allow;"
    segments = highlight(ligne, "php")

    assert "".join(s.text for s in segments).startswith("        ")


def test_an_empty_line_gives_nothing():
    """Une ligne vide ne doit pas produire de segment fantôme."""
    assert highlight("", "python") == ()


def test_an_unknown_language_returns_one_plain_segment():
    """Sans lexer, la ligne reste entière et neutre.

    Le piège : rendre un tuple vide, ce qui ferait disparaître le texte
    à l'affichage.
    """
    ligne = "contenu quelconque"
    segments = highlight(ligne, None)

    assert len(segments) == 1
    assert segments[0].text == ligne
    assert segments[0].kind is TokenKind.PLAIN


def test_a_broken_lexer_does_not_raise(monkeypatch):
    """Pygments ne doit jamais empêcher d'afficher un diff.

    La coloration est un confort : lever ici masquerait le contenu que
    l'utilisateur est venu lire.
    """
    from tortoisepy.core import syntax

    def casse(*a, **k):
        raise RuntimeError("lexer en panne")

    monkeypatch.setattr(syntax, "_lexer_pour", casse)

    segments = highlight("x = 1", "python")
    assert "".join(s.text for s in segments) == "x = 1"


# --- le nombre de genres reste petit ------------------------------------


def test_the_kinds_stay_few():
    """Peu de genres, donc peu de couleurs.

    Dans un diff, l'information principale reste « ajouté » ou
    « supprimé » : une palette trop riche la noierait. On regroupe donc
    les dizaines de jetons de Pygments en une poignée de genres.
    """
    assert len(TokenKind) <= 7


def test_every_kind_is_reachable():
    """Un genre qu'aucun code ne produit serait du code mort."""
    echantillons = {
        TokenKind.KEYWORD: ("class X:", "python"),
        TokenKind.STRING: ("x = 'texte'", "python"),
        TokenKind.COMMENT: ("# note", "python"),
        TokenKind.NUMBER: ("x = 42", "python"),
        TokenKind.NAME: ("def charger():", "python"),
        TokenKind.PLAIN: ("   ", "python"),
    }

    for genre, (code, langue) in echantillons.items():
        produits = {s.kind for s in highlight(code, langue)}
        assert genre in produits, f"« {genre} » n'est jamais produit"


def test_a_docblock_reads_as_a_comment():
    """`/** … */` et `\"\"\"…\"\"\"` sont des commentaires à l'écran.

    Pygments les classe en `String.Doc` — techniquement juste, puisque
    ce sont des chaînes de documentation. Mais dans un diff, ce qu'on
    lit est un commentaire : les teinter comme une chaîne les met au
    même niveau que `'/dev/shm'`, alors qu'ils doivent s'effacer.

    Vérifié sur le fichier de l'utilisateur, où tout le docblock
    ressortait en couleur de chaîne.
    """
    php = highlight("/** Checks and records a hit. */", "php")
    assert any(s.kind is TokenKind.COMMENT for s in php), (
        "le docblock PHP est traité comme une chaîne"
    )

    python = highlight('"""Documentation."""', "python")
    assert any(s.kind is TokenKind.COMMENT for s in python)


def test_a_real_string_is_still_a_string():
    """La correction ne doit pas emporter les chaînes ordinaires."""
    segments = highlight("$x = '/dev/shm';", "php")

    assert any(s.kind is TokenKind.STRING for s in segments)
