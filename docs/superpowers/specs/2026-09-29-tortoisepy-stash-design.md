# tortoisePy — Design, phase 11 : mettre de côté et reprendre (stash)

**Date :** 2026-09-29
**Statut :** brouillon, en attente de relecture

## 1. Problème

Les stashes sont **déjà dessinés** dans le graphe : `core/stashes.py` en fait
un nœud gris rattaché à son premier parent (§6.1 étape 5). On les voit, on ne
peut rien en faire.

Or ils servent précisément aux gestes que cette application rend maintenant
possibles. Changer de branche avec un arbre sale est refusé ; rebaser aussi.
La réponse de Git est « mets ton travail de côté » — et il fallait un terminal
pour le dire.

## 2. Décisions

Arbitrées avec l'utilisateur avant rédaction.

| # | Décision | Alternative écartée |
|---|---|---|
| D17 | Les fichiers **non suivis** partent dans le stash | `git stash` nu — laisse les fichiers neufs derrière |
| D18 | Trois opérations : **Apply**, **Pop**, **Drop** | Apply et Pop seuls — les stashes s'accumuleraient sans nettoyage possible |
| D19 | Un stash est désigné par son **OID**, jamais par son index | Agir par index — appliquerait le mauvais stash (§3.1) |

**D17 est un écart assumé avec `git stash` nu.** Vérifié : sans
`include_untracked`, un dossier ne contenant que des fichiers neufs répond
« cannot stash changes - there is nothing to stash ». L'utilisateur aurait du
travail en cours et un refus. C'est aussi ce que fait TortoiseGit.

## 3. Le piège de cette phase : les index glissent

Vérifié sur pygit2 1.20 :

```
apres 3 stash            apres stash_drop(0)
  stash@{0} travail 3      stash@{0} travail 2
  stash@{1} travail 2      stash@{1} travail 1
  stash@{2} travail 1
```

Le plus récent est en `0`, et **tout se décale** dès qu'un stash disparaît.

### 3.1 Pourquoi cela compte ici

L'interface agit sur le nœud que l'utilisateur a cliqué. Entre l'affichage du
graphe et le clic, la liste peut avoir changé — un autre processus, un
terminal ouvert à côté, ou simplement un `pop` fait juste avant. Passer
l'index affiché à `stash_pop` appliquerait alors **un autre stash que celui
montré**, sans rien signaler.

**Donc (D19) :** le nœud porte l'OID du commit de stash ; au moment d'agir, on
relit `listall_stashes()` et on cherche l'index de cet OID. S'il n'y est plus,
on refuse avec un message clair plutôt que d'agir au hasard.

## 4. Le geste

**Créer** : clic droit sur la branche courante → **Stash changes…** → une
fenêtre demande un message → le travail part de côté et l'arbre redevient
propre.

L'entrée est grisée si l'arbre est propre. Vérifié : `repo.stash()` lève
`NotFoundError('cannot stash changes - there is nothing to stash.')`, et
proposer une action qui échouera toujours n'apprend rien.

**Reprendre** : clic droit sur un nœud de stash →

- **Apply** — restaure le contenu, **garde** le stash ;
- **Pop** — restaure, **puis** supprime le stash ;
- **Drop** — supprime **sans** restaurer.

Seul **Drop** est confirmé : c'est le seul qui détruit du travail sans le
rendre.

## 5. Les conflits : rien à résoudre

**C'est la différence avec le rebase et le pull, et elle simplifie tout.**

Vérifié : quand le contenu du stash ne peut pas s'appliquer, libgit2 **refuse
avant de toucher à quoi que ce soit** :

```
stash_apply avec modification concurrente
  LEVE : GitError - 1 conflict prevents checkout
  etat depot : 0          <- aucun etat conflictuel
  conflits ? : False
  stash encore present ? 1
  contenu f.txt : 'a\nAUTRE\n'   <- le travail local intact
```

Il n'y a donc **pas de fenêtre de conflits** dans cette phase. Le message dit
ce qui bloque, et l'utilisateur choisit : commiter son travail courant, ou le
mettre de côté à son tour.

**Un `pop` qui échoue ne perd pas le stash** — vérifié, il reste dans la
liste. C'est ce qui rend `Pop` sans danger.

**Sans chevauchement, l'application passe** : un stash touchant `f.txt`
s'applique alors que `g.txt` est modifié localement (vérifié).

## 6. Ce que `Apply` laisse derrière

`stash_apply` **ne supprime pas** le stash (vérifié). Conséquence à connaître :
appliquer deux fois de suite échoue la seconde, puisque le contenu est déjà là.
Ce n'est pas un défaut — c'est la raison d'être d'`Apply` face à `Pop` : garder
le stash pour l'appliquer ailleurs, sur une autre branche par exemple.

## 7. Architecture

```
core/
  stash_ops.py    créer, appliquer, retirer, jeter        (nouveau)
  stashes.py      collecte pour le graphe                 (existant, intact)
ui/
  context_menu.py entrées sur la branche et sur un stash  (modifié)
  actions.py      routage                                 (modifié)
  main_window.py  lancement, message de stash             (modifié)
```

Un module neuf plutôt que d'alourdir `operations.py`, qui approche 700 lignes.
`stashes.py` n'est pas touché : il sert le graphe, pas les opérations.

`core/stash_ops.py` ne dépend pas de Qt.

## 8. Tests

- **Créer** — arbre sale ; arbre propre (refus clair) ; **fichier non suivi
  seul**, qui est le cas que D17 existe pour couvrir.
- **Le piège des index** — un test crée trois stashes, en retire un, et vérifie
  qu'agir sur un OID atteint bien le bon stash et non son voisin. C'est le
  test central de cette phase.
- **OID disparu** — refus explicite, aucune action au hasard.
- **Apply** — restaure et **conserve** le stash.
- **Pop** — restaure et le retire ; en cas d'échec, **le stash survit**.
- **Drop** — retire sans restaurer, et le travail local reste intact.
- **Conflit** — refus, dépôt inchangé, `state()` toujours à 0.
- **Lecture seule (§7.0)** — lister les stashes n'écrit rien ;
  `tests/test_read_only.py` reste vert.

## 9. Hors périmètre

- **`stash branch`** — créer une branche depuis un stash ; utile mais rare, et
  c'est un autre geste.
- **Stash partiel** (`paths=`) — choisir les fichiers à mettre de côté demande
  une fenêtre de sélection, comme le commit partiel.
- **`--keep-index`** — subtil, et mal comprise cette option surprend.
- **Résolution de conflits** — sans objet : l'application refuse avant de
  toucher au dépôt (§5).
