# tortoisePy — Design, phase 18 : une couleur par type de ref

**Date :** 2026-09-30
**Statut :** brouillon, en attente de relecture

## 1. Problème

Un nœud porte souvent plusieurs refs — `develop`, `origin/develop`, `4.2.0` —
et **elles ont toutes la même couleur**. Rien ne distingue ce qui est local de
ce qui est sur le serveur, ni une branche d'un tag.

Aujourd'hui le nœud entier prend **une seule** couleur, choisie par priorité
(HEAD, puis branche locale, puis distante, puis tag). L'information sur les
autres refs est perdue.

L'utilisateur a fourni une capture de référence.

## 2. Ce qui change, et ce qui ne change pas

| # | Décision | Alternative écartée |
|---|---|---|
| D41 | **Une bande colorée par ligne**, selon le type de la ref | Une couleur par nœud — c'est l'état actuel, qui masque l'information |
| D42 | Seule la **ligne** de la branche courante est rouge | Tout le nœud en rouge — on perdrait le type des autres refs |
| D43 | La ligne `HEAD` est masquée **quand une branche locale la porte** | La masquer toujours (§4.2) ; la garder toujours (ligne redondante) |

**Les flèches ne changent pas.** L'utilisateur l'a dit explicitement : leur
sens, leurs courbes et leur rendu restent exactement ce qu'ils sont.

## 3. Les couleurs

| Type | Couleur |
|---|---|
| Branche locale | **vert** |
| Branche locale **courante** | **rouge** |
| Branche distante | **beige** |
| Tag | **jaune** |

Les nœuds sans ref (jonctions), les stashes et les nœuds sélectionnés gardent
leur traitement actuel : ils n'ont pas de refs à distinguer.

## 4. Les deux cas qui demandent une décision

### 4.1 La branche courante (D42)

Sur le nœud où l'on se trouve, **seule la ligne de la branche locale courante**
passe au rouge. Sa jumelle distante reste beige, ses tags restent jaunes.

C'est ce que montre la capture de référence : `MYMT-1243` est rouge tandis que
`origin/MYMT-1243` reste beige sur le même nœud.

### 4.2 La ligne `HEAD` (D43)

Le graphe ajoute une ligne `HEAD` sur le nœud courant. Elle n'appartient à
aucune des quatre catégories, et la capture de référence ne la montre pas.

**Vérifié sur `vti`** : la masquer ne perd rien, car `develop` reste affichée et
sera rouge — ce qui dit déjà qu'on est dessus.

```
refs du nœud : ['develop', 'origin/develop', 'origin/HEAD', 'HEAD']
sans HEAD    : ['develop', 'origin/develop', 'origin/HEAD']
```

**Mais en HEAD détachée, c'est faux** — vérifié aussi :

```
refs du nœud : ['main', 'HEAD']
sans HEAD    : ['main']
```

`main` s'afficherait alors en vert, comme une branche ordinaire, alors qu'on
n'est **pas** dessus. Le repère serait perdu.

**Règle retenue :** masquer `HEAD` seulement quand une branche locale du même
nœud porte déjà l'information — c'est-à-dire quand HEAD n'est pas détachée. La
garder sinon, en rouge.

## 5. Ce que cela touche

Le rendu du graphe est **validé par l'utilisateur** et ne doit pas être
dégradé (mémoire du projet). Cette phase le modifie donc volontairement, mais
dans un périmètre étroit :

- **les dimensions, positions, courbes et flèches ne bougent pas** — seule la
  couleur de fond de chaque ligne change ;
- **`layout/` n'est pas touché** : la mise en page ne dépend pas des couleurs ;
- **le marqueur de commit non poussé** reste dessiné par-dessus, inchangé.

## 6. Architecture

```
ui/
  theme.py        une couleur par type de ref          (modifié)
  graph_items.py  une bande par ligne                  (modifié)
```

`graph_items.py` dessine aujourd'hui **un** rectangle pour tout le nœud ; il en
dessinera un par ligne, empilés, avec les coins arrondis seulement en haut et
en bas — comme sur la capture.

## 7. Tests

- **Chaque type a sa couleur** — locale, distante, tag, courante : quatre
  teintes distinctes, vérifiées deux à deux.
- **La branche courante seule est rouge** (D42) — sur un nœud portant
  `feature` et `origin/feature`, seule la première l'est.
- **`HEAD` est masquée quand une branche locale la porte** (D43).
- **`HEAD` est gardée en HEAD détachée** — le test qui distingue cette phase
  d'une simplification naïve.
- **Les jonctions, stashes et nœuds sélectionnés** gardent leur couleur
  actuelle : leurs tests existants restent verts sans modification.
- **La géométrie ne change pas** — la hauteur d'un nœud et la position de ses
  lignes restent celles que `QtMeasurer` calcule aujourd'hui.

## 8. Hors périmètre

- **Le sens et le dessin des flèches** — l'utilisateur l'a exclu explicitement.
- **L'ordre des refs dans un nœud** — déjà locale puis distante puis tag, ce
  qui correspond à la capture.
- **Une couleur pour les stashes ou les jonctions** — ils n'ont pas de refs à
  distinguer.
- **Rendre les couleurs configurables** — un réglage à créer, à documenter et
  à tester, pour un besoin qui n'est pas exprimé.
