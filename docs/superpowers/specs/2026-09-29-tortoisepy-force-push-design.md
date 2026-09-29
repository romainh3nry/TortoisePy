# tortoisePy — Design, phase 10 : pousser après un rebase

**Date :** 2026-09-29
**Statut :** brouillon, en attente de relecture

## 1. Problème

La phase 9 a livré le rebase. Elle l'a livré inutilisable.

Rebaser réécrit les commits : leurs identifiants changent. La branche locale
et la branche distante n'ont plus d'ancêtre commun au bon endroit, et le
serveur refuse la mise à jour. Vérifié, immédiatement après un rebase réussi :

```
rebase : True | Rebased 1 commit onto main
push NORMAL apres rebase : False | cannot push non-fastforwardable reference
```

Qui rebase une branche déjà poussée doit donc retourner au terminal — ce que
cette application existe précisément pour éviter. **La phase 9 a créé cette
impasse**, et cette phase la referme.

## 2. La décision que cette phase révise

La spec de la phase 7 excluait le push forcé en toutes lettres :

> **Push forcé** — jamais. (§9)
> **Jamais de push forcé**, ici comme ailleurs. (§6.2)

Le code le rappelle dans `push_branch` : « `--force` réécrit l'historique
d'autrui ».

**Cette raison était juste, et elle reste juste.** Ce qui change, c'est qu'il
existe une forme de push forcé à laquelle elle ne s'applique pas.

| # | Décision | Alternative écartée |
|---|---|---|
| D15 | Le push forcé existe, **en `--force-with-lease` uniquement** | `--force` simple — écrase le travail d'autrui sans avertir |
| D16 | Entrée de menu **toujours visible**, avec confirmation | Ne l'afficher que si le push normal échouerait — apparition/disparition déroutante, et tributaire d'un fetch récent |

**D15 est ce qui rend la révision acceptable.** `--force` écrase
inconditionnellement, y compris des commits qu'on n'a jamais vus.
`--force-with-lease` n'écrase que si la branche distante est encore là où
nous la croyons : il réécrit **son propre** historique, jamais celui d'un
autre. L'interdit de la phase 7 visait le second risque ; il ne vise pas le
premier.

## 3. Le mécanisme, vérifié

**C'est `git` qui arbitre le bail, pas nous.** Le push forcé est délégué au
`git` du système :

```
git push --force-with-lease <remote> <branche>
```

### 3.1 Pourquoi pas pygit2

pygit2 1.20 ne sait pas exprimer un bail. Son seul levier de forçage est le
refspec `+`, qui **force sans condition** : aucune valeur attendue n'est
transmise au serveur.

Le vrai `--force-with-lease` envoie au serveur la valeur qu'on **attend** pour
la ref ; c'est le serveur qui refuse si elle a bougé. La différence n'est pas
théorique :

```
git push --force-with-lease -> ! [rejected] main -> main (stale info)
historique serveur : travail du collegue / base   (les deux survivent)
```

### 3.2 La première conception était fausse — le défaut de cette phase

La version d'origine de cette spec vérifiait le bail **côté client**
(`connect()` + `list_heads()`), puis poussait un refspec `+`. Une revue l'a
mise en défaut, et c'est reproduit :

```
bail verifie : (True, None)
le collegue a pousse pendant la fenetre
push force : True | Pushed main to origin
historique serveur : ['base reecrit']      <- le commit du collegue DETRUIT
```

Entre le contrôle et l'envoi subsistait une fenêtre de course, et le `+`
inconditionnel y détruisait le travail d'un tiers **alors que le bail venait
d'être jugé valide**. Autrement dit : c'était `--force` déguisé.

*Pourquoi cela condamnait la conception entière :* la garantie du bail est la
**seule** justification de D15. Sans elle, l'interdit de la phase 7 n'avait
aucune raison d'être levé.

Vérifié après correction, sur la course la plus défavorable — le collègue
pousse juste avant notre `git push` :

```
push force : False | "'origin/main' has moved since your last fetch — ..."
historique serveur : ['travail du collegue', 'base']
```

### 3.3 Appeler `git` en sous-processus

Le précédent existe : `core/credentials.py` appelle déjà `git credential`.
`GIT_TERMINAL_PROMPT=0` est reprise pour la même raison — sans elle, `git`
poserait une question sur un terminal absent et l'appel resterait suspendu.

**Conséquence assumée :** un sous-processus ne rapporte pas la progression
objet par objet. La barre reste donc **indéterminée** pendant un push forcé,
au lieu d'afficher une fausse précision.

**Conséquence vérifiée sur l'authentification :** `git` ne parle pas comme
libgit2. Sans identifiant en cache il répond « could not read Username for
… : terminal prompts disabled », qui ne contient aucun des marqueurs de
libgit2. Sans les ajouter, la fenêtre d'identifiants ne s'ouvrait pas et le
premier push forcé sur un dépôt HTTPS était une impasse (trouvé en revue
finale, corrigé).

## 4. Le geste

Clic droit sur la branche courante → **Push (force with lease)…** →
confirmation nommant branche et remote → le push part en arrière-plan, comme
le push normal.

L'entrée est **toujours visible** (D16), active dès que la branche courante a
un remote. Elle est grisée dans les mêmes cas que « Push » : HEAD détachée,
pas de remote, opération en cours.

**La confirmation nomme ce qui va être réécrit** — branche, remote, et le fait
que l'historique distant sera remplacé. C'est la seule opération de cette
application qui détruit un état publié.

## 5. Ce que l'utilisateur voit en cas de refus

Le bail rompu n'est pas une erreur technique : c'est une information. Le
message dit ce qui s'est passé et ce qu'il faut faire :

> `origin/feature` a avancé depuis votre dernier fetch — quelqu'un d'autre a
> poussé. Récupérez (Fetch) avant de forcer.

Pas de contournement proposé dans l'interface : forcer par-dessus le travail
d'un autre reste hors de portée, exprès.

## 6. Architecture

```
core/
  operations.py   push_branch(force_with_lease=False)   (modifié)
ui/
  context_menu.py   entrée « Push (force with lease)… »  (modifié)
  actions.py        routage                              (modifié)
  main_window.py    lancement en arrière-plan            (modifié)
```

`push_branch` gagne un paramètre plutôt qu'une fonction jumelle : tout ce qui
l'entoure — remote par défaut, refus des remotes `pushurl`-only (segfault
libgit2 vérifié en phase 7), identifiants, détection des rejets serveur — est
commun, et le dupliquer les exposerait à diverger.

**Aucun refspec `+` n'existe dans le code.** Le chemin pygit2 ne force jamais,
par construction et non par condition : le forçage sort du processus, confié à
`git`. C'est plus fort que ce que visait la conception d'origine.

## 7. Tests

- **Le bail tient** → le push passe, la branche distante porte le commit réécrit.
- **Le bail est rompu** → refus **sans rien envoyer**, et le commit du tiers
  est toujours sur le serveur (c'est l'assertion qui compte).
- **Après un rebase réel** → le push forcé aboutit là où le push normal
  échouait avec `non-fastforwardable`.
- **Pas d'upstream** → message clair, pas de plantage.
- **`--force` n'existe nulle part** : un test vérifie que le push normal
  n'émet aucun refspec `+`, et aucun chemin du code n'en produit.
- **Refuser n'écrit rien** — sur un bail rompu, `git` rejette côté serveur et
  le dépôt local est inchangé.
- **Le push normal reste inchangé** — les tests de la phase 7 restent verts.

## 8. Hors périmètre

- **`--force` inconditionnel** — jamais, et c'est le cœur de D15.
- **Forcer une autre branche que la courante** — c'est un checkout d'abord.
- **Forcer plusieurs branches d'un coup** — un geste destructeur se fait une
  branche à la fois.
- **Rattraper un bail rompu depuis l'interface** (fetch + rebase + push
  enchaînés) — chaque étape existe déjà séparément, et les enchaîner
  masquerait ce qu'on écrase.
