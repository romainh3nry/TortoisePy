# Affichage du code — coloration syntaxique et diff au mot

**Date :** 2026-10-23 (rétrospective — construit entre le 7 et le 12
octobre)
**Modules :** `core/syntax.py`, `core/word_diff.py`,
`ui/highlighter.py`, `ui/code_delegate.py`
**Valeurs de rendu :** voir le contrat visuel du même jour

> **Spec rétrospective.** Cette fonctionnalité a été construite en
> conversation directe, sans document préalable. Ce texte l'écrit
> après coup, pour qu'une reconstruction depuis les specs produise la
> même application.

---

## Le problème

Deux manques, signalés à quelques jours d'écart.

**Le premier**, capture à l'appui : un diff PHP s'affichait en vert uni,
sans distinction entre mots-clés, chaînes et commentaires. Lire du code
non coloré après des années d'IDE demande un effort inutile.

**Le second**, inscrit au README comme limite connue : modifier un mot
dans une ligne longue affichait la ligne entière en rouge puis en vert,
et il fallait comparer à l'œil pour voir ce qui avait bougé.

## Le risque, et la règle qui en découle

Le rendu du diff est validé et ne doit pas être dégradé. Une coloration
mal dosée le rendrait **moins** lisible : trop de couleurs tuent la
distinction ajout / suppression, qui est l'information principale.

**D'où le partage retenu**, celui de GitHub et de VSCode :

> Le **fond** reste au diff — vert ou rouge.
> Le **texte** passe à la syntaxe.

Colorer le fond par la syntaxe rendrait le diff illisible. C'est la
règle qui gouverne tout le reste.

## Architecture

### `core/syntax.py` — le découpage, sans Qt

Six genres de jetons seulement : `KEYWORD`, `STRING`, `COMMENT`,
`NUMBER`, `NAME`, `PLAIN`. Pygments en distingue des dizaines ; les
réduire à six garde une grammaire de couleurs qu'on peut mémoriser, et
des contrastes mesurés une seule fois.

`language_for(path)` déduit le langage de l'extension. **Une extension
inconnue rend `None`**, et le texte n'est pas coloré : deviner
produirait une coloration fausse, pire que pas de coloration.

Deux pièges vérifiés, et tous deux ont un test :

- **PHP exige `startinline=True`.** Sans lui, Pygments attend `<?php`
  et ne colore rien d'un extrait.
- **`String.Doc` doit être rangé avec les commentaires**, et le test
  doit venir AVANT celui de `String` : une docstring est un commentaire
  pour le lecteur, et l'ordre inverse la coloriait en chaîne.

### `core/word_diff.py` — deux fonctions pures

`word_segments(avant, après)` rend les fragments communs et changés.
`pair_lines(supprimées, ajoutées)` apparie les lignes d'un hunk.

`SIMILARITE_MINIMALE = 0.3` : en deçà, deux lignes sont considérées
comme sans rapport et affichées entières plutôt que mot à mot. Souligner
des fragments au hasard entre deux lignes étrangères serait du bruit.

Le motif de découpage est `\w+|\s+|.` — un mot, une suite d'espaces, ou
un caractère isolé. Les espaces sont des segments à part entière, sinon
le texte reconstitué perdrait son indentation.

### Trois façons de peindre, pour trois contenants

C'est le point qu'une reconstruction manquerait : **la même coloration
exige trois mises en œuvre**, parce que Qt offre trois contenants
différents.

| Contenant | Mécanisme | Pourquoi pas les autres |
|---|---|---|
| `DiffView` (lecture seule) | formats posés à l'affichage | le contenu est figé, posé une fois |
| Éditeur de fusion (colonne modifiable) | `QSyntaxHighlighter` | un format posé une fois ne survivrait pas à la frappe |
| Blâme (`QTreeWidget`) | `CodeDelegate` | un `QTreeWidgetItem` ne porte **qu'une** couleur par cellule |

### Le piège des tabulations

`drawText` donne 80 px à une tabulation — plus de huit espaces dans la
police du code. Un fichier PHP indenté par tabulations sortait de
l'écran.

Deux corrections, selon le contenant :
- champs de texte : `setTabStopDistance`
- délégué : `expandtabs(TAB_EN_ESPACES)` **avant** de peindre, car
  `setTabStopDistance` ne s'y applique pas

## Ce que la reconstruction doit préserver

- Le gras du diff au mot **se superpose** à la coloration : la couleur
  dit « quel genre de jeton », le gras dit « ce mot a changé ». Perdre
  l'un pour l'autre défait la moitié du travail.
- Les caractères `+` et `-` en tête de ligne gardent la couleur du
  diff, jamais celle de la syntaxe : ils n'appartiennent pas au code.
- L'en-tête `@@ … @@` n'est pas du code non plus.
- Un fichier binaire et un diff vide gardent leur message.

## Tests qui tiennent le contrat

`tests/ui/test_syntax_in_diff.py` et
`tests/ui/test_syntax_everywhere.py`.

Le second compare des **pixels réellement peints**, pas des intentions :
un délégué qui ne peindrait rien laisserait passer un test d'intention
tout en laissant l'écran gris.
