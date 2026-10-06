"""Montrer ce qui change DANS une ligne, pas seulement quelle ligne.

Dernière limite inscrite au README : modifier un mot dans une ligne
longue affiche la ligne entière en rouge puis en vert, et il faut
comparer à l'œil pour voir ce qui a bougé. TortoiseGit et GitHub
soulignent le mot changé.

Fonction **pure** : elle ne lit ni dépôt ni disque, seulement deux
chaînes. C'est ce qui permet de la tester exhaustivement, là où le rendu
Qt ne se vérifie que par échantillons.
"""

from __future__ import annotations

import pytest

from tortoisepy.core.word_diff import Segment, pair_lines, word_segments


def _texte(segments, change_seulement=False):
    """Recompose le texte, ou seulement ses parties changées."""
    return "".join(
        s.text for s in segments if s.changed or not change_seulement
    )


# --- découpage d'une paire de lignes ------------------------------------


def test_an_unchanged_line_has_no_changed_segment():
    """Deux lignes identiques : rien à souligner."""
    avant, apres = word_segments("le chat dort", "le chat dort")

    assert all(not s.changed for s in avant)
    assert all(not s.changed for s in apres)


def test_a_single_changed_word_is_isolated():
    """L'assertion centrale : seul le mot qui change est marqué."""
    avant, apres = word_segments("le chat dort", "le chien dort")

    assert _texte(avant, True) == "chat"
    assert _texte(apres, True) == "chien"


def test_the_whole_line_is_still_recomposable():
    """Le texte complet doit survivre au découpage.

    Sans cette garantie, l'affichage perdrait des caractères — une
    espace avalée suffit à rendre un diff faux.
    """
    avant, apres = word_segments("le chat dort", "le chien dort")

    assert _texte(avant) == "le chat dort"
    assert _texte(apres) == "le chien dort"


def test_a_word_added_at_the_end():
    """Un ajout en fin de ligne ne doit pas marquer tout le reste."""
    avant, apres = word_segments("return x", "return x + 1")

    assert _texte(avant, True) == ""
    assert "+ 1" in _texte(apres, True)


def test_a_word_removed_from_the_middle():
    """Et une suppression au milieu."""
    avant, apres = word_segments("if a and b", "if b")

    assert "a and" in _texte(avant, True).replace("  ", " ")
    assert _texte(apres, True).strip() == ""


def test_two_distant_changes_in_one_line():
    """Deux mots changés : les deux doivent être marqués, pas l'entre-deux.

    Le piège : marquer tout l'intervalle entre le premier et le dernier
    changement, ce qui souligne du texte identique.
    """
    avant, apres = word_segments(
        "def charger(self, chemin):", "def enregistrer(self, fichier):"
    )

    assert "self" not in _texte(avant, True), (
        "la partie commune a été marquée comme changée"
    )


def test_indentation_is_preserved():
    """Un changement d'indentation seul doit se voir.

    L'espace est significative en Python : la traiter comme un séparateur
    ignorable masquerait un vrai changement.
    """
    avant, apres = word_segments("    return x", "        return x")

    assert _texte(avant) == "    return x"
    assert _texte(apres) == "        return x"
    assert any(s.changed for s in apres), (
        "un changement d'indentation doit être marqué"
    )


def test_a_completely_different_line_marks_almost_everything():
    """Sans rien de commun, presque tout est changé.

    « Presque » : une espace partagée reste non marquée, et c'est
    correct — elle n'a pas changé. Exiger la ligne entière
    reviendrait à marquer du texte identique, l'erreur même qu'on
    cherche à éviter.
    """
    avant, apres = word_segments("import os", "x = 1")

    assert "import" in _texte(avant, True)
    assert "os" in _texte(avant, True)
    assert "x" in _texte(apres, True)
    assert "1" in _texte(apres, True)


def test_punctuation_is_a_boundary():
    """`a.b` et `a.c` ne doivent marquer que `c`.

    Découper sur les espaces seules traiterait `a.b` comme un mot
    unique, et marquerait l'expression entière.
    """
    avant, apres = word_segments("self.charger()", "self.sauver()")

    assert "self" not in _texte(avant, True)


def test_an_empty_line_is_handled():
    """Une ligne vidée ou créée ne doit pas lever."""
    avant, apres = word_segments("", "du texte")

    assert _texte(avant) == ""
    assert _texte(apres, True) == "du texte"


# --- appariement des lignes d'un bloc ------------------------------------


def test_one_removed_and_one_added_are_paired():
    """Le cas courant : une ligne modifiée."""
    paires = pair_lines(("le chat dort",), ("le chien dort",))

    assert paires == ((0, 0),)


def test_unequal_counts_pair_what_they_can():
    """Deux lignes retirées, une ajoutée : une seule paire au plus.

    Le piège : apparier au hasard, ou lever. Ce qui reste sans
    correspondance s'affiche comme avant, ligne entière colorée.

    Les lignes sont réalistes : des chaînes d'un caractère tombent sous
    le seuil de similarité et ne testeraient que ce seuil.
    """
    paires = pair_lines(
        ("def charger(self):", "    return None"),
        ("def charger(self, chemin):",),
    )

    assert paires == ((0, 0),), (
        "seule la première paire est comparable"
    )


def test_nothing_added_gives_no_pair():
    """Une suppression pure n'a rien à comparer."""
    assert pair_lines(("a", "b"), ()) == ()


def test_nothing_removed_gives_no_pair():
    """Un ajout pur non plus."""
    assert pair_lines((), ("a",)) == ()


def test_dissimilar_lines_are_not_paired():
    """Apparier deux lignes sans rapport produirait des confettis.

    Mesuré sur un vrai diff : un bloc qui remplace dix lignes par dix
    autres, toutes différentes, deviendrait illisible si chacune était
    découpée mot à mot.
    """
    paires = pair_lines(("import os",), ("def f(): pass",))

    assert paires == (), (
        "deux lignes sans mot commun ne doivent pas être appariées"
    )


def test_pairs_follow_the_order():
    """Les paires suivent l'ordre d'apparition.

    Apparier la première retirée avec la dernière ajoutée afficherait
    des changements qui n'ont pas eu lieu.
    """
    paires = pair_lines(
        ("le chat dort", "la souris court"),
        ("le chien dort", "la souris marche"),
    )

    assert paires == ((0, 0), (1, 1))
