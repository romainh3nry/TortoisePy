# tortoisePy — Design

**Date :** 2026-09-11
**Statut :** brouillon, en attente de relecture

## 1. Problème

TortoiseGit n'existe pas sur macOS. Sa vue **Revision Graph** — la carte
topologique des branches d'un dépôt — n'a pas d'équivalent satisfaisant dans les
clients Git disponibles sur Mac, et `git log --graph` ne la remplace pas : il
donne un journal chronologique, pas une vue d'ensemble des relations entre refs.

tortoisePy reproduit cette vue sur macOS, et la rend actionnable.

## 2. Périmètre

### Dans le périmètre (v1)

- Une fenêtre affichant le Revision Graph, visuellement fidèle à TortoiseGit.
- Lancement par une commande shell depuis n'importe quel dossier d'un dépôt.
- Menu contextuel sur les nœuds, permettant les opérations Git courantes.
- Navigation : zoom, panoramique, mini-carte d'ensemble.

### Hors périmètre (v1)

- Le **Log Dialog** (liste chronologique des commits avec lanes colorées). C'est
  l'autre vue majeure de TortoiseGit ; elle mérite son propre cycle de
  conception. Voir §11.
- L'intégration au menu contextuel du Finder.
- Le diff visuel intégré (v1 délègue à un outil externe, voir §7.4).
- Windows et Linux. Le code évite les dépendances spécifiques à macOS, mais seul
  macOS est testé et supporté en v1.

## 3. Décisions à valider

Ces points ont été tranchés par défaut faute d'arbitrage explicite. Ils sont
signalés pour relecture.

| # | Décision prise | Alternative écartée |
|---|---|---|
| D1 | Menu contextuel **enrichi** : le graphe garde le visuel de TortoiseGit, mais le clic droit propose les actions du Log Dialog (Checkout, Merge, Reset…) | Fidélité stricte : TortoiseGit n'offre que *Show Log* et *Compare Revisions* sur le Revision Graph |
| D2 | **PySide6** (LGPL) plutôt que PyQt6 (GPL/commercial) | PyQt6, si la licence GPL n'est pas un problème |
| D3 | Nom de commande : **`tgraph`** | `tortoisepy`, `ggraph` — disponibilité PyPI non vérifiée |
| D4 | Lecture seule sur les opérations destructrices sans confirmation explicite | Exécution directe |

**D1 est la décision structurante.** TortoiseGit traite le Revision Graph comme
une vue de consultation : sa documentation ne mentionne que deux entrées de menu
contextuel. Le besoin exprimé — « pouvoir y faire toutes les commandes git
classiques » — impose d'aller au-delà de la fidélité stricte. Si la fidélité
prime, D1 doit être inversée et le périmètre v1 se réduit fortement.

## 4. Le graphe : sémantique

### 4.1 Ce qu'est un nœud

Un nœud n'est **pas un commit**. C'est un **point de référence** : un commit sur
lequel pointe au moins une ref (branche locale, branche distante, tag, stash,
HEAD). L'historique linéaire entre deux refs est compressé — c'est ce qui rend la
vue lisible sur un dépôt réel.

Plusieurs refs sur le même commit sont **groupées dans un seul nœud**, affichées
en lignes empilées. Exemple tiré de la capture de référence : un nœud contenant
`github/master`, `origin/HEAD` et `origin/master`.

### 4.2 Ce qu'est une arête

Une flèche de A vers B signifie **B est un descendant de A** — il existe un
chemin dans le graphe des commits allant de A à B. Les flèches pointent vers le
descendant.

Les arêtes sautent les commits intermédiaires : si `master` et `merge_1` sont
séparés de 200 commits sans ref, une seule flèche les relie.

### 4.3 Couleurs

Déduites de la capture de référence. La documentation TortoiseGit indique que ces
couleurs sont configurables et ne documente pas les valeurs par défaut — cette
table est donc une reconstitution, à ajuster si les teintes ne correspondent pas.

| Type de nœud | Couleur | Repère visuel |
|---|---|---|
| Branche courante (HEAD) | Vert | `master` dans la capture |
| Branche locale | Jaune | `merge_1`, `debug_problem` |
| Branche distante | Beige / pêche | `origin/master`, `github/renaming` |
| Stash | Gris | `stash` |
| Nœud sélectionné | Rouge foncé, texte blanc | `RevisionGraph` |
| Tag | Jaune | `REL_1.7.15.0_EXTERNAL` |

Sur la capture, tags et branches locales partagent la même teinte jaune. Le type
de chaque nœud est néanmoins conservé dans le modèle, indépendamment de sa
couleur : §7.3 s'en sert pour désactiver les actions de branche sur un tag. Si
l'usage montre que la confusion visuelle gêne, une teinte distincte pourra être
attribuée aux tags sans changement d'architecture.

Les couleurs seront définies dans un module unique afin de rester paramétrables
ultérieurement sans toucher au moteur de rendu.

### 4.4 Forme et typographie

- Nœuds : rectangles à coins arrondis, bordure fine plus sombre que le
  remplissage.
- Police : **monospace**, conformément à la capture.
- Un nœud multi-refs s'étend verticalement, une ligne par ref.
- Arêtes : courbes noires terminées par une pointe de flèche pleine.

## 5. Architecture

Quatre couches, chacune testable isolément.

```
cli.py          → découverte du dépôt, parsing des arguments, démarrage Qt
  ↓
core/           → accès Git (pygit2). Aucune dépendance Qt.
  repository.py    ouverture, liste des refs, HEAD, stashes
  graph.py         construction du graphe : nœuds + arêtes
  operations.py    checkout, merge, reset, branch, cherry-pick…
  ↓
layout/         → placement 2D des nœuds. Pure logique, aucune dépendance Qt.
  engine.py        algorithme de disposition
  ↓
ui/             → PySide6
  main_window.py   fenêtre, menus, toolbar
  graph_view.py    QGraphicsView : rendu, zoom, panoramique
  graph_items.py   QGraphicsItem des nœuds et arêtes
  minimap.py       vue d'ensemble
  dialogs/         un fichier par dialogue d'action
  theme.py         couleurs, polices, métriques
```

**Règle de dépendance :** `core/` et `layout/` n'importent jamais PySide6. Cela
les rend testables sans serveur graphique et garde la logique Git réutilisable —
notamment si le projet devait un jour être porté vers un autre langage, la
bibliothèque sous-jacente (libgit2) étant la même.

## 6. Construction du graphe

### 6.1 Algorithme

1. Collecter toutes les refs : branches locales, branches distantes, tags,
   stashes, HEAD.
2. Résoudre chaque ref vers son commit cible (en déréférençant les tags annotés).
3. Grouper les refs par OID de commit → un nœud par OID distinct.
4. Déterminer les arêtes : pour chaque paire de nœuds (A, B), une arête A→B
   existe si A est un ancêtre de B **et** qu'aucun nœud C n'est à la fois
   descendant de A et ancêtre de B (réduction transitive — on ne trace que les
   relations directes).
5. Détecter les racines : nœuds sans ancêtre parmi les nœuds du graphe.

`pygit2` fournit `descendant_of()` pour l'étape 4, mais l'appeler sur toutes les
paires est quadratique. Pour un dépôt à 50 refs, c'est 2 500 appels — acceptable.
Au-delà, un parcours unique depuis chaque nœud avec mémoïsation des ancêtres
atteints sera nécessaire. **La v1 implémente la version simple ; l'optimisation
attend une mesure réelle démontrant qu'elle est nécessaire.**

### 6.2 Disposition

L'algorithme place les nœuds en respectant deux contraintes :

- Un descendant est toujours placé **au-dessus** de son ancêtre (la capture
  montre `master` en bas, ses descendants au-dessus).
- Les arêtes se croisent le moins possible.

Approche retenue : **tri topologique en couches** (algorithme de Sugiyama
simplifié).

1. Assigner à chaque nœud un rang = longueur du plus long chemin depuis une
   racine.
2. Ordonner les nœuds à l'intérieur de chaque rang pour réduire les croisements
   (heuristique du barycentre, deux ou trois passes).
3. Convertir rangs et positions en coordonnées, en tenant compte de la largeur
   réelle de chaque nœud (variable : un nœud à trois refs est plus haut, un nom
   de branche long est plus large).

La disposition exacte de TortoiseGit ne sera pas reproduite au pixel près — son
algorithme n'est pas documenté. L'objectif est une disposition **lisible et
stable** : deux ouvertures successives sur un dépôt inchangé doivent produire la
même image.

## 7. Interactions

### 7.1 Navigation

| Geste | Effet |
|---|---|
| Molette | Défilement vertical |
| ⌘ + molette | Zoom centré sur le curseur |
| Glisser sur fond vide | Panoramique |
| Glisser dans la mini-carte | Déplacement du viewport |
| ⌘0 | Zoom 100 % |
| ⌘9 | Ajuster à la fenêtre |

### 7.2 Sélection

- Clic sur un nœud : sélection (nœud en rouge foncé).
- ⌘ + clic : ajoute à la sélection. Deux nœuds sélectionnés activent les actions
  de comparaison.
- Clic sur fond vide : désélection.

**Note d'adaptation :** TortoiseGit utilise Ctrl+clic ; sur macOS, Ctrl+clic est
le clic droit système. ⌘+clic est la convention macOS équivalente et est donc
retenue.

### 7.3 Menu contextuel — un nœud sélectionné

Conformément à D1. Les entrées agissant sur une branche sont désactivées pour les
nœuds stash et tag.

- **Show Log** — historique du commit
- **Checkout / Switch** — bascule sur cette branche
- **Create Branch here…**
- **Create Tag here…**
- **Merge into current branch…**
- **Rebase current branch onto this…**
- **Cherry-pick this commit…**
- **Reset current branch to this…** (soft / mixed / hard)
- **Revert this commit…**
- **Delete branch** (branches locales et distantes)
- **Rename branch…** (branches locales)
- **Push…** / **Pull…** / **Fetch…**
- **Copy commit hash**

### 7.4 Menu contextuel — deux nœuds sélectionnés

- **Compare revisions** — liste des fichiers modifiés entre les deux commits
- **Show log of differences** — commits présents dans l'un et pas dans l'autre

La v1 délègue l'affichage des diffs à l'outil configuré dans
`git config diff.tool`, ou à défaut affiche un diff textuel dans une fenêtre
simple. Un visualiseur de diff intégré est hors périmètre.

### 7.5 Confirmations (D4)

Les opérations destructrices ou difficiles à annuler exigent une confirmation
nommant explicitement ce qui va se produire :

- `reset --hard`
- suppression de branche
- suppression de branche distante (`push --delete`)
- toute opération avec des modifications non commitées dans l'arbre de travail

Le dialogue indique la branche concernée et ce qui sera perdu. Pas de case
« ne plus demander » en v1.

## 8. Interface en ligne de commande

```
tgraph              # dépôt du dossier courant
tgraph /chemin      # dépôt à ce chemin
tgraph --version
```

Découverte du dépôt via `pygit2.discover_repository()`, qui remonte
l'arborescence comme le fait Git — la commande fonctionne donc depuis n'importe
quel sous-dossier.

**Attention :** `discover_repository()` lève une exception lorsqu'aucun dépôt
n'est trouvé (`KeyError` sur les versions anciennes de pygit2, `GitError` sur les
récentes). Elle ne retourne pas `None`. La gestion d'erreur doit donc passer par
`try/except` sur ces deux types, et non par un test de nullité.

En l'absence de dépôt, la commande affiche un message sur stderr et sort avec le
code 1, sans ouvrir de fenêtre.

Installation : `[project.scripts]` dans `pyproject.toml`, installé par
`pip install -e .`. La distribution d'un binaire autonome (PyInstaller) est hors
périmètre v1 — pygit2 embarquant libgit2 en natif, c'est un chantier d'empaquetage
à part entière.

## 9. Gestion des erreurs

Trois catégories, traitées différemment :

| Catégorie | Exemple | Traitement |
|---|---|---|
| Pas de dépôt | Lancement hors d'un dépôt | Message stderr, code de sortie 1 |
| Opération Git refusée | Merge en conflit, checkout avec modifications locales | Dialogue affichant le message d'erreur Git brut, graphe inchangé |
| Dépôt illisible | Dépôt corrompu, permissions | Dialogue, puis fermeture |

Les erreurs Git ne sont jamais reformulées : le message de libgit2 est affiché
tel quel. Une reformulation approximative serait plus nuisible qu'utile pour un
utilisateur qui connaît Git.

Après toute opération modifiant le dépôt, le graphe est **reconstruit
intégralement**. Un rafraîchissement incrémental est une optimisation
prématurée tant que la reconstruction reste sous le seuil de perception.

## 10. Tests

- **`core/`** — dépôts de test construits par fixtures pytest (création de
  commits, branches, merges via pygit2). Couvre : découverte des refs,
  groupement par OID, calcul des arêtes, réduction transitive, cas limites
  (dépôt vide, dépôt sans commit, HEAD détaché, repo à une seule branche).
- **`layout/`** — assertions sur les invariants plutôt que sur des coordonnées
  exactes : un descendant est toujours au-dessus de son ancêtre, aucun
  chevauchement de nœuds, déterminisme (deux exécutions donnent le même
  résultat).
- **`operations/`** — chaque opération sur un dépôt temporaire, vérification de
  l'état résultant. Inclut les cas d'échec attendus.
- **`ui/`** — `pytest-qt`, couverture limitée : ouverture de fenêtre, présence
  des entrées de menu contextuel selon la sélection, activation/désactivation
  correcte. Le rendu visuel n'est pas testé automatiquement.

## 11. Suites envisagées

Hors périmètre v1, documentées pour mémoire et par ordre de valeur estimée :

1. **Log Dialog** — la liste chronologique avec lanes colorées, seconde vue
   majeure de TortoiseGit. C'est le complément naturel du graphe.
2. **Visualiseur de diff intégré** — remplace la délégation externe.
3. **Dialogue de commit** avec staging par hunks.
4. **Intégration Finder** — Quick Action macOS pour un « Ouvrir ici » depuis le
   menu contextuel.
5. **Portage Windows** — l'architecture ne l'empêche pas ; demande une passe de
   test et d'empaquetage.
6. **Empaquetage autonome** — PyInstaller, pour distribution à des utilisateurs
   sans Python.

## 12. Choix techniques

| Élément | Choix | Raison |
|---|---|---|
| Langage | Python 3.13 | Vitesse d'itération sur un projet dont l'UI va beaucoup évoluer. Le travail lourd est en C (libgit2, Qt). |
| Accès Git | pygit2 | Liaison à libgit2. Évite d'analyser la sortie texte de Git. |
| UI | PySide6 | LGPL. API quasi identique à PyQt6. Voir D2. |
| Rendu du graphe | QGraphicsView / QGraphicsScene | Zoom, panoramique et sélection fournis nativement ; adapté à des milliers d'éléments. |
| Tests | pytest, pytest-qt | Standard. |
