# tortoisePy — Design, phase 21 : checkout d'une branche distante

**Date :** 2026-10-01
**Statut :** brouillon, en attente de relecture

## 1. Problème

Signalé par l'utilisateur. Sur un nœud qui ne porte qu'une branche
**distante**, « Switch / Checkout to revision » est grisé. Il faut d'abord
passer par « Branch from revision… », deux gestes au lieu d'un.

Deux causes, vérifiées dans le code :

- `operations.checkout_branch` ne cherche que dans `repo.branches.local` et
  répond « branch not found » pour une distante ;
- `context_menu._single_node_menu` construit ses cibles depuis
  `_local_branches(node)` : un nœud sans branche locale n'a aucune cible, donc
  l'entrée est désactivée.

## 2. Ce que fait git, mesuré

```
$ git branch -a
* main
  remotes/origin/test-branch

$ git checkout test-branch
Switched to a new branch 'test-branch'
branch 'test-branch' set up to track 'origin/test-branch'.
```

Deux effets, pas un : la branche locale est créée **et** son suivi configuré.
Le suivi n'est pas un détail — sans lui, un `push` ou un `pull` ultérieur ne
sait pas quelle branche distante viser.

**Quand la locale existe déjà, git n'écrase rien** (mesuré) :

```
$ git checkout test-branch
Switched to branch 'test-branch'
Your branch and 'origin/test-branch' have diverged,
and have 1 and 1 different commits each, respectively.
```

Il bascule sur la locale existante et signale la divergence.

## 3. Décisions

| # | Décision | Alternative écartée |
|---|---|---|
| D53 | Le checkout d'une distante **crée la locale du même nom** | Demander le nom — l'utilisateur a nommé le comportement attendu, et git fait pareil |
| D54 | La locale créée **suit** la distante | Ne pas configurer le suivi — casserait `push`/`pull` et l'indicateur d'avance/retard |
| D55 | Si la locale existe, **avertir puis écraser** sur validation | Basculer sans écraser (git natif) — l'utilisateur a demandé l'écrasement |
| D56 | L'avertissement **nomme les commits perdus** et les compte | Un message générique — ne permet pas de décider |
| D57 | **Aucun avertissement** quand la locale est déjà sur le commit distant | Avertir toujours — une alerte qui ne protège rien finit ignorée |

### 3.1 L'écart assumé avec git (D55)

Git **ne** réinitialise **pas** une branche locale existante lors d'un
checkout : c'est un garde-fou délibéré contre la perte accidentelle.
L'utilisateur demande explicitement l'écrasement, après avertissement. C'est
son outil, la décision lui revient, et D56 couvre le risque en nommant ce qui
est en jeu.

L'équivalent git est `git checkout -B <branche> <distante>`.

### 3.2 Ce que l'écrasement détruit, mesuré

```
$ git log --oneline origin/test-branch..test-branch
6ce0350 travail local non pousse

$ git checkout -B test-branch origin/test-branch
$ git log --oneline -1
947b312 feature
```

Le commit local disparaît du graphe. Il reste atteignable par le reflog, mais
**plus aucune ref ne le désigne** : pour qui lit le graphe, il est perdu.
C'est donc une opération destructrice, au même titre que `reset --hard`.

## 4. Comportement

### 4.1 Aucune locale du même nom

Checkout direct, sans confirmation : rien n'est détruit. La locale est créée
depuis le commit de la distante, le suivi est configuré, HEAD bascule.

### 4.2 La locale existe et pointe déjà sur le commit distant (D57)

Bascule directe, sans fenêtre. Il n'y a rien à écraser : la locale et la
distante désignent le même commit.

### 4.3 La locale existe et diverge (D55, D56)

Fenêtre d'avertissement avant tout changement :

```
  Local branch « test-branch » already exists

  Checking out origin/test-branch will reset it to the remote,
  discarding 2 local commits that were never pushed:

      6ce0350  travail local non poussé
      a91f4c2  correction du parseur

  This cannot be undone from the graph.

                              [ Cancel ]  [ Overwrite ]
```

Deux issues seulement (choix de l'utilisateur) : écraser, ou annuler.

Le compte et les sujets viennent de `origin/<branche>..<branche>`. Au-delà de
cinq commits, la liste est tronquée avec « … and N more » : une fenêtre qui
déborde l'écran ne se lit pas.

## 5. Architecture

```
core/
  operations.py   `checkout_branch` accepte une distante      (modifié)
                  `local_commits_ahead(repo, local, remote)`  (nouveau)
ui/
  actions.py      le handler compose la confirmation          (modifié)
  context_menu.py les distantes deviennent des cibles         (modifié)
```

`confirmation_for` reste une fonction **pure**, sans accès au dépôt : elle ne
peut pas compter les commits perdus. Le handler, lui, a `ctx.repository` —
c'est donc lui qui compose la demande de confirmation, puis appelle
`ctx.confirm`. La porte reste `ctx.confirm`, celle qu'emprunte déjà toute
action destructrice.

**pygit2 suffit**, vérifié :

```python
dist = repo.branches.remote.get("origin/test-branch")
locale = repo.branches.local.create("test-branch", repo.get(dist.target))
locale.upstream = dist
repo.checkout(locale)
```

## 6. Ce qui ne change pas

- **La garantie de lecture seule (§7.0)** : aucune écriture sans geste
  explicite de l'utilisateur dans l'UI.
- **Le rendu du graphe** — ni couleurs, ni courbes, ni flèches, ni mise en
  page. Les tests de `graph_items` et `theme` restent verts sans modification.
- **Le checkout d'une branche locale** garde son comportement actuel, y
  compris sa confirmation sur arbre sale.
- **Le checkout détaché sur un commit** (`checkout_commit`) n'est pas touché.

## 7. Tests

- **Checkout d'une distante sans locale** : la locale est créée, HEAD bascule
  dessus, et **le suivi est configuré** (D54) — c'est l'assertion qui
  distingue cette phase d'un simple `branch + checkout`.
- **Le nom de la locale est celui de la distante sans le remote** :
  `origin/test-branch` → `test-branch`.
- **Une distante dont le nom contient des barres obliques**
  (`origin/feature/sous-truc`) donne `feature/sous-truc`, et non `sous-truc` :
  seul le préfixe du remote est retiré.
- **Locale existante et divergente** : sans validation, **rien n'est modifié**
  — ni HEAD, ni la branche. C'est l'assertion centrale.
- **Locale existante et divergente, après validation** : la locale pointe sur
  le commit distant, et HEAD est dessus.
- **Le message nomme les commits perdus** et les compte juste.
- **Locale déjà à jour** : aucune confirmation demandée (D57).
- **Le menu propose les distantes** sur un nœud sans locale.
- **Un nœud portant locale et distante du même nom** ne propose pas deux
  entrées identiques.
- **Arbre sale** : le refus de libgit2 remonte tel quel, et rien n'est
  modifié.

## 8. Hors périmètre

- **Choisir un autre nom** pour la branche locale — l'utilisateur a demandé
  le même nom ; « Branch from revision… » couvre déjà le cas.
- **Basculer sans écraser** quand la locale existe — écarté par l'utilisateur
  (question posée, réponse : écraser ou annuler).
- **Checkout d'une distante en HEAD détachée** — `checkout_commit` le fait
  déjà.
- **Proposer de sauvegarder la branche écrasée** avant de l'écraser.
