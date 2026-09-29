# tortoisePy — Design, phase 9 : rebaser sur une branche choisie

**Date :** 2026-09-29
**Statut :** brouillon, en attente de relecture

## 1. Problème

Le rebase n'existe aujourd'hui que dans le pull, et seulement vers la branche
de suivi. Rebaser sa branche courante sur une autre — le geste quotidien
`git rebase main` — oblige à retourner au terminal.

Et lorsqu'un conflit survient, la phase 8 avait tranché : **on annule tout**.
La raison était bonne — `abort_operation`, la sortie de secours générique, ne
sait pas défaire un rebase et laisserait la HEAD détachée. Mais la conséquence
était qu'aucun conflit de rebase n'était résoluble depuis l'application.

Cette phase lève les deux limites.

## 2. Décisions

Arbitrées avec l'utilisateur avant rédaction.

| # | Décision | Alternative écartée |
|---|---|---|
| D13 | Les conflits de rebase **se résolvent** dans la fenêtre, avec une vraie récupération | Annuler le rebase (phase 8) — sûr, mais renvoie au terminal |
| D14 | L'autocomplétion propose branches **locales et distantes** | Locales seules (impose un checkout avant de rebaser sur `origin/main`) |

**D13 révise le Ruling 3 de la phase 8.** Ce qui manquait alors est désormais
vérifié : `rebase_open()` reprend un rebase interrompu **depuis un autre
processus**, et `Rebase.abort()` restaure l'état, la branche et les commits.
La sortie de secours existe donc réellement.

## 3. Le geste

Clic droit sur une branche → **Rebase…** → une fenêtre demande la branche
cible, avec autocomplétion → le rebase s'exécute.

**Rebase réécrit les commits locaux.** La fenêtre le dit, et nomme les deux
branches concernées : c'est la seule opération de cette application qui
modifie des commits déjà faits.

**Seule la branche courante est rebasée.** Rebaser une autre branche
demanderait un checkout, qui existe déjà. L'entrée est grisée ailleurs.

## 4. La fenêtre de choix

Un champ de saisie avec autocomplétion, et la liste des branches proposées
dès l'ouverture.

**Branches locales et distantes** (D14) : `main`, `develop`,
`origin/main`… Rebaser sur une distante fraîchement récupérée est courant, et
l'imposer via un checkout préalable serait une gêne inutile.

**La branche courante est exclue** : se rebaser sur soi-même n'a pas de sens.

**Le bouton reste inactif tant que la saisie ne correspond à aucune
référence connue.** Accepter un nom libre produirait une erreur de libgit2
que l'utilisateur ne saurait pas interpréter.

## 5. Les conflits (D13)

### 5.1 La même fenêtre que le pull

`ConflictWindow` sert telle quelle : liste des fichiers, choix par fichier,
et l'aperçu coloré. Ce qui change, ce sont **les libellés** et **ce que font
les boutons**.

### 5.2 « Ours » et « theirs » sont inversés — le piège de cette phase

Vérifié sur pygit2 1.20 : pendant un rebase, `ours` désigne la branche
**cible** et `theirs` le commit **rejoué**. C'est l'inverse du merge.

```
rebase de feature sur main, conflit sur f.txt
  ours   : 'a / MAIN'        <- la branche cible
  theirs : 'a / FEATURE'     <- mon commit rejoué
```

Conserver les libellés « Keep mine » / « Take theirs » ferait donc **perdre
son propre travail à qui croit le garder**. En rebase, la fenêtre dit :

- **« Keep <cible> »** — la version de la branche sur laquelle on rebase ;
- **« Keep my commit »** — la version du commit en cours de rejeu.

Les noms réels sont affichés, pas « ours » et « theirs ».

### 5.3 Continuer, pas conclure

Un rebase rejoue les commits un par un : résoudre un conflit ne termine pas
l'opération. Le bouton s'appelle donc **« Continue »** et non « Resolve », et
il enchaîne sur le commit suivant. Un nouveau conflit rouvre la fenêtre.

Quand il ne reste rien à rejouer, `finish()` termine et la fenêtre se ferme.

**Un commit devenu vide est sauté**, comme le fait `git rebase` : si la
résolution retient la version de la cible, le commit rejoué n'apporte plus
rien. Vérifié — `Rebase.commit()` rend `None` dans ce cas, et ce n'est pas
une erreur.

### 5.4 Abandonner

**« Abort »** appelle `Rebase.abort()` — pas `abort_operation`, qui ne sait
pas défaire un rebase et laisserait la HEAD détachée (défaut trouvé en
phase 8).

Vérifié depuis un autre processus, comme le fait la fenêtre :

```
etat : 0 | HEAD detachee ? False | HEAD restauree ? True
branche : ## feature | mon commit intact ? True
```

C'est cette garantie qui rend D13 acceptable : **on ne peut pas rester
coincé**.

## 6. Reprendre un rebase interrompu

Fermer la fenêtre pendant un conflit laisse le rebase en cours — comme au
terminal. À la réouverture, l'application le détecte et propose de reprendre :
la fenêtre se rouvre sur les conflits restants.

`rebase_open()` le permet, y compris depuis un autre processus (vérifié). Le
défaut de la phase 8 — un état que rien ne savait récupérer — est ainsi
refermé.

## 7. Architecture

```
core/
  rebase.py      démarrer, continuer, abandonner, décrire l'état  (nouveau)
  refs.py        lister les cibles possibles                      (existant)
ui/
  dialogs.py         champ avec autocomplétion                    (modifié)
  conflict_window.py libellés et boutons selon l'opération        (modifié)
  context_menu.py    entrée « Rebase… »                           (modifié)
  actions.py         routage                                      (modifié)
  main_window.py     lancement, reprise                           (modifié)
```

`core/rebase.py` ne dépend pas de Qt.

## 8. Tests

- **`core/rebase.py`** — rebase sans conflit ; avec conflit ; reprise après
  résolution ; abandon qui restaure ; commit devenu vide ; cible inconnue ;
  HEAD détachée ; branche déjà à jour.
- **L'inversion ours/theirs** — un test vérifie que « garder mon commit »
  retient bien la version rejouée, et non celle de la cible. C'est le piège
  principal de cette phase.
- **`ui/`** — l'autocomplétion propose locales et distantes, exclut la
  courante ; le bouton reste inactif sur une saisie inconnue ; la fenêtre de
  conflits affiche « Continue » en rebase et « Resolve » en merge.
- **Lecture seule** — `tests/test_read_only.py` reste vert : lister les
  branches n'écrit rien.

## 9. Hors périmètre

- **Rebase interactif** (`-i`) — réordonner, fusionner ou réécrire des
  commits est une application à soi seule.
- **`rebase --onto`** — trois arguments, un usage rare et facile à se tromper.
- **Rebaser une branche autre que la courante** — c'est un checkout d'abord.
- **Résolution ligne à ligne** — comme pour le merge, on choisit un camp par
  fichier (D12, phase 8).
