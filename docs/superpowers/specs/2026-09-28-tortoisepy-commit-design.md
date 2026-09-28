# tortoisePy — Design, phase 6 : voir, stager, commiter, pousser, inspecter

**Date :** 2026-09-28
**Statut :** brouillon, en attente de relecture

## 1. Problème

tortoisePy sait lire un dépôt et agir sur ses refs (checkout, merge, création de
branches, fetch). Mais le geste le plus courant du quotidien — voir ce qu'on a
modifié, en choisir une partie, écrire un message, publier — oblige encore à
retourner au terminal.

Cette phase ferme ce cycle.

## 2. Ce que l'utilisateur veut faire

1. **Voir ce qui a changé** : quels fichiers, quelles lignes.
2. **Choisir ce qui entre dans le commit** (`git add`).
3. **Écrire un message et commiter**.
4. **Pousser**, ou non.
5. **Inspecter un commit déjà fait** : quels fichiers, quelles lignes.

## 3. Décisions

Arbitrées avec l'utilisateur avant rédaction.

| # | Décision | Alternative écartée |
|---|---|---|
| D5 | Staging **par fichier**. Le staging par hunk (`git add -p`) est reporté | Par hunk dès la v1 — manipuler l'index ligne à ligne dans libgit2 est un chantier à soi seul |
| D6 | **Une seule fenêtre** : fichiers, diff, message et boutons | Deux fenêtres séparées — écrire un message sans voir ce qu'on committe nuit à sa qualité |
| D7 | Deux boutons : **Commit** et **Commit & Push**, le second confirmé | Case « pousser après commit » — cochée par défaut, elle finit par pousser sans qu'on y pense |
| D8 | Fichiers non suivis **affichés, décochés** | Masqués (on rate le fichier qu'on vient de créer) ou cochés (on ajoute `.env` par mégarde) |

## 4. La fenêtre de commit

Une fenêtre autonome, ouverte depuis le menu contextuel ou la barre d'outils.

```
┌─ Commit — branche courante ─────────────────────────────┐
│ ☑ M  src/app.py                    +12 -3               │
│ ☑ A  tests/test_app.py             +40 -0               │
│ ☐ ?  build/output.log                                   │  ← non suivi, décoché
│ ☐ D  vieux.txt                     +0 -8                │
├─────────────────────────────────────────────────────────┤
│ @@ -14,7 +14,9 @@                                       │
│    def charger(chemin):                                 │
│  -     return open(chemin).read()                       │
│  +     with open(chemin) as f:                          │
│  +         return f.read()                              │
├─────────────────────────────────────────────────────────┤
│ Message :                                               │
│ ┌─────────────────────────────────────────────────────┐ │
│ │                                                     │ │
│ └─────────────────────────────────────────────────────┘ │
│                      [ Annuler ] [ Commit ] [ Commit & Push ] │
└─────────────────────────────────────────────────────────┘
```

**Trois zones.** La liste des fichiers en haut, le diff du fichier sélectionné
au milieu, le message et les boutons en bas. Voir le diff en écrivant le
message est précisément ce qui rend le message juste.

### 4.1 La liste des fichiers

Une ligne par fichier modifié, avec une case à cocher et un indicateur :

| Marque | Signification |
|---|---|
| `M` | modifié |
| `A` | ajouté à l'index |
| `D` | supprimé |
| `?` | non suivi |
| `!` | en conflit |

**Cases pré-cochées** pour ce qui est déjà dans l'index, et pour les fichiers
suivis modifiés. **Décochées** pour les fichiers non suivis (D8).

Les fichiers **en conflit** ne peuvent pas être cochés : commiter un conflit
non résolu produit un commit contenant les marqueurs `<<<<<<<`. La ligne les
signale et indique que la résolution se fait hors de l'application — comme
pour le merge (§7.7).

### 4.2 Le diff

Le diff du fichier sélectionné, en lecture seule, police à chasse fixe.

- Lignes ajoutées sur fond vert pâle, supprimées sur fond rouge pâle, contexte
  sur fond neutre.
- En-têtes de hunk (`@@ -14,7 +14,9 @@`) en gris.
- Un fichier binaire affiche « fichier binaire » plutôt qu'un diff illisible.
- Un fichier non suivi affiche son contenu comme entièrement ajouté.

Le diff montre **l'état du fichier par rapport au dernier commit**, que le
fichier soit indexé ou non : c'est ce que l'utilisateur s'apprête à commiter.

### 4.3 Le message

Zone de texte multiligne. Aucun format imposé, aucune longueur maximale.

**Commiter sans message est refusé.** Git l'autorise avec `--allow-empty-message`,
mais un commit sans message est une dette immédiate. Les deux boutons de commit
sont désactivés tant que le message est vide ou que rien n'est coché.

### 4.4 Les boutons

- **Annuler** — ferme sans rien faire. **L'index n'est pas modifié** : cocher
  une case ne stage rien tant qu'on n'a pas commité (voir §5).
- **Commit** — stage les fichiers cochés, puis commite.
- **Commit & Push** — même chose, puis pousse après confirmation (§6.2).

## 5. Le staging n'a lieu qu'au commit

Cocher une case **ne modifie pas l'index**. Les cases décrivent une intention ;
l'index n'est écrit qu'au moment du commit, juste avant de le créer.

Cela tient à §7.0 : tant que l'utilisateur n'a pas cliqué sur un bouton de
commit, rien n'est écrit dans le dépôt. Fermer la fenêtre par « Annuler »
laisse le dépôt exactement dans l'état où il était — y compris son index, que
l'utilisateur a peut-être préparé au terminal.

**Décocher un fichier déjà indexé le retire du commit**, sans le retirer de
l'index pour autant : le commit ne portera que les fichiers cochés, et l'index
conservera ce que l'utilisateur y avait mis. Concrètement, le commit est
construit à partir d'un arbre dérivé de la sélection, pas de l'index tel quel.

C'est la lecture la plus sûre : un utilisateur qui décoche s'attend à ce que le
fichier ne parte pas dans ce commit, pas à voir son index modifié derrière son
dos.

### 5.1 Une exception : l'index est aligné après un commit réussi

Découvert à l'implémentation, le 2026-09-28. Les deux règles ci-dessus se
contredisaient :

- `commit_selection` ne touche jamais `.git/index` (§5) ;
- la liste des fichiers vient de `repo.status()`, qui compare
  **HEAD ↔ index ↔ arbre de travail**.

Donc juste après un commit, l'index resté en arrière faisait toujours
apparaître le fichier comme modifié : la fenêtre continuait de lister un
fichier que l'utilisateur venait de commiter. Vérifié :
`git status --short` rend `MM a.txt` après avoir commité `a.txt`.

**La fenêtre aligne donc l'index sur HEAD après un commit réussi, mais
uniquement pour les chemins commités** — c'est exactement ce que fait un vrai
`git commit`. Le reste de l'index est laissé intact.

Cela ne relâche pas §5 : cocher ou décocher n'écrit toujours rien, et un
fichier décoché que l'utilisateur avait indexé au terminal **reste indexé**.
Vérifié : sur un dépôt où `b.txt` est indexé puis décoché, commiter `a.txt`
seul retire `a.txt` de la fenêtre et laisse `b.txt` indexé.

L'alignement est un confort, jamais une raison de perdre un commit : s'il
échoue (index verrouillé par un `git` concurrent), le commit reste acquis et
l'utilisateur doit l'apprendre — voir §8.

## 6. Les opérations

### 6.1 Commit

Le commit est construit depuis un **index temporaire en mémoire**, jamais
depuis `.git/index` — c'est ce qui permet de ne pas toucher à ce que
l'utilisateur a préparé au terminal (§5).

1. Créer un `pygit2.Index()` détaché, l'initialiser avec l'arbre de `HEAD`.
2. Pour chaque fichier coché : créer le blob depuis l'arbre de travail
   (`create_blob_fromworkdir`), puis ajouter une `IndexEntry`. Pour un fichier
   supprimé : le retirer de l'index temporaire.
3. `write_tree(repo)` — écrit l'arbre dans la base d'objets, **pas** dans
   `.git/index`.
4. `create_commit` sur `HEAD`.

**Un index détaché ne lit pas le disque.** Vérifié : `index.add('fichier')`
lève « Index is not backed up by an existing repository ». Il faut passer par
`create_blob_fromworkdir` et construire l'`IndexEntry` soi-même.

Vérifié le 2026-09-28 sur pygit2 1.20, sur un dépôt où `a.txt` était indexé et
`b.txt` non : commiter la seule sélection `b.txt` produit un commit ne
contenant que `b.txt`, et `git status` montre ensuite `a.txt` toujours indexé.
L'index de l'utilisateur est intact.

**Le premier commit d'un dépôt vide** n'a pas de parent : `create_commit` doit
recevoir une liste de parents vide, pas `[HEAD]` qui n'existe pas encore.

### 6.2 Push

Push est la **seule opération dont l'effet sort de la machine** et que
l'utilisateur ne peut pas défaire seul. Elle est donc toujours confirmée, en
nommant la branche et le remote visés.

**Le refspec est construit depuis la branche courante**, jamais codé en dur :
vérifié, un dépôt cloné récemment est sur `main`, pas `master`.

```python
spec = f"refs/heads/{branch}:refs/heads/{branch}"
```

**Authentification.** Même chemin que le fetch (§7.3) : agent SSH pour les URL
`git@` et `ssh://`, gestionnaire d'identifiants de Git pour HTTPS. Le dépôt de
test `portfolio-v1` est en HTTPS, `vti` et `xpc` en SSH — les deux cas se
présentent en pratique.

**Push rejeté.** Si le serveur a avancé entre-temps, libgit2 refuse et dit :
« cannot push because a reference that you are trying to update on the remote
contains commits that are not present locally ». Ce message est affiché tel
quel (§9).

**Jamais de push forcé.** `--force` réécrit l'historique d'autrui ; aucune
interface de tortoisePy ne l'expose. Un push rejeté se résout en récupérant
d'abord les changements distants.

### 6.3 Exécution en arrière-plan

Le push passe par le réseau. Comme le fetch (§7.9), il s'exécute dans un fil
séparé avec une barre de progression : mesuré, un fetch synchrone gelait
l'interface 1,6 s même sans rien transférer.

Le commit, lui, est local et rapide : il reste dans le fil principal.

## 6.4 Inspecter un commit existant

Double-cliquer un commit dans le panneau ouvre une fenêtre montrant **ce que
ce commit a changé** : la liste des fichiers touchés, et le diff de chacun.

C'est la même question que §4.2 — quelles lignes ont bougé — posée sur un
commit passé au lieu de l'arbre de travail. D'où la même vue de diff, et une
fenêtre distincte, **strictement en lecture seule** : pas de case à cocher, pas
de bouton d'action. Ce commit est déjà fait.

**Le commit est comparé à son premier parent**, comme `git show`.

- Un **commit de merge** a deux parents, donc pas d'« avant » unique. Diffter
  contre le premier montre ce que le merge a apporté à la branche d'accueil —
  ce qu'affiche TortoiseGit.
- Un **commit racine** n'a aucun parent. Vérifié :
  `commit.tree.diff_to_tree(swap=True)` donne le bon résultat ; **sans
  `swap=True`, ses fichiers s'affichent en suppressions**.

Plusieurs de ces fenêtres peuvent être ouvertes en même temps — comparer deux
commits côte à côte est légitime, et elles ne modifient rien. La fenêtre de
commit, elle, reste unique (§4) : deux vues modifiables du même index se
contrediraient.

## 7. Architecture

```
core/
  changes.py     état des fichiers modifiés, diffs      (lecture seule)
                 + changes_in_commit(), diff_in_commit()
  operations.py  commit_selection(), push_branch()      (+ existant)
ui/
  commit_window.py         la fenêtre de commit          (nouveau)
  commit_detail_window.py  changements d'un commit       (nouveau)
  diff_view.py             affichage coloré d'un diff    (nouveau)
```

**`core/changes.py` ne dépend pas de Qt.** Il produit des structures décrivant
les fichiers et leurs diffs ; `ui/` les affiche. La règle de §5 vaut ici comme
ailleurs.

**`ui/diff_view.py` est séparé de la fenêtre** : afficher un diff coloré est
une responsabilité autonome, réutilisable par le futur « Compare revisions »
(§7.4) qui reste hors périmètre.

## 8. Gestion des erreurs

Trois cas, traités différemment :

| Cas | Traitement |
|---|---|
| Commit refusé par Git | Dialogue en trois parties (§9), la fenêtre reste ouverte |
| Push refusé | Le commit est fait et conservé ; seul le push a échoué. Le dialogue le dit explicitement |
| Fichier disparu entre l'affichage et le commit | Message nommant le fichier, la fenêtre se rafraîchit |
| Index verrouillé après un commit réussi (§5.1) | Le commit est acquis ; on le dit, et on signale que l'index n'a pu être rafraîchi |

**Le cas du push refusé mérite une attention particulière.** L'utilisateur a
cliqué « Commit & Push » : si le push échoue, il doit comprendre que son
travail est commité localement et n'est pas perdu.

## 9. Ce qui reste hors périmètre

- **Le staging par hunk** (D5) — reporté, pas abandonné.
- **Amender un commit** (`git commit --amend`).
- **Pull** — il fusionne dans la branche courante, avec ses conflits.
- **La résolution de conflits** — déjà hors périmètre v1 (§7.7).
- **Push forcé** — jamais.

## 10. Tests

- **`core/changes.py`** — dépôts construits par fixtures : fichier modifié,
  ajouté, supprimé, non suivi, binaire, en conflit. Vérifier le décompte des
  lignes et le contenu des hunks.
- **`core/operations.py`** — staging et commit sur dépôt temporaire, y compris
  le premier commit d'un dépôt vide. Push contre un dépôt nu local, et push
  rejeté après qu'un tiers a poussé.
- **`ui/`** — la fenêtre s'ouvre, les cases reflètent l'état, les boutons sont
  désactivés sans message ou sans sélection, « Annuler » ne touche pas à
  l'index.
- **Détail d'un commit** — un commit ordinaire, un commit racine, un commit de
  merge, un OID inconnu. La fenêtre n'expose aucune case à cocher.
- **Lecture seule** — `tests/test_read_only.py` doit rester vert : ouvrir la
  fenêtre de commit et cocher des cases n'écrit rien.

Les tests d'intégration utilisent `portfolio-v1`, à la demande de
l'utilisateur. Il est actuellement propre et son remote est en HTTPS ; les
fixtures créent donc leurs propres dépôts pour les cas de modification et de
push.
