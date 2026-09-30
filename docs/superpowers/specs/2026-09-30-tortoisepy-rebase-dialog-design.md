# tortoisePy — Design, phase 19 : dire ce que le rebase va rejouer

**Date :** 2026-09-30
**Statut :** brouillon, en attente de relecture

## 1. Problème

Signalé par l'utilisateur, et c'est un piège d'interface classique.

On clique droit sur une branche, on choisit **Rebase…** — et l'application
rejoue la **branche courante**, pas celle qu'on a cliquée. Rien dans le geste
ne le laisse deviner.

Le libellé actuel dit bien « Replay develop on top of: », mais l'information
est noyée dans une phrase, et **la branche rejouée n'est pas modifiable**.

L'utilisateur demande deux champs côte à côte : **ce qu'on rebase** (la
courante par défaut, changeable) et **sur quoi**.

## 2. Ce que la phase révise

La phase 9 avait écarté « rebaser une branche autre que la courante » en
écrivant : *« c'est un checkout d'abord »*. L'utilisateur demande le
contraire ; c'est son projet, et la mesure montre que c'est faisable
proprement.

| # | Décision | Alternative écartée |
|---|---|---|
| D44 | Deux champs : **branche rejouée** et **cible** | Un seul champ — c'est l'état actuel, source de la confusion |
| D45 | La branche rejouée est **modifiable**, courante par défaut | La figer — ne répondrait qu'à la moitié du besoin |
| D46 | La fenêtre **prévient** qu'on changera de branche | Revenir sur la branche de départ — s'écarte de git, et ajoute une écriture |

## 3. Ce que la mesure a établi

**Rebaser une branche sur laquelle on n'est pas fonctionne**, et
`rebase_init(branch=…, onto=…)` l'exprime directement :

```
branche courante : main
rebase feature sur main -> 1 commit rejoué
branche après : feature          <- on a basculé
feature : ['cote feature', 'cote main', 'base']
```

**Git fait exactement pareil** — vérifié :

```
avant : main
git rebase main feature
après : feature
```

Notre comportement sera donc conforme à git, et D46 se contente de le dire
plutôt que de le contredire.

**Un arbre sale est refusé proprement** :

```
arbre sale ? True
rebase_init LEVE : GitError - unstaged changes exist in workdir
```

libgit2 protège donc déjà le travail non commité — aucune perte possible par
ce chemin.

## 4. La fenêtre

```
  Rebase

  Replay:  [ feature            ▾ ]
  Onto:    [ main               ▾ ]

  ⚠ You will end up on « feature » after the rebase.

                          [ Cancel ]  [ Rebase ]
```

**« Replay »** — la branche dont les commits seront rejoués. Par défaut la
branche courante ; la liste propose les branches **locales** uniquement, puisque
rebaser une distante n'a pas de sens.

**« Onto »** — la cible, comme aujourd'hui : branches locales **et** distantes
(D14, phase 9).

**L'avertissement n'apparaît que si la branche rejouée n'est pas la courante**
(D46). Le montrer toujours le rendrait invisible.

Les deux champs gardent l'autocomplétion de la phase 9, et **refusent un nom
inconnu** : laisser passer du texte libre produirait une erreur de libgit2
incompréhensible.

## 5. Ce qui ne change pas

- **La résolution des conflits** — même fenêtre, mêmes libellés inversés
  (`ours` = cible, `theirs` = commit rejoué), même reprise.
- **Rebaser sur soi-même reste refusé.**
- **Le cas d'un rebase déjà en cours** garde son message actuel.
- **L'arbre sale** : on s'appuie sur le refus de libgit2 plutôt que de le
  réimplémenter.

## 6. Architecture

```
core/
  rebase.py      `start_rebase(repo, onto, branch=None)`   (modifié)
ui/
  dialogs.py     une fenêtre à deux champs                  (modifié)
  main_window.py l'appel                                    (modifié)
```

`branch=None` conserve le comportement actuel — la branche courante — pour que
les appels existants et leurs tests restent valides.

## 7. Tests

- **Rebaser une autre branche que la courante** fonctionne, et **la branche
  courante devient celle qui a été rejouée** (D46). C'est le test central.
- **Par défaut, c'est toujours la courante** qui est rejouée : les tests de la
  phase 9 restent verts sans modification.
- **La fenêtre pré-remplit** la branche courante, et propose les locales.
- **L'avertissement** apparaît pour une autre branche, **pas** pour la courante.
- **Un nom inconnu** dans l'un ou l'autre champ est refusé.
- **Rebaser une branche sur elle-même** est refusé.
- **Un arbre sale** — le message de libgit2 remonte tel quel, et **rien n'est
  modifié** : c'est l'assertion qui compte.
- **HEAD détachée** — refusé, comme aujourd'hui.

## 8. Hors périmètre

- **`rebase --onto` à trois arguments** — déjà écarté en phase 9 : usage rare
  et facile à se tromper.
- **Le rebase interactif** — une application à soi seule.
- **Revenir automatiquement sur la branche de départ** — écarté par D46 : git
  ne le fait pas, et ce serait une écriture de plus dans le dépôt.
- **Rebaser une branche distante** — elle n'est pas à nous ; la cible peut en
  être une, la branche rejouée non.
