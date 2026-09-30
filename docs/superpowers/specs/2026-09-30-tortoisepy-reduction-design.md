# tortoisePy — Design, phase 17 : le graphe sur un vrai gros dépôt

**Date :** 2026-09-30
**Statut :** brouillon, en attente de relecture

## 1. Problème

Signalé par l'utilisateur : sur son dépôt `vti`, **chaque action gèle
l'application** et le graphe met très longtemps à se charger.

Mesuré sur ce dépôt — **21 816 commits, 712 refs** dont 413 tags :

```
build_graph : 19 s
```

Les phases précédentes ont été validées sur un dépôt de test de 3 000 commits
et 10 refs, où la même opération prenait 355 ms. **Ce cas ne représentait pas
la réalité de l'utilisateur** : 7× plus de commits, 70× plus de refs, et une
topologie bien plus dense.

## 2. Ce que la mesure a trouvé

```
reduce_transitive_edges      16,8 s   <- 88 % du temps
drop_all_junctions            1,0 s
significant_commits           1,1 s
compress_linear_segments      0,0 s
collapse_trivial_junctions    0,0 s
```

**Ce n'est pas libgit2 cette fois, c'est notre propre algorithme.**

`reduce_transitive_edges` appelle `_reaches` pour chacune des 23 862 arêtes, et
chaque appel reparcourt le graphe depuis zéro — sans jamais réutiliser ce qu'il
vient d'apprendre. Le profil montre **102 millions** d'opérations de liste.

| # | Décision | Alternative écartée |
|---|---|---|
| D38 | Calculer les descendants **une fois**, en ordre topologique | Mémoïser `_reaches` — mesuré, gain ×1 seulement |
| D39 | Représenter les ensembles de descendants par des **entiers** | Des `set` — mesuré, ×4 au lieu de ×380 |
| D40 | Le résultat doit être **identique**, arête pour arête | « Assez proche » — le graphe est validé visuellement (mémoire projet) |

## 3. La correction

### 3.1 Une seule passe (D38)

Les arêtes forment un graphe acyclique. En le remontant **en ordre topologique
inverse**, chaque nœud hérite des descendants de ses enfants :

```
descendants(n) = ⋃ ({enfant} ∪ descendants(enfant))
```

Chaque nœud est visité une fois, au lieu d'être reparcouru pour chaque arête.

### 3.2 Des entiers plutôt que des ensembles (D39)

Chaque nœud reçoit un indice, et l'ensemble de ses descendants devient un
entier dont le bit *i* dit « le nœud *i* est atteignable ».

L'union de deux ensembles devient `a | b` — une instruction machine, là où
`set | set` parcourt les éléments. Sur 16 000 nœuds, c'est ce qui fait
l'essentiel du gain :

```
actuel                          16,4 s
ordre topologique + set          4,6 s   (×4)
ordre topologique + entiers      0,04 s  (×380)
```

### 3.3 Le résultat est identique (D40)

Vérifié sur les 23 862 arêtes réelles de `vti` : **21 608 arêtes conservées de
part et d'autre, les mêmes**. Le rendu du graphe ne change pas — ce que la
mémoire du projet exige.

C'est la condition de cette phase, et son test principal : une optimisation qui
changerait le graphe serait un défaut, pas une amélioration.

## 4. Le cas du cycle

Un graphe Git est acyclique, mais un tri topologique laisse de côté les nœuds
d'un cycle éventuel — leur masque resterait vide.

**Vérifié :** dans ce cas l'algorithme **conserve** des arêtes au lieu d'en
supprimer à tort, et l'implémentation actuelle se comporte exactement pareil
(2 arêtes gardées sur 2). La dégradation est sûre : un graphe un peu chargé,
jamais faux.

## 5. Ce que cela donne, et ce qui reste

```
avant : build_graph 19 s
après : build_graph ~3 s
```

Ce qui subsiste : `significant_commits` (1,1 s), `drop_all_junctions` (1,0 s),
`read_state` (0,5 s).

**Le gel pendant le fetch est un problème distinct.** Le fetch s'exécute déjà
en arrière-plan ; c'est le `refresh()` qui suit, sur le fil graphique, qui
gèle. Le ramener de 20 s à 3 s le rend supportable, **sans le supprimer**.
Déporter `build_graph` dans un fil est la suite logique — à décider **après**
avoir remesuré (§7).

## 6. Architecture

```
core/
  reduction.py   un seul parcours, masques entiers   (réécrit)
```

**Un seul fichier.** Rien dans `ui/`, `layout/`, ni `theme.py` : le graphe
produit est identique, donc le rendu aussi.

## 7. Tests

- **Le résultat est identique** — sur des graphes construits à la main, et sur
  un dépôt réel : mêmes arêtes, à l'ensemble près. C'est le test central.
- **Les cas déjà couverts** par `tests/core/test_reduction.py` restent verts
  sans modification : c'est le garde-fou de la réécriture.
- **Un cycle** ne fait pas planter, et conserve les arêtes (§4).
- **Un graphe vide**, une arête seule, un ancêtre à un seul descendant.
- **Le gain** — un test mesure que la réduction d'un graphe dense reste sous
  une seconde. Sans lui, une régression de performance passerait inaperçue,
  comme celle-ci l'a fait pendant seize phases.
- **Le rendu ne bouge pas** — `tests/ui/test_graph_items.py` et `tests/layout/`
  restent verts, sans modification.

## 8. Hors périmètre

- **`build_graph` en arrière-plan** — la suite logique, à décider après
  remesure (§5). Elle demande de gérer l'affichage pendant le calcul et la
  sérialisation des demandes concurrentes.
- **`significant_commits` et `drop_all_junctions`** (2,1 s à eux deux) — à
  traiter si le reliquat gêne encore.
- **Limiter le nombre de refs affichées** — 413 tags sur 712 refs ; les
  masquer par défaut existe déjà (`GraphOptions`), et changer ce défaut
  toucherait au rendu validé.
