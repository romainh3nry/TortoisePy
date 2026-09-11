# tortoisePy — Design

**Date :** 2026-09-11
**Statut :** brouillon, en attente de relecture

## 1. Problème

TortoiseGit n'existe pas sur macOS. Sa vue **Revision Graph** — la carte
topologique des branches d'un dépôt — n'a pas d'équivalent satisfaisant dans les
clients Git disponibles sur Mac, et `git log --graph` ne la remplace pas : il
donne un journal chronologique, pas une vue d'ensemble des relations entre refs.

tortoisePy reproduit cette vue sur macOS, et la rend actionnable.

**Position du produit.** tortoisePy reproduit la **représentation visuelle** du
Revision Graph, pas son comportement historique. Là où TortoiseGit en fait une
vue de consultation, tortoisePy en fait le point d'entrée des opérations
courantes (§3, D1). Formulé autrement : *le Revision Graph de TortoiseGit, mais
réellement interactif.*

**Nommage.** Trois noms distincts, à ne pas confondre :

| | |
|---|---|
| Projet / dépôt | `tortoisePy` |
| Package Python | `tortoisepy` |
| Commande shell | `tgraph` |

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

### 4.0 Modèle à deux niveaux

Le graphe affiché est une **compression visuelle du DAG Git, pas le DAG Git
lui-même**. Cette distinction est le point le plus important de la conception :
la confondre produit un graphe faux dans les cas courants (voir §4.2).

Trois notions distinctes :

```
Commit      oid, parents[]        — le DAG Git réel, exact
Ref         name, type, target    — branche, tag, stash, HEAD
DisplayNode commit_oid, refs[]    — ce qui est dessiné
```

`core/` conserve le DAG réel des commits. La compression décide quels commits
deviennent des `DisplayNode`. Le layout et l'UI ne voient que les `DisplayNode`.

### 4.1 Ce qui devient un nœud affiché

Un `DisplayNode` est créé pour tout commit qui est :

1. **porteur d'au moins une ref** (branche locale, branche distante, tag, HEAD) ;
2. **ou un point de jonction topologique** : merge-base entre deux refs, ou
   commit de merge dont plusieurs parents mènent à des refs distinctes.

La catégorie 2 est indispensable. Sans elle, deux branches divergentes
apparaissent comme deux composantes déconnectées — voir §4.2.

Plusieurs refs sur le même commit sont **groupées dans un seul `DisplayNode`**,
affichées en lignes empilées. Exemple tiré de la capture : un nœud contenant
`github/master`, `origin/HEAD` et `origin/master`.

**HEAD détaché :** HEAD est traité comme une ref de type `HEAD` portant le nom
court de l'OID (`[abc1234]`). S'il pointe sur un commit portant déjà d'autres
refs, il rejoint leur `DisplayNode` — un nœud unique affichant par exemple
`HEAD` et `v1.2.0`. Le nœud est alors coloré comme le nœud courant (vert).

**Stash :** un commit de stash possède **2 ou 3 parents** (HEAD au moment du
stash, l'index, et les fichiers non suivis). Il est affiché comme `DisplayNode`
mais **exclu du calcul topologique** de §4.2 : ses parents artificiels
créeraient des arêtes parasites. Un stash est relié par une seule arête à son
premier parent (le HEAD d'origine), sans participer à la réduction transitive.

**Tags annotés :** un tag annoté est un objet Git de type `tag`, pas `commit`.
Il doit être déréférencé (`peel`) vers le commit cible avant regroupement.

### 4.2 Ce qu'est une arête

Une flèche de A vers B signifie **B est un descendant de A**. Les flèches
pointent vers le descendant.

**Le cas qui invalide l'approche naïve.** Considérons deux branches divergentes :

```
A ─ B ─ C ─ D          master
         \
          X ─ Y ─ Z    feature
```

`master` n'est pas ancêtre de `feature`, ni l'inverse — vérifié avec
`git merge-base --is-ancestor`, les deux sens répondent non. Un algorithme qui
ne relie que des nœuds porteurs de refs par relation d'ancestralité ne produit
donc **aucune arête** : deux composantes déconnectées.

Le graphe correct passe par le merge-base `C`, qui ne porte aucune ref :

```
        master(D)   feature(Z)
             ↑         ↑
             └─── C ───┘
```

C'est pourquoi §4.1 catégorie 2 existe. Les merge-bases sont des nœuds de
première classe, affichés avec leur OID court comme étiquette.

Les arêtes sautent les commits intermédiaires : si deux nœuds sont séparés de
200 commits sans ref ni jonction, une seule flèche les relie.

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
| Jonction (merge-base, §4.1) | Blanc, bordure grise | absent de la capture |

Les nœuds de jonction ne portent aucune ref et n'existent pas dans la capture de
référence — TortoiseGit ne les distingue pas visuellement. Un remplissage neutre
les rend discrets : ils structurent le graphe sans attirer l'œil. Ils affichent
l'OID court comme étiquette.

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
  repository.py    ouverture, découverte, état du working tree
  refs.py          collecte et typage des refs, déréférencement des tags
  graph.py         DAG, compression, DisplayNodes, arêtes (§6.1)
  operations.py    checkout, merge, reset, branch, cherry-pick…
  results.py       OperationResult (§7.6)
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

Le pipeline suit le modèle à deux niveaux de §4.0 :

```
DAG Git complet → commits significatifs → compression → DisplayNodes → arêtes
```

**Étape 1 — collecter les refs.** Branches locales, distantes, tags, HEAD.
Déréférencer les tags annotés (objet `tag` → `commit`) via `peel`. Les stashes
sont collectés à part (voir étape 5).

**Étape 2 — marquer les commits significatifs.** Parcourir le DAG depuis toutes
les pointes de refs. Un commit est significatif s'il vérifie l'un de :

- il porte une ref ;
- c'est un merge-base entre deux pointes de refs ;
- c'est un commit de merge dont au moins deux parents mènent à des refs
  distinctes ;
- c'est une racine (aucun parent).

**Étape 3 — compresser.** Chaque commit significatif devient un `DisplayNode`.
Les segments linéaires entre eux sont remplacés par une arête unique portant le
nombre de commits sautés (utilisable plus tard comme info-bulle).

**Étape 4 — réduire transitivement.** Supprimer toute arête A→B s'il existe un
chemin A→…→C→…→B dans le graphe compressé. Ne restent que les relations
directes.

**Étape 5 — rattacher les stashes.** Chaque stash devient un `DisplayNode` relié
par une seule arête à son **premier parent**, en ignorant ses deuxième et
troisième parents. Les stashes ne participent ni à l'étape 2 ni à l'étape 4.

**Complexité.** L'étape 2 est le point sensible : calculer les merge-bases pour
toutes les paires de refs est quadratique en nombre de refs. `pygit2` expose
`merge_base_many()`, qui permet de traiter plusieurs pointes en un appel. Pour
un dépôt à 50 refs, l'approche par paires reste acceptable (~1 225 appels). Un
dépôt à plusieurs centaines de refs demandera un parcours unique avec marquage
de couleur par ref atteinte.

**La v1 implémente la version par paires. L'optimisation attend une mesure
démontrant qu'elle est nécessaire** — mais le découpage en étapes ci-dessus
permet de remplacer l'étape 2 sans toucher au reste.

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

### 7.6 Résultat d'opération

Les fonctions de `core/operations.py` ne laissent pas remonter les exceptions
pygit2 jusqu'à l'UI. Elles retournent un résultat structuré :

```python
@dataclass(frozen=True)
class OperationResult:
    success: bool
    repository_changed: bool   # le graphe doit-il être reconstruit ?
    summary: str               # phrase décrivant l'opération tentée
    git_error: str | None      # message brut de libgit2, si échec
```

`repository_changed` est distinct de `success` : une opération peut échouer
**après** avoir modifié le dépôt (un merge qui s'arrête sur conflit laisse
l'index modifié). L'UI reconstruit le graphe dès que `repository_changed` est
vrai, quel que soit `success`.

Cela évite à chaque appelant de l'UI d'envelopper les opérations dans un
`try/except` et de deviner s'il faut rafraîchir.

### 7.7 Classes d'opérations

Les opérations de §7.3 n'ont pas le même profil de risque. Trois classes, qui
déterminent le traitement en UI :

| Classe | Opérations | Traitement UI |
|---|---|---|
| **Simples** — n'échouent qu'en cas d'erreur évidente | Create branch/tag, Rename, Checkout, Copy hash, Fetch | Exécution directe, erreur affichée si échec |
| **Interactives** — peuvent s'arrêter en état intermédiaire | Merge, Rebase, Cherry-pick, Revert, Pull | Détection de l'état intermédiaire (conflits), message indiquant comment poursuivre ou abandonner |
| **Destructrices** — perte possible de travail | `reset --hard`, Delete branch, Push --delete | Confirmation préalable obligatoire (§7.5) |

Les opérations interactives sont celles qui demandent le plus de soin : en cas
de conflit, l'application n'a pas de résolveur intégré en v1. Elle affiche la
liste des fichiers en conflit et indique que la résolution se fait hors de
l'application, puis propose **Abandonner** (`merge --abort` ou équivalent) pour
revenir à l'état antérieur.

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

Le message de libgit2 n'est **jamais reformulé ni remplacé** — mais il n'est pas
non plus affiché seul. Un dialogue d'erreur comporte trois parties :

```
Fusion impossible                          ← titre : l'opération qui a échoué
La fusion de « feature » dans « master »   ← contexte : ce qui était tenté
n'a pas abouti.

Détail Git :                               ← message brut de libgit2
  1 conflict prevents checkout
```

Le contexte vient de `OperationResult.summary`, le détail de
`OperationResult.git_error`. L'utilisateur garde l'information exacte sans avoir
à deviner à quelle action elle se rapporte.

Après toute opération pour laquelle `repository_changed` est vrai (§7.6), le
graphe est **reconstruit intégralement**. Un rafraîchissement incrémental est une
optimisation prématurée tant que la reconstruction reste sous le seuil de
perception.

## 10. Tests

### 10.1 Ordre de développement

Le risque du projet n'est ni Python, ni Qt : c'est la **modélisation correcte du
graphe Git** (§4, §6). Le développement suit donc cet ordre, et non l'inverse :

1. `core/` — modèle et construction du graphe, validés sans aucune UI.
2. `layout/` — placement, validé par invariants.
3. `ui/` — rendu, une fois le modèle sûr.

Pour valider l'étape 1 sans interface, les tests sérialisent le graphe construit
en JSON et le comparent à un attendu :

```json
{
  "nodes": [
    {"oid": "abc123", "refs": [{"name": "master", "type": "local_branch"}]},
    {"oid": "def456", "refs": [], "kind": "merge_base"}
  ],
  "edges": [{"from": "def456", "to": "abc123", "skipped": 12}]
}
```

Cette sérialisation est un **outil de test**, pas une commande publique : elle
vit dans les fixtures, pas dans la CLI de §8, qu'elle alourdirait sans bénéfice
pour l'utilisateur.

### 10.2 Dépôts de référence

Dix dépôts construits par fixtures pytest, couvrant les cas dont §4.2 montre
qu'ils cassent les approches naïves :

1. Branche unique, quelques commits
2. Deux branches divergentes (le cas du merge-base, §4.2)
3. Un merge
4. Merges imbriqués, plusieurs merge-bases
5. Branche de 1 000 commits sans aucune ref (compression)
6. Plusieurs refs sur un même commit (regroupement)
7. Tags légers et tags annotés (déréférencement)
8. Branches distantes avec plusieurs remotes
9. Stash (2 et 3 parents)
10. HEAD détaché, dont un cas sur un commit déjà porteur d'un tag

Cas limites additionnels : dépôt vide sans aucun commit, dépôt sans branche,
dépôt à racines multiples (historiques non liés).

### 10.3 Invariants du graphe

Testés sur les dix dépôts plutôt qu'assertés cas par cas :

- Chaque OID apparaît au plus une fois parmi les `DisplayNode`.
- Chaque ref appartient à exactement un `DisplayNode`.
- Toute arête relie deux nœuds existants.
- Le graphe est acyclique.
- Deux refs reliées dans le DAG Git le restent dans le graphe compressé
  (aucune composante artificiellement déconnectée).
- Les stashes n'ont qu'une arête sortante.

### 10.4 Invariants du layout

Assertions sur les propriétés, jamais sur des coordonnées exactes :

- `descendant.y < ancêtre.y` pour toute arête.
- Aucun chevauchement de rectangles de nœuds.
- Déterminisme : deux exécutions sur le même dépôt donnent des coordonnées
  identiques.
- **Stabilité locale** : ajouter une ref à un commit existant ne déplace pas
  l'ensemble du graphe. Sans cette propriété, l'interface « saute » à chaque
  opération et devient désagréable à l'usage.

### 10.5 Opérations et UI

- **`operations/`** — chaque opération sur un dépôt temporaire, vérification de
  l'état résultant et du `OperationResult` retourné (§7.6), y compris les cas
  d'échec et les états intermédiaires (merge en conflit).
- **`ui/`** — `pytest-qt`, couverture limitée : ouverture de fenêtre, présence
  des entrées de menu contextuel selon la sélection, activation/désactivation
  correcte selon le type de nœud. Le rendu visuel n'est pas testé
  automatiquement.

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
