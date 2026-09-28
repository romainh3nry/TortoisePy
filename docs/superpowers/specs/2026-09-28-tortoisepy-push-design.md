# tortoisePy — Design, phase 7 : pousser depuis le graphe, et voir ce qui ne l'est pas

**Date :** 2026-09-28
**Statut :** brouillon, en attente de relecture

## 1. Problème

La phase 6 a fermé le cycle commit. À l'usage, quatre manques apparaissent :

1. **La fenêtre de commit reste ouverte** après un commit réussi. Il faut la
   fermer à la main pour revenir au graphe.
2. **Rien ne dit si ça a marché.** Un commit réussi est silencieux ; seul un
   échec ouvre un dialogue.
3. **On ne peut pas pousser depuis le graphe.** Si on a commité sans pousser,
   il faut rouvrir la fenêtre de commit — mais elle ne sert qu'à commiter, donc
   en pratique il faut retourner au terminal.
4. **Rien ne distingue un commit poussé d'un commit local.** On ne sait pas ce
   qu'on risque de perdre, ni ce qu'il reste à envoyer.

## 2. Décisions

Arbitrées avec l'utilisateur avant rédaction.

| # | Décision | Alternative écartée |
|---|---|---|
| D9 | Les commits non poussés sont marqués **dans le graphe ET dans le panneau** | Panneau seul — moins visible d'un coup d'œil |
| D10 | Push accessible depuis **la barre d'outils ET le menu contextuel** | Menu contextuel seul — moins découvrable |

## 3. Fermer la fenêtre et revenir au graphe

Après un commit **réussi** — simple ou suivi d'un push — la fenêtre de commit
se ferme et le graphe reprend la main, rafraîchi.

**Après un échec, la fenêtre reste ouverte.** Le message saisi est conservé :
le fermer ferait perdre le travail de rédaction, et l'utilisateur a
généralement une correction à faire sur place.

Cas intermédiaire, déjà traité en §8 de la phase 6 : **le commit réussit mais
le push échoue.** La fenêtre se ferme quand même, puisque le commit est acquis.
L'échec du push est signalé séparément, et la distinction visuelle de §5 montre
alors le commit comme non poussé — ce qui est exact.

## 4. Dire si ça a marché

Le résultat s'affiche dans la **barre d'état de la fenêtre principale**,
là où le fetch affiche déjà les siens (§7.9 phase 5). Cohérence : c'est le même
genre d'information, au même endroit.

| Situation | Message |
|---|---|
| Commit réussi | `Committed 2 files — a1b2c3d4` |
| Commit + push réussis | `Committed 2 files — a1b2c3d4, pushed to origin` |
| Commit réussi, push échoué | `Committed 2 files — a1b2c3d4 (push failed)` + dialogue détaillant l'erreur |
| Commit échoué | La fenêtre reste ouverte, dialogue d'erreur (inchangé) |

**Un échec de push garde son dialogue** en plus du message : c'est une action
dont l'effet sort de la machine, son échec ne doit pas se noyer dans une barre
d'état qu'on peut ne pas regarder.

## 5. Distinguer les commits poussés

### 5.1 Ce que « poussé » veut dire

**Corrigé le 2026-09-28, après un test sur le dépôt réel `xpc`.** La première
définition — « accessible depuis l'upstream de la branche courante » — était
fausse, et le dépôt de l'utilisateur l'a montré immédiatement : les 1644
commits ressortaient comme non poussés alors qu'aucun ne l'était.

Un commit est **poussé** s'il est accessible depuis **n'importe quelle ref
distante**. C'est exactement la réponse de `git log --not --remotes`.

Pourquoi l'ancienne règle échouait, sur `xpc` :

- la branche courante `mcp` n'a **pas d'upstream** configuré ;
- l'ancienne règle en concluait « jamais poussée, donc tout est à publier » ;
- or tout son historique est sur le serveur, sous d'autres branches ;
- et les nœuds des autres branches héritaient de la marque — `lightweight-calls`
  apparaissait non poussée alors que son tip local **était identique** à son
  tip distant.

Après correction : 0 commit non poussé sur `mcp`, ce que `git log --not
--remotes` confirme. Coût mesuré : 23 ms sur `xpc` (79 refs distantes,
~1600 commits).

La marque du graphe couvre **toutes les branches locales**, puisque le graphe
affiche un nœud pour chacune. Le **bouton Push**, lui, ne compte que la branche
courante : c'est elle seule qu'il enverrait, et l'activer pour des commits
qu'il ne pousserait pas serait mentir.

Cas particuliers :

- **Pas d'upstream configuré** : ce n'est **pas** un signe que la branche n'a
  jamais été poussée. Ses commits peuvent être sur le serveur sous une autre
  ref — c'est le cas de `mcp` sur `xpc`. Seule l'accessibilité depuis une ref
  distante fait foi.
- **Dépôt sans remote** : la distinction n'a pas de sens. Rien n'est marqué,
  plutôt que de tout marquer en rouge.
- **Upstream en retard** (on n'a pas fetché) : l'information reflète ce que
  l'on sait localement. C'est la même limite que `git status`, et la même
  convention.

### 5.2 Dans le panneau des commits

Une marque `↑` en tête de ligne sur les commits non poussés, et le compte dans
le titre : `main — 2 commits non poussés sur 27`.

Le panneau distingue déjà les commits « propres à la branche » par un cadre
(phase 5). Les deux marques coexistent sans se gêner : l'une dit *d'où vient*
le commit, l'autre *où il est arrivé*.

### 5.3 Dans le graphe

Un nœud dont la ref porte des commits non poussés reçoit une **pastille** dans
son coin supérieur droit.

**Contrainte absolue :** l'utilisateur a validé le rendu actuel et posé la
règle « il ne faut pas dégrader le rendu actuel ». La pastille est donc un
**ajout** :

- aucune couleur existante n'est modifiée ;
- aucune forme, taille ni position de nœud ne change ;
- la pastille est dessinée *par-dessus*, après le rectangle, sans déplacer les
  étiquettes.

Un nœud sans commit à pousser est dessiné **exactement** comme aujourd'hui.

## 6. Le bouton Push

### 6.1 Où

- **Barre d'outils** : un bouton « Push », à côté de « Commit… ».
- **Menu contextuel** : une entrée « Push », auprès de Fetch, Checkout et
  Merge — libellé en anglais, comme le reste du menu (demande utilisateur).

### 6.2 Quand il est actif

Le bouton est **grisé** quand il n'y a rien à pousser : pas de remote, HEAD
détachée, ou aucun commit en avance sur l'upstream. Un bouton actif qui ne fait
rien apprend à l'utilisateur à ignorer l'interface.

Son infobulle dit pourquoi il est grisé.

### 6.3 Comment il s'exécute

Push part sur le réseau : il s'exécute **en arrière-plan**, avec la barre de
progression, comme le fetch (§6.3 phase 6). Un push synchrone gèlerait
l'interface — mesuré à 1,6 s pour un fetch qui ne ramenait rien.

**Il est confirmé**, comme dans la fenêtre de commit : c'est la seule opération
dont l'effet sort de la machine et que l'utilisateur ne peut pas défaire seul.

**Jamais de push forcé**, ici comme ailleurs.

## 7. Architecture

```
core/
  push_state.py   unpushed_oids(), push_status()        (nouveau, lecture seule)
ui/
  commit_window.py   ferme après succès, émet le résultat   (modifié)
  main_window.py     barre d'état, bouton Push, tâche de fond (modifié)
  commit_panel.py    marque ↑ et compte dans le titre         (modifié)
  graph_items.py     pastille sur les nœuds concernés         (modifié, ajout seul)
  theme.py           couleur de la pastille                   (ajout seul)
  context_menu.py    entrée « Push »                          (modifié)
  actions.py         routage de l'action                      (modifié)
```

`core/push_state.py` ne dépend pas de Qt et n'écrit rien : il répond « quels
commits ne sont pas encore sur le serveur ».

## 8. Tests

- **`core/push_state.py`** — branche avec upstream et commits en avance ;
  branche sans upstream ; dépôt sans remote ; HEAD détachée ; tout déjà poussé.
- **Fermeture** — la fenêtre se ferme après un commit réussi, **reste ouverte**
  après un échec, et se ferme quand le commit réussit mais le push échoue.
- **Barre d'état** — les quatre messages de §4.
- **Bouton Push** — grisé sans remote, sans commit en avance, sur HEAD
  détachée ; actif sinon.
- **Rendu** — un nœud sans commit à pousser est dessiné comme avant
  (non-régression du rendu validé) ; un nœud concerné porte la pastille.
- **Lecture seule** — `tests/test_read_only.py` reste vert : calculer l'état
  de poussée n'écrit rien.

## 9. Hors périmètre

- **Pull** — il fusionne, avec ses conflits.
- **Push forcé** — jamais.
- **Push d'une autre branche que la courante** — le menu agit sur la branche
  du nœud cliqué uniquement si c'est la branche courante ; sinon l'entrée est
  grisée. Changer de branche pour pousser est un checkout, qui existe déjà.
