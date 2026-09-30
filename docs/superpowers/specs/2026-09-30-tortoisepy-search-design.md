# tortoisePy — Design, phase 13 : chercher un commit, sans figer l'interface

**Date :** 2026-09-30
**Statut :** brouillon, en attente de relecture

## 1. Problème

Deux manques d'usage, révélés maintenant que les commandes Git sont couvertes.

**On ne peut pas chercher.** Retrouver « le commit qui a touché
l'authentification » suppose de parcourir le graphe à l'œil, nœud par nœud.

**L'interface gèle pendant la lecture du dépôt.** Mesuré sur un dépôt de
3 000 commits : **670 ms par rafraîchissement**, dont 97 % dans
`significance._walk_once`. Le coût est linéaire — à 30 000 commits, ~3,3 s à
chaque commit, chaque fetch, chaque changement de fichier détecté.

## 2. Ce que la mesure a écarté

**Le chargement paresseux ne marche pas ici, et c'est vérifié :**

```
TOPOLOGICAL complet      333 ms
TOPOLOGICAL borné à 500  326 ms   <- aucun gain
TIME borné à 500         325 ms   <- aucun gain
NONE borné à 500          53 ms
```

Tout tri — topologique **ou** par date — force libgit2 à lire l'historique
entier avant de rendre le premier commit. Seul `SORT_NONE` est paresseux, mais
il perd l'ordre topologique dont dépend toute la logique de significativité
(un commit doit précéder ses parents).

**Lire moins n'est donc pas une option.** Restent : lire **moins souvent**, et
lire **ailleurs que sur le fil graphique**.

| # | Décision | Alternative écartée |
|---|---|---|
| D23 | Le graphe se construit **en arrière-plan** | Sur le fil graphique — l'interface gèle |
| D24 | Le résultat est **mis en cache**, invalidé par les refs | Reconstruire à chaque fois — 97 % du travail est refait pour rien |
| D25 | La recherche porte sur **message, auteur et SHA** | Le message seul — coller un SHA ou chercher un auteur est courant |
| D26 | Elle s'exécute **sur validation**, pas à chaque frappe | À la frappe — 325 ms par caractère saisi |

## 3. Le cache (D24)

### 3.1 La clé

L'empreinte des refs : chaque nom avec sa cible. **Mesuré à 0,4 ms** contre
330 ms pour reconstruire — trois ordres de grandeur, ce qui rend le cache
rentable dès le premier rafraîchissement inutile.

S'y ajoutent **HEAD** et **`state()`** : le nœud courant et une opération en
cours changent l'affichage sans qu'aucune ref ne bouge nécessairement.

### 3.2 Ce que cela change

Un `refresh()` déclenché par le surveillant de fichiers alors que rien n'a
changé dans les refs — le cas le plus fréquent — **ne coûte plus rien**.

Le cache vit en mémoire, le temps de la session. Aucune écriture, donc aucune
incidence sur §7.0.

## 4. La construction en arrière-plan (D23)

`build_graph` part dans un `BackgroundTask`, comme le fetch et le push. Le
motif existe déjà et a été éprouvé, y compris son piège : **la tâche doit être
attendue à la fermeture**, sinon le `QThread` est détruit en pleine exécution
(défaut corrigé en phase 10).

**Pendant le calcul**, le graphe précédent reste affiché et la barre de
progression tourne. Montrer un écran vide ferait croire à un dépôt vide.

**Une seule construction à la fois.** Si un rafraîchissement arrive pendant
qu'une construction tourne, il est noté et rejoué à la fin plutôt que lancé en
parallèle : deux constructions concurrentes se disputeraient le même dépôt
pour un résultat identique.

`core/` ne connaît rien de tout cela — c'est l'interface qui décide où le
travail s'exécute.

## 5. La recherche (D25, D26)

### 5.1 Le geste

Un champ en haut de la fenêtre. On tape, on valide : les commits
correspondants sont **surlignés dans le graphe**, et un compteur dit combien
ont été trouvés.

### 5.2 Où l'on cherche — le piège de cette phase

**Les commits ne sont pas les nœuds.** Vérifié : 3 000 commits se réduisent à
**10 nœuds**, la compression du graphe faisant son travail. Une recherche qui
n'examinerait que les nœuds raterait donc 99,7 % des commits.

La recherche parcourt donc **l'historique complet**, et surligne le **nœud qui
porte** chaque commit trouvé — celui sous lequel le panneau latéral le
listerait.

### 5.3 Sur validation, pas à la frappe (D26)

**Mesuré : ~325 ms** pour parcourir 3 000 commits, quel que soit le motif
(le coût est celui du parcours, pas celui de la comparaison). Chercher à
chaque caractère rendrait la saisie inutilisable.

La recherche s'exécute donc sur `Entrée`, **en arrière-plan** comme le graphe,
avec le même garde-fou : une seule à la fois.

### 5.4 Ce qui est cherché

Sans casse, sur : le **message**, le **nom de l'auteur**, et le **SHA** en
préfixe. Un seul champ pour les trois — obliger à choisir un critère avant de
taper ferait réfléchir l'utilisateur à la place de l'outil.

Un motif vide efface le surlignage.

## 6. Architecture

```
core/
  search.py       chercher dans l'historique                  (nouveau)
  graph_cache.py  empreinte des refs, cache mémoire           (nouveau)
ui/
  main_window.py  champ de recherche, graphe en arrière-plan  (modifié)
  graph_view.py   surligner un ensemble de commits            (modifié)
```

**`ui/graph_items.py`, `ui/theme.py` et `layout/` ne sont pas touchés** : le
rendu validé ne change pas.

**Le surlignage ne passe PAS par la sélection** — vérifié, ce serait un
défaut : le menu contextuel bascule selon le nombre de nœuds sélectionnés
(`main_window.py:246`, `:561`), donc une recherche à plusieurs résultats
transformerait le menu en menu de comparaison.

Il passe par un **cadre superposé** ajouté à la scène : un `QGraphicsRectItem`
sans remplissage, au-dessus des nœuds. Vérifié sur un vrai graphe — la
sélection reste inchangée (`_selected_node()` continue de répondre), les
cadres s'enlèvent proprement, et `NodeItem` n'est pas modifié.

`core/search.py` et `core/graph_cache.py` ne dépendent pas de Qt.

## 7. Tests

- **Le cache** — deux `build_graph` consécutifs sans changement rendent le même
  objet ; créer une branche l'invalide ; changer de HEAD l'invalide ; une
  opération en cours l'invalide.
- **Le gain** — un test mesure que le second appel est au moins dix fois plus
  rapide. C'est la raison d'être de D24, elle mérite d'être pinnée.
- **La recherche** — par message, par auteur, par préfixe de SHA ; sans casse ;
  motif vide ; motif introuvable ; un commit **derrière** un nœud est trouvé et
  c'est le nœud porteur qui est désigné (§5.2, le piège).
- **L'arrière-plan** — l'interface reste réactive pendant la construction ; le
  graphe précédent reste affiché ; deux rafraîchissements rapprochés ne lancent
  qu'une construction ; **fermer pendant un calcul n'abandonne pas un fil en
  cours** (le défaut de la phase 10).
- **Non-régression du rendu** — les tests de `graph_items` et de `layout`
  restent verts, sans modification.
- **Lecture seule (§7.0)** — chercher et mettre en cache n'écrivent rien.

## 8. Hors périmètre

- **Chercher dans le contenu des fichiers** (`git log -S`) — il faudrait lire
  le diff de chaque commit, ce qui ramène exactement le coût qu'on traite ici.
- **Chercher par date ou par fichier** — utile, mais chaque critère
  supplémentaire demande sa syntaxe ; on commence par les trois qui couvrent
  l'essentiel.
- **Persister le cache sur disque** — il faudrait l'invalider correctement
  entre deux lancements, et §7.0 interdit d'écrire dans le dépôt.
- **Naviguer de résultat en résultat** (suivant/précédent) — le surlignage
  suffit à un premier usage ; à ajouter s'il manque.
