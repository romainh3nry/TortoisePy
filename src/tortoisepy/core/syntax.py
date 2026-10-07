"""Coloration syntaxique du code affiché dans les diffs.

Demandé par l'utilisateur, capture à l'appui : un diff PHP s'affichait en
vert uni, sans distinction entre mots-clés, chaînes et commentaires.

Le module est **pur** : il rend des segments de texte, pas des widgets.
Il se teste donc sans Qt, exhaustivement, là où un rendu ne se vérifie
que par échantillons.

Le point délicat n'est pas la coloration — Pygments la fait très bien —
mais sa **superposition au diff**. La ligne porte déjà un fond vert ou
rouge, et l'information principale reste « ajouté » ou « supprimé » :
une palette trop riche la noierait. D'où le regroupement des dizaines de
jetons de Pygments en une poignée de genres.

Aucune dépendance à Qt : `ui/` applique les couleurs, ce module dit
seulement où elles vont.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from pygments import lex
from pygments.lexers import get_lexer_by_name, get_lexer_for_filename
from pygments.token import Token
from pygments.util import ClassNotFound


class TokenKind(Enum):
    """Les genres retenus. Volontairement peu nombreux.

    Pygments distingue des dizaines de jetons ; les afficher tous dans un
    diff ferait concurrence au vert et au rouge, qui portent le sens
    premier.
    """

    PLAIN = "plain"
    KEYWORD = "keyword"
    STRING = "string"
    COMMENT = "comment"
    NUMBER = "number"
    NAME = "name"
    """Noms de fonctions, de classes, de variables déclarées."""


@dataclass(frozen=True)
class Segment:
    """Un morceau de ligne et son genre."""

    text: str
    kind: TokenKind


def language_for(path: str) -> str | None:
    """Le langage déduit de l'extension, ou `None` s'il est inconnu.

    Pygments connaît les extensions : rien à deviner nous-mêmes. Un
    fichier sans lexer s'affiche tel quel plutôt que d'être coloré au
    hasard.
    """
    try:
        return get_lexer_for_filename(path).aliases[0]
    except (ClassNotFound, IndexError, AttributeError):
        return None


def highlight(line: str, language: str | None) -> tuple[Segment, ...]:
    """Découpe une ligne en segments colorables.

    Recomposer le `text` de chaque segment redonne la ligne **exacte** :
    une espace avalée suffirait à décaler un diff et à le rendre faux.

    Sans langage connu, rend un seul segment neutre — et non un tuple
    vide, qui ferait disparaître le texte à l'affichage.
    """
    if not line:
        return ()

    if language is None:
        return (Segment(line, TokenKind.PLAIN),)

    try:
        lexer = _lexer_pour(language)
        jetons = list(lex(line, lexer))
    except Exception:  # noqa: BLE001
        # La coloration est un confort : lever ici masquerait le contenu
        # que l'utilisateur est venu lire.
        return (Segment(line, TokenKind.PLAIN),)

    segments = [
        Segment(texte, _genre(jeton))
        for jeton, texte in jetons
        if texte
    ]

    # Pygments ajoute un saut de ligne final que la ligne n'avait pas.
    if segments and segments[-1].text == "\n":
        segments.pop()
    elif segments and segments[-1].text.endswith("\n"):
        dernier = segments[-1]
        segments[-1] = Segment(dernier.text[:-1], dernier.kind)

    return tuple(s for s in segments if s.text)


def _lexer_pour(language: str):
    """Le lexer de ce langage. Isolé pour que les tests puissent le casser.

    `startinline` pour PHP : son lexer attend `<?php` et traite tout le
    reste comme du HTML brut (vérifié — « class RateLimiter { » rendait
    un seul jeton `Other`). Or un diff montre un fragment, jamais le
    fichier depuis sa balise ouvrante.
    """
    options = {"stripnl": False, "ensurenl": False}
    if language == "php":
        options["startinline"] = True
    return get_lexer_by_name(language, **options)


def _genre(jeton) -> TokenKind:
    """Ramène un jeton Pygments à l'un de nos six genres.

    `in` plutôt qu'une égalité : les jetons de Pygments sont
    hiérarchiques (`Token.Literal.String.Single` appartient à
    `Token.Literal.String`), et comparer les feuilles demanderait d'en
    énumérer des dizaines.

    L'ordre compte : `Name.Function` doit être vu comme un nom avant que
    `Keyword` ne l'attrape, et un commentaire avant tout le reste.
    """
    if jeton in Token.Comment:
        return TokenKind.COMMENT
    # `String.Doc` AVANT `String` : Pygments classe `/** … */` et les
    # docstrings Python en chaînes de documentation — techniquement juste,
    # mais à l'écran ce sont des commentaires. Vérifié sur un diff PHP
    # réel, tout le docblock ressortait en couleur de chaîne, au même
    # niveau que `'/dev/shm'`, alors qu'il doit s'effacer.
    if jeton in Token.Literal.String.Doc:
        return TokenKind.COMMENT
    if jeton in Token.Literal.String:
        return TokenKind.STRING
    if jeton in Token.Literal.Number:
        return TokenKind.NUMBER
    if jeton in Token.Keyword:
        return TokenKind.KEYWORD
    if jeton in Token.Name.Function or jeton in Token.Name.Class:
        return TokenKind.NAME
    return TokenKind.PLAIN
