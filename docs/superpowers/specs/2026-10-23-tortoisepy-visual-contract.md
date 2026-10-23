# Contrat visuel de tortoisePy

> **Pourquoi ce document.** Les dix-huit specs précédentes décrivent des
> comportements. Aucune ne contient une seule valeur de rendu : ni pixel,
> ni couleur, ni police — vérifié par recherche sur leurs 3 803 lignes.
>
> Or l'aspect de l'application a été validé à l'œil, par itérations, et
> la mémoire du projet porte une consigne explicite : *« ne jamais
> dégrader l'aspect actuel — courbes, flèches tangentes, espacement,
> centrage HEAD »*.
>
> Une reconstruction à partir des specs seules produirait donc un graphe
> différent, et sans doute moins bon : ces valeurs ne sont pas
> arbitraires, et personne ne les retrouverait au jugé.
>
> Ce document existe pour que cette reconstruction soit **identique**.
> Les valeurs ci-dessous ont été extraites du code en exécution, pas
> recopiées à la main.

**Date :** 2026-10-23
**Portée :** tout ce qui se voit — géométrie, couleurs, typographie
**Source de vérité :** `ui/theme.py`, `layout/engine.py`,
`ui/graph_items.py`

---

## 1. Typographie

| Constante | Valeur | Raison |
|---|---|---|
| `NODE_FONT_FAMILY` | `Menlo` | Chasse fixe, conforme à la capture TortoiseGit de référence. Qt retombe sur une équivalente si absente — donc l'aspect varie un peu hors macOS, et c'est accepté. |
| `NODE_FONT_SIZE` | `12` | |
| `TAB_EN_ESPACES` | `4` | Qt pose ses taquets à 80 px, soit 8,9 espaces dans la police du code : un fichier PHP indenté par tabulations sortait de l'écran. Quatre est la convention de PHP comme de Python. |

## 2. Géométrie des nœuds

| Constante | Valeur |
|---|---|
| `NODE_RADIUS` | `6.0` |
| `NODE_BORDER_WIDTH` | `1.0` |
| `PADDING_X` | `12.0` |
| `PADDING_Y` | `6.0` |
| `UNPUSHED_MARKER_RADIUS` | `4.0` |

## 3. Agencement du graphe

Ces trois valeurs gouvernent la densité, et toutes trois ont été
**relevées après usage** — l'aspect d'origine paraissait comprimé.

| Constante | Valeur | Raison |
|---|---|---|
| `GAP_X` | `60.0` | Relevé de 40 à 60 : le graphe paraissait comprimé à l'usage. |
| `GAP_Y` | `90.0` | Relevé de 60 à 90, même raison. C'est aussi ce qui laisse la place aux étiquettes « N commits » sans qu'elles chevauchent les nœuds. |
| `COMPONENT_GAP` | `120.0` | Écart entre deux historiques indépendants, plus large pour les distinguer. |
| `SCENE_MARGIN` | `40.0` | Marge autour de la scène. |

## 4. Liens et flèches

C'est la partie la plus difficile à retrouver sans ce document : elle
produit les « courbes » et les « flèches tangentes » que la consigne de
mémoire protège nommément.

| Constante | Valeur | Rôle |
|---|---|---|
| `EDGE_WIDTH` | `1.5` | |
| `ARROW_SIZE` | `9.0` | |
| `TANGENT_SAMPLE` | `0.06` | Fraction de la courbe échantillonnée pour orienter la pointe de flèche. Une flèche posée à angle fixe ne suivrait pas la courbe. |
| `STRAIGHT_THRESHOLD` | `12.0` | En deçà de cet écart horizontal, le lien est tracé droit : une courbe imperceptible coûterait du calcul et paraîtrait tremblée. |
| `LABEL_POSITION` | `0.5` | Étiquette « N commits » au milieu du lien. |
| `LABEL_STEP` | `9.0` | Décalage appliqué pour éviter deux étiquettes superposées. |
| `LABEL_MAX_SHIFT` | `54.0` | Au-delà, on renonce à décaler : l'étiquette s'éloignerait trop de son lien. |
| `LABEL_OFFSET` | `14.0` | Distance perpendiculaire au lien. |

## 5. Palette du graphe

Reconstituée de la capture TortoiseGit de référence (§4.3 de la spec
d'origine). Chaque type de référence a sa couleur, et c'est ce qui rend
le graphe lisible d'un coup d'œil.

| Rôle | RGB | Aspect |
|---|---|---|
| `current_branch` | `190, 50, 40` | rouge |
| `local_branch` | `120, 200, 120` | vert |
| `remote_branch` | `250, 222, 180` | beige / pêche |
| `tag` | `250, 240, 130` | jaune |
| `stash` | `150, 150, 150` | gris |
| `junction` | `245, 245, 245` | blanc cassé, discret |
| `selected` | `160, 30, 30` | rouge foncé |
| `selected_text` | `255, 255, 255` | |
| `text` | `20, 20, 20` | |
| `border` | `110, 110, 110` | |
| `edge` | `30, 30, 30` | |
| `background` | `255, 255, 255` | |

### Nœud « Uncommitted changes »

| Constante | RGB |
|---|---|
| `WORKING_FILL` | `248, 248, 248` |
| `WORKING_BORDER` | `140, 140, 140` |
| `WORKING_TEXT` | `90, 90, 90` |

Volontairement effacé, bordure pointillée : il signale, il ne réclame
pas l'attention.

### Marqueur de commits non poussés

`UNPUSHED_MARKER` = `230, 140, 30` — orange, rayon 4 px.

## 6. Couleurs du diff

Deux jeux, clair et sombre. **Les contrastes ont été mesurés** contre
les deux fonds, dans les deux thèmes, pour tenir le seuil WCAG AA de
4,5:1 — une reconstruction qui choisirait « un vert » et « un rouge »
au jugé échouerait ce critère.

| Rôle | Clair | Sombre |
|---|---|---|
| Fond ajouté | `#e4f5e4` | `#1a3a22` |
| Texte ajouté | `#166534` | `#7ee787` |
| Fond supprimé | `#fae4e4` | `#461c20` |
| Texte supprimé | `#8c1a1e` | `#ff7b72` |
| En-tête de section | `#6e6e7a` | `#9696a2` |

**Règle de composition :** le fond porte l'information de diff (ajouté /
supprimé), le texte porte la coloration syntaxique. L'inverse — colorer
le fond par la syntaxe — rendrait le diff illisible.

## 7. Coloration syntaxique

| Jeton | Clair | Sombre |
|---|---|---|
| `keyword` | `140, 40, 160` | `220, 150, 240` |
| `string` | `20, 110, 60` | `140, 220, 170` |
| `comment` | `100, 100, 100` | `160, 160, 160` |
| `number` | `30, 80, 180` | `150, 190, 255` |
| `name` | `30, 70, 160` | `150, 195, 255` |

**Règle :** une extension inconnue n'est **pas** colorée. Deviner un
langage produirait une coloration fausse, pire que pas de coloration.

## 8. Comportements visuels non chiffrables

Ces règles ne tiennent pas dans une constante, et c'est pourquoi elles
doivent être écrites.

- **Le centrage sur HEAD** à l'ouverture, et uniquement à l'ouverture.
  Un recentrage automatique après chaque action a été explicitement
  refusé par l'utilisateur.
- **Les chaînes linéaires sont compressées** en un nœud portant « N
  commits ». C'est ce qui rend lisible un dépôt de plusieurs milliers de
  commits.
- **Le panneau latéral occupe 40 %** de la largeur, le graphe 60 %. La
  proportion est recalculée sur la largeur réelle de la fenêtre, jamais
  en pixels absolus.
- **La fenêtre s'ouvre à la taille de l'écran disponible**, pas à une
  dimension fixe : 1400 px laissaient des bandes vides sur un écran
  large.
- **La poignée de repli du panneau** fait 16 × 48 px, centrée
  verticalement, posée PAR-DESSUS le splitter et non dedans — une
  colonne dédiée épaississait la bordure.

## 9. Ce qui garantit la fidélité

Ce document seul ne suffit pas : il dit les valeurs, pas le résultat.

Trois tests existants vérifient des **pixels réellement peints**, et
non des intentions :

- `test_syntax_everywhere.py` capture le rendu du blâme et cherche les
  couleurs de syntaxe à l'écran ;
- `test_panel_toggle.py` compte les teintes de la poignée pour
  s'assurer qu'elle n'est pas un aplat invisible ;
- `test_syntax_in_diff.py` lit les fonds ligne par ligne.

**Une reconstruction doit faire passer ces tests.** C'est le seul
critère objectif de « c'est pareil ».
