# tortoisePy — Design, phase 8 : récupérer les changements distants, conflits compris

**Date :** 2026-09-28
**Statut :** brouillon, en attente de relecture

## 1. Problème

Les phases précédentes permettent de pousser. L'inverse manque : quand la
branche distante a avancé, il faut retourner au terminal.

Le pull était jusqu'ici **hors périmètre**, au motif qu'« il fusionne dans la
branche courante, avec ses conflits ». C'est exact, et c'est pourquoi cette
phase traite les deux ensemble : un pull qui laisse l'utilisateur coincé dans
un conflit que l'application ne sait pas défaire serait pire que pas de pull
du tout.

## 2. Décisions

Arbitrées avec l'utilisateur avant rédaction.

| # | Décision | Alternative écartée |
|---|---|---|
| D11 | Sur divergence, **demander** merge ou rebase | Merge d'office (impose des commits de fusion) ou rebase d'office (réécrit l'historique local sans prévenir) |
| D12 | Conflits : **lister les fichiers et choisir une version** par fichier | Éditeur de fusion intégré (chantier à soi seul) ou renvoi pur et simple au terminal |

## 3. Les trois situations

`repo.merge_analysis(upstream)` les distingue. Vérifié sur pygit2 1.20 :

| Analyse | Situation | Ce que fait Pull |
|---|---|---|
| `UP_TO_DATE` | rien à récupérer | ne fait rien, le dit |
| `FASTFORWARD` | local en retard, rien en local | **avance la ref**, sans commit de fusion |
| `NORMAL` | les deux ont avancé | demande merge ou rebase (D11) |

**Le cas courant est le fast-forward** — celui que l'utilisateur a décrit :
« la remote a des modifs en plus ». Il ne produit aucun commit de fusion et ne
peut pas entrer en conflit.

**Pull commence toujours par un fetch.** Sans lui, l'analyse porte sur une
référence distante périmée et conclurait « à jour » à tort.

## 4. Le bouton Pull

À côté de Push : **barre d'outils et menu contextuel**, cohérent avec la phase
précédente. Libellé anglais.

**Grisé** quand il n'y a rien à récupérer, avec l'infobulle qui dit pourquoi :
pas de remote, HEAD détachée, ou déjà à jour. Comme pour Push, un bouton actif
qui ne fait rien apprend à ignorer l'interface.

**Pull n'est pas confirmé.** Contrairement au push, son effet ne sort pas de la
machine et reste annulable : un fast-forward se défait avec `reset`, une fusion
avec « Abort ». Demander confirmation à chaque récupération serait du bruit.

**Exécution en arrière-plan**, avec la barre de progression : le fetch passe
par le réseau.

## 5. Divergence : merge ou rebase (D11)

Quand l'analyse rend `NORMAL`, une fenêtre propose :

- **Merge** — conserve les deux historiques, crée un commit de fusion. Sûr et
  annulable à tout instant.
- **Rebase** — rejoue les commits locaux par-dessus la branche distante.
  Historique linéaire, mais **réécrit les commits locaux** : la fenêtre le dit
  explicitement, car c'est la seule des deux options qui change des commits
  déjà faits.
- **Annuler** — ne touche à rien.

Le fetch a déjà eu lieu à ce stade : annuler laisse simplement les nouvelles
refs distantes en place, ce qui est sans danger.

## 6. Les conflits (D12)

### 6.1 Ce que l'application montre

Une fenêtre listant les fichiers en conflit. Pour chacun, trois colonnes :
le chemin, la version retenue, et de quoi la changer.

`index.conflicts` fournit pour chaque fichier ses trois versions — ancêtre
commun, la nôtre, la leur. Vérifié.

### 6.2 Résoudre

Pour chaque fichier, deux choix :

- **Keep mine** — garder la version locale ;
- **Take theirs** — prendre la version distante.

Vérifié sur pygit2 1.20 : retirer l'entrée de `index.conflicts`, ajouter
l'`IndexEntry` du côté choisi, écrire l'index, puis récrire le fichier de
travail avec le contenu du blob retenu. Le conflit disparaît et `git status`
est d'accord.

**Un fichier non résolu bloque la validation.** Le bouton « Resolve » reste
grisé tant qu'il en reste un, pour la raison qui vaut depuis la phase 6 :
commiter un conflit produit un commit contenant des marqueurs `<<<<<<<`.

### 6.3 Conclure

Une fois tous les fichiers résolus, « Resolve » crée le commit de fusion à
**deux parents** — `HEAD` et la tête distante — puis appelle `state_cleanup()`.
Vérifié : le dépôt revient à l'état propre et `git log` montre un vrai merge.

`state_cleanup()` est indispensable : la phase 7 a montré qu'un commit créé
sans lui laisse `REVERT_HEAD`/`MERGE_MSG` traîner, et l'interface continue de
griser checkout et merge. Le défaut avait été signalé sur le dépôt
`portfolio`.

### 6.4 Abandonner

Un bouton **« Abort »** rend la main : `abort_operation` existe déjà (phase 5)
et fait exactement cela. Vérifié sur un conflit réel : conflits effacés, `HEAD`
inchangé, fichier revenu à la version locale, état du dépôt propre.

**C'est la garantie qui rend le reste acceptable** : à aucun moment
l'utilisateur ne peut se retrouver coincé.

## 7. Ce qui reste du conflit après un rebase

Un rebase rejoue les commits un par un : un conflit peut surgir à chaque étape.
La même fenêtre sert, avec deux différences :

- le bouton s'appelle **« Continue »** plutôt que « Resolve », car il reste
  peut-être des commits à rejouer ;
- « Abort » restaure la branche dans son état d'avant le rebase.

**Le rebase n'est proposé que sur la branche courante**, jamais sur une autre.

**API vérifiée** : le rebase se démarre avec `repo.rebase_init(branch=…,
upstream=None, onto=…)` — **pas** `init_rebase`, qui n'existe pas. L'objet
rendu s'itère opération par opération ; `reb.commit(...)` valide l'étape
courante, `reb.finish(...)` termine, `reb.abort()` restaure. Un rebase
interrompu se reprend avec `repo.rebase_open()`.

Vérifié sur un rebase réellement conflictuel : le conflit est détecté avec le
fichier nommé, l'état du dépôt passe à `REBASE_MERGE`, et `abort()` le ramène
à l'état propre.

## 8. Architecture

```
core/
  pull.py        analyse, fast-forward, merge, rebase       (nouveau)
  conflicts.py   lister et résoudre les conflits            (nouveau)
ui/
  conflict_window.py   la fenêtre de résolution             (nouveau)
  dialogs.py           choix merge/rebase                   (modifié)
  main_window.py       bouton Pull, tâche de fond           (modifié)
  context_menu.py      entrée « Pull »                      (modifié)
  actions.py           routage                              (modifié)
```

`core/pull.py` et `core/conflicts.py` ne dépendent pas de Qt.

## 9. Tests

- **`core/pull.py`** — les trois analyses ; fast-forward qui avance la ref ;
  merge propre ; merge conflictuel ; rebase propre ; rebase conflictuel ;
  dépôt sans remote ; HEAD détachée ; branche sans upstream.
- **`core/conflicts.py`** — lister les fichiers en conflit ; garder la sienne ;
  prendre la distante ; conclure ; refuser de conclure s'il en reste un ;
  fichier binaire en conflit.
- **`ui/`** — bouton grisé selon l'état ; la fenêtre liste les conflits ;
  « Resolve » grisé tant qu'il reste un fichier ; « Abort » restaure.
- **Lecture seule** — `tests/test_read_only.py` reste vert : analyser ne
  modifie rien ; seul un clic sur Pull écrit.

## 10. Hors périmètre

- **Éditeur de fusion à trois panneaux** — choisir une version couvre la
  majorité des cas (D12).
- **Résolution ligne à ligne** — même raison.
- **Pull sur une autre branche que la courante** — c'est un checkout d'abord.
- **`pull --force`, `rebase --onto`** — jamais.
