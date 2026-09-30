# tortoisePy — Design, phase 12 : amender, et savoir où l'on en est

**Date :** 2026-09-29
**Statut :** brouillon, en attente de relecture

## 1. Problème

Deux manques, liés.

**On ne peut pas corriger le dernier commit.** Une faute dans le message, un
fichier oublié : il faut retourner au terminal. C'est le geste correctif le
plus fréquent de tout Git.

**On ne sait pas si l'on a divergé.** L'application marque les commits non
poussés, mais ne dit nulle part « tu as 2 commits d'avance et 1 de retard ».
C'est précisément l'information qui manque après un amend ou un rebase, quand
on se demande si l'on peut pousser normalement.

Les deux vont ensemble : amender rend la branche divergente, et l'indicateur
est ce qui le montre.

## 2. Ce qui rend l'amend acceptable aujourd'hui

Amender réécrit le commit. S'il était déjà poussé, le push normal est rejeté.

**Jusqu'à la phase 10, c'était une impasse.** Le force-push existe désormais,
avec un bail arbitré par le serveur : amender puis republier est un chemin
complet, et sûr pour le travail d'autrui.

| # | Décision | Alternative écartée |
|---|---|---|
| D20 | On amende **le dernier commit seulement** | Amender un ancêtre — c'est du rebase interactif (hors périmètre) |
| D21 | Le message **et** le contenu sont amendables | Le message seul — le fichier oublié est la moitié du besoin |
| D22 | L'indicateur dit **ce que le dernier fetch a vu** | Interroger le serveur à chaque rafraîchissement — lent, et bavard sur le réseau |

## 3. Amender (D20, D21)

### 3.1 Le geste

Dans la fenêtre de commit, une case **« Amend last commit »**. Cochée :

- le message du dernier commit remplit la zone de saisie ;
- les fichiers cochés s'ajoutent à ce commit au lieu d'en créer un nouveau ;
- le bouton devient **« Amend »**.

Décocher revient à un commit normal.

### 3.2 Ce que libgit2 garantit — vérifié

```
amender en ajoutant un fichier oublié
  fichiers du commit : ['f.txt', 'oublie.txt']
  un seul commit ? True

amender le tout premier commit (sans parent) -> OK
l'auteur d'origine est conservé (nom et date)
```

**Et ce qu'il refuse de lui-même :**

```
amender un commit qui n'est plus la pointe
  LEVE : GitError - commit to amend is not the tip of the given branch
```

C'est la garantie qui rend D20 tenable : on ne peut pas réécrire un ancêtre
par accident, libgit2 s'y oppose.

### 3.3 Le piège : la HEAD détachée

**Vérifié, et c'est le seul cas dangereux :**

```
HEAD détachée -> amend ACCEPTÉ | HEAD -> 10d8e3c9
```

Aucune branche ne suit le nouveau commit : il devient orphelin, invisible dans
le graphe, récupérable seulement par le reflog. **L'application refuse donc
d'amender sur une HEAD détachée**, et la case est grisée.

Sont également refusés, pour les mêmes raisons de sens :

- **un dépôt sans commit** (`head_is_unborn`) — il n'y a rien à amender ;
- **une opération en cours** (merge, rebase, cherry-pick) — l'état est déjà
  instable, et `state()` le dit.

### 3.4 Après l'amend

Le commit change d'identifiant. Si l'ancien était poussé, la branche diverge :
le push normal échouera avec `non-fastforwardable`.

**L'application le dit avant, pas après.** Quand la case est cochée sur un
commit déjà poussé, un avertissement le signale et nomme la suite :
« Push (force with lease) ». C'est ce qui évite le message de git que
l'utilisateur ne sait pas interpréter.

## 4. L'indicateur devant/derrière (D22)

### 4.1 Ce qu'il montre

Dans la barre de statut, à côté du nom de la branche :

```
⎇ main  ↑2 ↓1
```

`↑` : commits locaux que le serveur n'a pas. `↓` : commits du serveur que l'on
n'a pas. Rien n'est affiché quand les deux valent zéro — une branche à jour
n'a pas besoin d'être commentée.

`repo.ahead_behind(local, distant)` rend le couple directement (vérifié).

### 4.2 Il mesure le dernier fetch, pas le serveur — le piège de cette partie

**Vérifié :**

```
un autre dépôt pousse un second commit
  sans nouveau fetch : ahead=2 behind=1   <- PÉRIMÉ
  après fetch        : ahead=2 behind=2
```

L'indicateur dirait `↓1` alors que le serveur en a 2. **Il ne peut pas en être
autrement** sans interroger le réseau à chaque rafraîchissement, ce que D22
écarte : ce serait lent et bavard.

La conséquence est donc **assumée et dite** : l'infobulle précise « as of your
last fetch ». Un indicateur qui se tait sur sa fraîcheur mentirait par
omission ; celui-ci dit ce qu'il sait et depuis quand.

### 4.3 Quand il ne s'affiche pas

- **Pas d'upstream configuré** — `branch.upstream` vaut `None` (vérifié) : il
  n'y a rien à comparer, et une branche purement locale n'est ni en avance ni
  en retard.
- **HEAD détachée ou dépôt sans commit** — aucune branche courante.

## 5. Architecture

```
core/
  amend.py        amender le dernier commit, dire si c'est possible  (nouveau)
  push_state.py   ahead/behind depuis la ref de suivi                (modifié)
ui/
  commit_window.py case « Amend », message pré-rempli, avertissement (modifié)
  main_window.py   l'indicateur dans la barre de statut              (modifié)
```

`core/amend.py` ne dépend pas de Qt. L'ahead/behind rejoint `push_state.py`,
qui répond déjà à « où en suis-je vis-à-vis du serveur ».

## 6. Tests

- **Amender le message seul** — un seul commit, nouveau message.
- **Amender en ajoutant un fichier** — le fichier oublié entre dans le commit,
  et il n'en existe toujours qu'un.
- **L'auteur d'origine est conservé** — amender n'est pas se réapproprier le
  travail d'un autre.
- **Le premier commit** (sans parent) s'amende.
- **HEAD détachée** — refusé, et **aucun commit orphelin créé** : c'est
  l'assertion qui compte, pas le simple refus.
- **Dépôt sans commit**, **opération en cours** — refusés avec un message clair.
- **L'avertissement** apparaît si le commit est déjà poussé, pas sinon.
- **ahead/behind** — les deux sens, une branche à jour (rien affiché), une
  branche sans upstream (rien affiché).
- **La fraîcheur** — un test pose explicitement que la valeur reflète la ref de
  suivi et non le serveur, pour que personne ne « corrige » ce comportement
  plus tard.
- **Lecture seule (§7.0)** — calculer ahead/behind n'écrit rien.

## 7. Hors périmètre

- **Amender un ancêtre** — c'est du rebase interactif, déjà écarté.
- **Changer l'auteur** (`--author`, `--reset-author`) — rare, et lourd de sens.
- **Interroger le serveur pour l'indicateur** — c'est ce que fait Fetch, qui
  existe et reste le geste explicite.
- **Amender depuis le graphe** — la fenêtre de commit est le lieu où l'on
  compose un commit ; deux portes pour un même geste dérouteraient.
