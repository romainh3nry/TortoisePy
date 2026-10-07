"""Montrer ce qui change DANS une ligne, pas seulement quelle ligne.

Dernière limite inscrite au README : modifier un mot dans une ligne
longue affichait la ligne entière en rouge puis en vert, et il fallait
comparer à l'œil pour voir ce qui avait bougé. TortoiseGit et GitHub
soulignent le mot changé.

Deux fonctions **pures**, sans dépôt ni disque — ce qui permet de les
tester exhaustivement, là où un rendu Qt ne se vérifie que par
échantillons.

Aucune dépendance à Qt : `ui/` appelle ces fonctions, jamais pygit2
directement.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

#: Un « mot » : une suite de caractères de mot, OU un caractère isolé.
#:
#: Découper sur les espaces seules traiterait « self.charger() » comme un
#: mot unique, et le moindre changement marquerait l'expression entière.
#: La ponctuation sépare donc, mais reste dans le découpage : le texte
#: doit pouvoir être recomposé à l'identique, une espace avalée suffisant
#: à rendre un diff faux.
_MOT = re.compile(r"\w+|\s+|.")

SIMILARITE_MINIMALE = 0.3
"""En deçà, deux lignes ne sont pas considérées comme une modification.

Mesuré sur de vrais diffs : apparier des lignes sans rapport produit un
marquage en confettis, moins lisible que la ligne entière colorée. Mieux
vaut alors ne rien souligner.
"""


@dataclass(frozen=True)
class Segment:
    """Un morceau de ligne, changé ou non."""

    text: str
    changed: bool


def word_segments(
    avant: str, apres: str
) -> tuple[tuple[Segment, ...], tuple[Segment, ...]]:
    """Découpe deux lignes en segments, en marquant ce qui diffère.

    Rend `(segments_avant, segments_apres)`. Recomposer le `text` de
    chaque suite redonne exactement la ligne d'origine : l'affichage ne
    doit perdre aucun caractère.
    """
    mots_avant = _MOT.findall(avant)
    mots_apres = _MOT.findall(apres)

    comparateur = SequenceMatcher(None, mots_avant, mots_apres, autojunk=False)

    gauche: list[Segment] = []
    droite: list[Segment] = []

    for operation, a1, a2, b1, b2 in comparateur.get_opcodes():
        identique = operation == "equal"
        if a1 != a2:
            gauche.append(
                Segment("".join(mots_avant[a1:a2]), not identique)
            )
        if b1 != b2:
            droite.append(
                Segment("".join(mots_apres[b1:b2]), not identique)
            )

    return tuple(gauche), tuple(droite)


def pair_lines(
    retirees: tuple[str, ...], ajoutees: tuple[str, ...]
) -> tuple[tuple[int, int], ...]:
    """Apparie les lignes retirées et ajoutées d'un même bloc.

    Rend les couples d'indices `(retirée, ajoutée)` à comparer mot à
    mot. Les lignes sans correspondance s'affichent comme avant, en
    entier.

    L'appariement suit l'**ordre d'apparition** : associer la première
    retirée à la dernière ajoutée afficherait des changements qui n'ont
    pas eu lieu. Et deux lignes trop dissemblables ne sont pas
    appariées — cf. `SIMILARITE_MINIMALE`.
    """
    paires: list[tuple[int, int]] = []

    for index, (ligne_avant, ligne_apres) in enumerate(
        zip(retirees, ajoutees)
    ):
        if _similarite(ligne_avant, ligne_apres) >= SIMILARITE_MINIMALE:
            paires.append((index, index))

    return tuple(paires)


def _similarite(avant: str, apres: str) -> float:
    """Proportion de contenu commun entre deux lignes, de 0 à 1.

    Deux lignes vides sont identiques (1.0) : `SequenceMatcher` le dit
    déjà, et traiter ce cas à part n'apporterait rien.
    """
    return SequenceMatcher(None, avant, apres, autojunk=False).ratio()
