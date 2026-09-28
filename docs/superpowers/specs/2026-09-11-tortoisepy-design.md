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

## 3. Décisions

| # | Décision | Statut | Alternative écartée |
|---|---|---|---|
| D1 | Menu contextuel **enrichi** : le graphe garde le visuel de TortoiseGit, mais le clic droit propose les actions du Log Dialog (Checkout, Merge, Reset…) | **Validée** | Fidélité stricte : TortoiseGit n'offre que *Show Log* et *Compare Revisions* sur le Revision Graph |
| D2 | **PySide6** (LGPL) plutôt que PyQt6 (GPL/commercial) | Acceptée par défaut | PyQt6, si la licence GPL n'est pas un problème |
| D3 | Nom de commande : **`tgraph`** | Acceptée par défaut | `tortoisepy`, `ggraph` — disponibilité PyPI non vérifiée |
| D4 | Confirmation obligatoire avant toute opération destructrice | Acceptée par défaut | Exécution directe |

**D1 est la décision structurante, et elle est validée.** TortoiseGit traite le
Revision Graph comme une vue de consultation : sa documentation ne mentionne que
deux entrées de menu contextuel. tortoisePy s'en écarte délibérément — c'est ce
qui distingue le produit, comme énoncé en §1.

D2, D3 et D4 n'ont pas fait l'objet d'un arbitrage explicite mais n'ont pas été
contestés sur deux relectures. Toutes trois sont peu coûteuses à inverser : D3
est une ligne de `pyproject.toml`, D4 un paramètre, D2 un changement d'import
(l'API PyQt6 est quasi identique).

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

Trois notions à ne jamais confondre — les mélanger est une source de bugs
classique dans ce type de code :

| Niveau | Formulation |
|---|---|
| Relation Git | `parent → child` (un commit pointe vers ses parents) |
| Arête du graphe | `GraphEdge(ancestor, descendant)` — champs **nommés**, jamais `from`/`to` |
| Rendu | la flèche est dessinée de l'ancêtre vers le descendant, donc du bas vers le haut |

```python
@dataclass(frozen=True)
class GraphEdge:
    ancestor: Oid       # le plus ancien
    descendant: Oid     # le plus récent
    skipped: int        # commits compressés entre les deux
```

Le modèle ne connaît que `ancestor`/`descendant`. La direction visuelle est une
décision de `layout/` et `ui/` seuls : si le sens de dessin change un jour, le
modèle n'est pas touché.

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

### 4.2.1 La compression est visuelle, jamais sémantique

Conséquence à ne pas manquer : si les commits compressés disparaissaient du
modèle, il deviendrait impossible de les sélectionner, d'en copier le hash, d'en
faire un cherry-pick ou d'en voir le contenu. L'outil perdrait l'essentiel de ce
que Git permet.

**Les commits intermédiaires restent donc dans le modèle.** Seul le rendu les
masque.

- Chaque arête connaît la liste ordonnée des OID qu'elle saute (`skipped` est le
  décompte ; la liste elle-même est conservée).
- Une arête portant au moins un commit sauté affiche le décompte comme
  étiquette (« 200 commits »).
- **Clic sur une arête** → panneau listant les commits sautés, chacun
  sélectionnable et porteur du même menu contextuel qu'un nœud (§7.3).

Le coût mémoire est celui d'une liste d'OID par arête — négligeable devant le
DAG déjà chargé.

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
  repository.py    ouverture, découverte
  state.py         RepositoryState (§7.8)
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
  watcher.py       surveillance de .git, anti-rebond (§7.9)
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

**Étape 2 — marquer les commits significatifs.**

*Intention* (ce qui doit être vrai, indépendamment de l'algorithme) :

> Conserver l'ensemble **minimal** de commits préservant la connectivité
> topologique entre les refs. Deux refs reliées dans le DAG Git doivent le
> rester dans le graphe compressé, et tout point où l'histoire diverge ou
> converge doit rester visible.

*Implémentation v1.* Un commit est significatif s'il vérifie l'un de :

- il porte une ref ;
- il appartient à l'ensemble des merge-bases entre deux pointes de refs ;
- **c'est un commit de merge** (deux parents ou plus), sans condition sur ses
  parents ;
- **c'est un parent direct d'un commit de merge** ;
- c'est une racine (aucun parent).

**Pourquoi les parents de merge comptent.** Une version antérieure exigeait
« un merge dont au moins deux parents mènent à des refs distinctes ». Vérifié à
l'exécution : sur un octopus `base → {p1,p2,p3,p4} → octopus` dont seul
`octopus` porte une ref, cette règle ne marquait aucun parent. La compression
remontait alors les quatre chemins jusqu'à `base`, et la déduplication par
couple (ancêtre, descendant) n'en gardait **qu'une seule arête sur quatre** :
le graphe perdait trois branches silencieusement.

Marquer les parents directs d'un merge garantit qu'un point de divergence reste
un nœud, donc qu'un chemin parallèle reste une arête distincte.

**Deux branches peuvent avoir plusieurs merge-bases, et pygit2 ne sait pas les
énumérer.** Vérifié le 2026-09-11 sur pygit2 1.20.0, dépôt à merges croisés :
`git merge-base -a` retourne **deux** bases ; `merge_base`, `merge_base_many` et
`merge_base_octopus` retournent toutes **une seule** — la même. Aucune API
pygit2 n'expose l'équivalent de `--all`.

**L'implémentation n'utilise donc aucune API merge-base.** Les jonctions sont
détectées par **parcours du DAG avec marquage par pointe** :

1. Pour chaque pointe de ref, parcourir ses ancêtres et marquer chaque commit
   atteint du nom de cette pointe.
2. Les commits marqués par au moins deux pointes sont les **ancêtres communs**.
3. Parmi eux, retenir les **maximaux** : ceux dont aucun enfant n'est lui-même
   un ancêtre commun des mêmes pointes. Ce sont les merge-bases.

Prototype validé : sur le dépôt à merges croisés, cette méthode retrouve
exactement les deux bases que `git merge-base -a` rapporte, sans faux positif ni
omission.

Cette approche était présentée plus bas comme une optimisation à envisager pour
les gros dépôts. La contrainte d'API en fait la voie principale — avec
l'avantage d'être linéaire en nombre de commits au lieu de quadratique en
nombre de refs.

**Les merges octopus existent.** Vérifié : `git merge b1 b2 b3` produit un commit
à **quatre parents**. La règle ci-dessus est formulée en « au moins deux
parents » et les couvre, mais toute implémentation supposant `parents[0]` et
`parents[1]` seulement serait fausse. Les parents sont itérés, jamais indexés en
dur.

Cette formulation est l'implémentation v1, pas la définition. Si un benchmark
montre qu'elle ne tient pas, elle est remplaçable sans toucher aux autres
étapes — l'intention ci-dessus reste le contrat.

**Étape 3 — compresser.** Chaque commit significatif devient un `DisplayNode`.
Les segments linéaires entre eux sont remplacés par une arête unique conservant
la **liste ordonnée** des OID sautés (§4.2.1).

**Étape 4 — réduire transitivement.** Supprimer toute arête (A, B) s'il existe
un chemin A→…→C→…→B dans le graphe compressé.

**Les étapes 3 et 4 sont deux transformations distinctes**, et le code les garde
séparées — `compress_linear_segments()` et `reduce_transitive_edges()`. Elles
résolvent des problèmes différents :

```
Compression                     Réduction transitive
A ─ c1 ─ c2 ─ c3 ─ B            A → B  et  A → C → B
        ↓                               ↓
A ──────────────── B            A → C → B
   (skipped = 3)                   (A → B supprimée)
```

Les confondre produirait un code où corriger l'une casse l'autre.

**Étape 5 — rattacher les stashes.** Chaque stash devient un `DisplayNode` relié
par une seule arête à son **premier parent**, en ignorant ses deuxième et
troisième parents. Les stashes ne participent ni à l'étape 2 ni à l'étape 4.

**Complexité.** Le parcours avec marquage est linéaire en nombre de commits
atteignables, et coûte un parcours par pointe de ref. Il remplace l'approche
par paires d'appels merge-base, quadratique en nombre de refs, que la contrainte
d'API rendait de toute façon impossible.

Le point sensible devient la mémoire : le marquage associe à chaque commit
l'ensemble des pointes qui l'atteignent. Sur un dépôt à 100 000 commits et
200 refs, c'est acceptable mais mesurable — d'où la tâche de mesure prévue en
§12.1.

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

### 7.0 Lecture seule par défaut — exigence absolue

**Ouvrir, afficher, naviguer, zoomer, sélectionner, rafraîchir : rien de tout
cela n'écrit dans le dépôt.** Aucune écriture dans `.git`, y compris l'index,
le reflog, les refs ou la configuration.

La **seule** écriture autorisée est celle qu'un utilisateur déclenche
explicitement par une commande du menu contextuel (§7.3), après la
confirmation prévue en §7.5 le cas échéant.

Un outil de visualisation qui altère silencieusement un dépôt de travail est
inacceptable : l'utilisateur doit pouvoir l'ouvrir sur un dépôt professionnel
sans y réfléchir.

**Vérifié, pas supposé.** `tests/test_read_only.py` prend une empreinte de tout
le contenu de `.git` — chemins, tailles, dates de modification à la
nanoseconde — avant et après chaque opération de lecture, y compris l'ouverture
complète de la fenêtre avec sa surveillance active. Toute écriture la fait
changer ; la garde elle-même a été validée en injectant une écriture
volontaire.

Mesuré le 2026-09-25 sur pygit2 1.20 : `repo.status()`, `read_state()`,
`build_graph()`, `commits_for_node()` et la lecture des références n'écrivent
rien. Ce point méritait vérification — selon les versions de libgit2,
`status()` peut rafraîchir le cache de l'index sur disque.

**Écritures implicites à surveiller** lors des évolutions : `repo.index.write()`,
`repo.checkout()`, `repo.set_head()`, `repo.state_cleanup()`, `repo.reset()`,
`repo.stash()`, et toute écriture de configuration. Une garde
d'architecture (`test_ui_never_calls_pygit2_directly_for_operations`) fait
échouer la suite si une opération d'écriture apparaît dans `ui/`.

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

Conformément à D1. Quatorze entrées à plat seraient illisibles : le menu est
donc **hiérarchisé**, les actions les plus fréquentes restant au premier niveau.

```
Checkout / Switch
──────────────────
Create            ▸  Branch here…
                     Tag here…
Integrate         ▸  Merge into current branch…
                     Rebase current branch onto this…
                     Cherry-pick this commit…
Undo              ▸  Reset current branch to this…  (soft / mixed / hard)
                     Revert this commit…
Remote            ▸  Fetch
Branch            ▸  Rename…
                     Delete
──────────────────
Show Log
Copy commit hash
```

Le regroupement est purement présentationnel : il ne change rien à
`core/operations.py`.

**Sur le sous-menu Remote.** Seul **Fetch** est implémenté en v1. Il met à
jour les refs distantes sans toucher à l'arbre de travail ni aux branches
locales : c'est l'opération réseau la moins risquée, et celle qui rend le
graphe utile — elle montre où en sont les autres.

L'authentification passe par l'agent SSH (`KeypairFromAgent`) pour les URL
`git@` et `ssh://`, et par le gestionnaire d'identifiants de Git pour HTTPS.
Vérifié le 2026-09-28 sur un dépôt GitLab d'entreprise : fetch réussi en
1,7 s sans manipuler de clé ni de mot de passe.

**Push et Pull restent hors périmètre.** Pull fusionne dans la branche
courante, donc peut créer des conflits et modifier des fichiers ; Push est
la seule opération dont l'effet sort de la machine. Les deux méritent leur
propre cycle de conception.

**Activation des entrées.** Chaque entrée est activée ou grisée selon le type de
nœud **et** l'état du dépôt (§7.8) :

| Condition | Effet |
|---|---|
| Nœud tag ou jonction | Rename, Delete, Push, Pull grisés |
| Nœud stash | seuls Show Log, Copy hash, et Apply/Drop (v1.1) actifs |
| Nœud = HEAD courant | Checkout, Merge, Rebase grisés (sans objet) |
| Opération en cours (rebase, merge) | toutes les opérations modifiantes grisées, message indiquant l'état |
| Arbre de travail sale | Checkout, Merge, Rebase grisés ou assortis d'un avertissement |

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

**Sur le nom `repository_changed`.** Il couvre volontairement plus que le DAG :
un checkout ne crée aucun commit mais déplace HEAD, donc change le nœud vert du
graphe. Un nom comme `graph_changed` serait plus étroit que la réalité qu'il
décrit. Le champ signifie « l'affichage ne reflète plus le dépôt », ce qui inclut
HEAD, les refs et l'état de §7.8.

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

### 7.8 État du dépôt

Le graphe seul ne suffit pas à décider quelles actions sont possibles. Un second
modèle, indépendant du graphe et bien moins coûteux à calculer, porte l'état
courant :

```python
@dataclass(frozen=True)
class RepositoryState:
    head_oid: Oid | None          # None si dépôt sans commit
    head_branch: str | None       # None si HEAD détaché
    detached: bool
    has_unstaged_changes: bool
    has_staged_changes: bool
    has_conflicts: bool
    operation_in_progress: str | None   # "merge", "rebase", "cherry-pick", …
```

C'est lui que consulte §7.3 pour activer ou griser les entrées de menu, et §7.5
pour décider si une confirmation est nécessaire.

`RepositoryState` est relu après chaque opération et à chaque rafraîchissement
externe (§7.9). Il est bien moins coûteux à calculer que le graphe : quand seul
l'état change (un fichier modifié dans l'éditeur), le graphe n'est pas
reconstruit.

### 7.9 Changements externes

Un dépôt Git n'est jamais modifié uniquement par tortoisePy. Un `git commit`
tapé dans le terminal pendant que la fenêtre est ouverte doit se voir — sans
quoi l'affichage ment, et l'utilisateur agit sur un état périmé.

**Mécanisme :** surveillance du système de fichiers sur le répertoire `.git`,
via `QFileSystemWatcher`.

Chemins surveillés :

| Chemin | Détecte |
|---|---|
| `.git/HEAD` | checkout, changement de branche |
| `.git/refs/` (récursif) | création, déplacement, suppression de refs |
| `.git/packed-refs` | refs compactées |
| `.git/index` | staging |
| `.git/MERGE_HEAD`, `.git/rebase-merge/` | début et fin d'opérations |

**Anti-rebond obligatoire.** Une seule commande Git produit plusieurs événements
de fichier — un `git commit` touche l'index, `HEAD` et une ref. Sans
temporisation, le graphe serait reconstruit trois fois. Un délai de **300 ms**
après le dernier événement avant reconstruction.

**Distinction lecture/reconstruction :** un changement sur `.git/index` seul
relit `RepositoryState` sans reconstruire le graphe. Un changement sur `HEAD`,
`refs/` ou `packed-refs` reconstruit le graphe.

**Réentrance :** la surveillance est suspendue pendant qu'une opération lancée
depuis l'application s'exécute, pour éviter qu'elle ne déclenche son propre
rafraîchissement en plus de celui de §7.6.

Le rafraîchissement préserve la sélection courante lorsque le nœud sélectionné
existe encore après reconstruction.

## 8. Interface en ligne de commande

```
tgraph              # dépôt du dossier courant
tgraph /chemin      # dépôt à ce chemin
tgraph --version
```

Découverte du dépôt via `pygit2.discover_repository()`, qui remonte
l'arborescence comme le fait Git — la commande fonctionne donc depuis n'importe
quel sous-dossier.

**Attention** (vérifié sur pygit2 1.20.0 / libgit2 1.9.6, 2026-09-11) :
`discover_repository()` **retourne `None`** lorsqu'aucun dépôt n'est trouvé.
Elle ne lève pas.

Une version antérieure de cette spec affirmait le contraire. C'était faux, et
non vérifié. Le code teste donc `is None`, tout en conservant un `try/except`
sur `GitError` et `KeyError` en ceinture et bretelles — d'anciennes versions de
pygit2 ont pu lever, et le coût de la double protection est nul.

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
11. **Merges croisés produisant deux merge-bases** — vérifié : `merge-base -a`
    en retourne deux, `merge-base` un seul. Le fixture échoue si
    l'implémentation n'utilise pas la forme « all ».
12. **Octopus merge** — vérifié : `git merge b1 b2 b3` donne un commit à quatre
    parents. Détecte toute indexation en dur sur `parents[0..1]`.
13. **Stashes multiples** (`stash@{0..2}`) à premiers parents différents, dont
    un dont le premier parent n'est atteignable depuis aucune ref
14. **Commit portant simultanément** une branche locale, une branche distante
    et un tag annoté (regroupement combiné)
15. **Deux historiques indépendants** dans un même dépôt (racines multiples)

Cas limites additionnels : dépôt vide sans aucun commit, dépôt sans branche,
dépôt dont toutes les refs pointent sur un unique commit.

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
- Composantes déconnectées (historiques indépendants) : disposées côte à côte,
  ordonnées par date du commit le plus récent de chaque composante,
  décroissante. Sans cette règle, le déterminisme ne serait pas garanti.

**Stabilité locale — objectif v1.1, pas invariant v1.** Il serait souhaitable
qu'ajouter une ref à un commit ne déplace pas tout le graphe. Mais un nœud qui
passe d'une à trois refs change de hauteur, et un layout global propage ce
changement en cascade. Exiger cette propriété dès la v1 ferait passer un temps
disproportionné sur le layout avant d'avoir un graphe qui fonctionne.

La v1 garantit donc « même dépôt → même layout ». La stabilité sous modification
locale est un objectif ultérieur.

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
| Rendu du graphe | QGraphicsView / QGraphicsScene | Zoom, panoramique et sélection fournis nativement. Voir seuils ci-dessous. |
| Tests | pytest, pytest-qt | Standard. |

### 12.1 Seuils de performance

« Des milliers d'éléments » est trop vague pour servir de critère. Les cibles
v1, à mesurer sur les fixtures :

| Grandeur | Cible v1 |
|---|---|
| Commits dans le DAG chargé | 100 000 |
| `DisplayNode` après compression | 500 |
| Arêtes après réduction | 1 000 |
| Construction du graphe (dépôt à 200 refs, 2 000 commits) | **0,66 s mesurés** (2026-09-25, pygit2 1.20.0, Python 3.13), cible < 2 s — tenue |
| Reconstruction après opération | < 500 ms |
| Rendu, zoom, panoramique | fluide, sans seuil chiffré |

La compression est précisément ce qui rend ces chiffres tenables : un dépôt à
100 000 commits et 200 refs produit quelques centaines de `DisplayNode`, pas
100 000. Si un dépôt réel dépasse 500 nœuds affichés, c'est la stratégie de
compression qu'il faudra revoir, pas le moteur de rendu.

**Ce que la première mesure a révélé.** La version initiale lançait un parcours
du DAG **par pointe de ref**. Sur 200 branches d'une chaîne de 2 000 commits,
cela produisait 201 200 visites pour 2 001 commits uniques — une redondance de
facteur 101, et 44 s de construction, vingt-deux fois la cible.

La correction tient en une ligne d'API : `walker.push()` alimente **un seul**
parcours avec toutes les pointes. Un unique parcours coûte 0,24 s. Le marquage
par pointe et le repérage des merges, parents de merges et racines se font
désormais dans cette même passe, au lieu de deux séries de parcours séparées.

Résultat : 0,66 s au lieu de 44 s, à ensemble de commits significatifs
rigoureusement identique (vérifié par comparaison des deux implémentations).
C'est l'intérêt d'avoir mesuré plutôt que supposé : la spec affirmait que
l'approche était « acceptable » sans aucun chiffre.

**Sur la mesure elle-même.** Le premier appel paie le remplissage du cache
d'objets Git, les suivants non : `0,72 / 0,28 / 0,28 s` sur trois exécutions
consécutives. Sous charge, une mesure unique est montée jusqu'à 2,93 s sans que
le code change.

Le test retient donc le **meilleur** de trois exécutions : le minimum mesure le
code, la moyenne mesurerait surtout le bruit de la machine et le cache froid.
Un seuil absolu sur une mesure unique produisait des échecs aléatoires.

### 12.2 Risque connu : empaquetage

`pygit2` embarque libgit2 en binaire natif, avec ses dépendances SSL et SSH.
Combiné à PySide6 et PyInstaller sur macOS, c'est un point de friction connu.

Le risque est accepté et reporté : empaqueter une application qui n'existe pas
encore n'a pas de sens. Mais il est explicite — si la distribution à des tiers
devient un objectif, prévoir un temps de mise au point non négligeable, et le
valider par un essai d'empaquetage **avant** de s'engager sur une date.
