# tortoisePy — Design, phase 16 : le dernier point de lenteur

**Date :** 2026-09-30
**Statut :** brouillon, en attente de relecture

## 1. Problème

La phase 13 a mis le graphe en cache : un rafraîchissement sans changement
devait tomber de 680 ms à 2 ms. **Il est resté à ~310 ms.**

Mesuré : le temps ne vient plus du graphe, mais de `commits_for_node`, qui
recharge l'historique du nœud sélectionné **à chaque rafraîchissement et à
chaque clic** :

```
refresh (3 000 commits) : 305, 322, 310 ms
commits_for_node        : 292 ms
  dont _history         : 294 ms sur 298 — le parcours libgit2
```

Et il recharge toujours la même chose :

```
ouverture + 3 refresh -> 4 appels, pour 1 seul OID distinct
```

C'est le dernier endroit où l'application fige perceptiblement.

## 2. Ce qui ne marcherait pas, et pourquoi

**Borner le parcours ne gagne rien.** C'est la même limite qu'en phase 13 :
tout tri libgit2 lit l'historique entier avant de rendre le premier commit, et
`_history` est déjà borné à 500. Le coût est celui du tri, pas du volume rendu.

**Abandonner le tri topologique** ferait gagner 6× mais casserait l'ordre
d'affichage, et le marquage `own` en dépend.

Reste donc la même réponse qu'en phase 13 : **ne pas recalculer ce qui n'a pas
changé.**

| # | Décision | Alternative écartée |
|---|---|---|
| D35 | Un cache **par nœud**, dans la fenêtre principale | Un cache dans `core/commits.py` — le cœur ne doit pas garder d'état entre deux appels |
| D36 | Invalidé par l'**empreinte du dépôt**, celle de `GraphCache` | Une empreinte propre — deux mécanismes à garder d'accord |
| D37 | `⌘F` place le curseur dans le champ de recherche | Rien — le champ existe depuis la phase 13 et n'a aucun raccourci |

## 3. Le cache (D35, D36)

### 3.1 Ce qui l'invalide

`commits_for_node` dépend de **deux** choses : le dépôt (pour l'historique) et
**le graphe** (pour le marquage `own`, qui vient des arêtes). Un cache qui
n'observerait que les refs afficherait de mauvais marqueurs si le graphe
changeait.

**Vérifié :** l'empreinte de `GraphCache` couvre les deux. Elle porte les refs,
HEAD et l'état ; à empreinte égale, `build_graph` rend le même graphe, donc les
mêmes `own`. Une seule empreinte pour les deux caches, et pas deux mécanismes à
maintenir d'accord.

### 3.2 Ce qu'il garde

Un dictionnaire `OID -> commits`, vidé dès que l'empreinte change. Pas de
limite de taille : un nœud coûte au plus 500 `CommitInfo`, et le graphe en
compte une dizaine après compression — **3 000 commits donnent 10 nœuds**
(mesuré en phase 13).

### 3.3 Là où il ne doit pas mentir

Le panneau montre aussi les **marqueurs de non-poussé**, qui viennent de
`unpushed_oids` et changent après un push sans qu'aucun commit ne bouge. Ils
sont passés au panneau à l'affichage, **pas stockés dans le cache** : ce qui
est mis en cache, c'est l'historique, pas sa décoration.

## 4. `⌘F` (D37)

Le champ de recherche existe depuis la phase 13, sans raccourci : il faut
cliquer dedans.

`Ctrl+F` / `⌘F` y place le curseur et sélectionne son contenu, pour qu'une
nouvelle recherche remplace la précédente sans avoir à effacer.

**Vérifié libre.** Les raccourcis pris sont `Ctrl+0`, `Ctrl+9`, `Ctrl+K`
(Commit), `Ctrl+L` (Pull), `Ctrl+P` (Push), `Ctrl+Shift+F` (Fetch), plus les
standards de zoom et de rafraîchissement.

## 5. Architecture

```
ui/
  main_window.py   cache par nœud, raccourci ⌘F   (modifié)
```

**Rien dans `core/`** : le cœur reste sans état entre deux appels (D35), et
`commits_for_node` n'est pas touché. Rien non plus dans `theme.py`,
`layout/` ni `graph_items.py`.

## 6. Tests

- **Le gain** — deux sélections du même nœud n'appellent `commits_for_node`
  qu'une fois. C'est la raison d'être de la phase.
- **L'invalidation** — un nouveau commit, une nouvelle branche, un changement
  de HEAD rechargent le panneau. Un cache qui ne s'invalide pas affiche un
  historique faux, ce qui est pire que lent.
- **Plusieurs nœuds** — cliquer A, puis B, puis A ne recharge pas A.
- **Les marqueurs de non-poussé** — après un push, ils disparaissent du
  panneau bien que l'historique soit inchangé (§3.3).
- **`⌘F`** — le champ prend le focus, et son contenu est sélectionné.
- **Lecture seule (§7.0)** — mettre en cache n'écrit rien.

## 7. Hors périmètre

- **Mettre `_history` en arrière-plan** — le cache supprime la répétition ;
  déporter le premier calcul demanderait de gérer l'affichage pendant qu'il
  tourne, pour 300 ms une fois par nœud.
- **Persister le cache** — il vaut pour une session ; le relire d'un
  lancement à l'autre demanderait de l'invalider correctement, et §7.0
  interdit d'écrire dans le dépôt.
- **Naviguer entre les résultats de recherche** (suivant/précédent) — déjà
  écarté en phase 13.
