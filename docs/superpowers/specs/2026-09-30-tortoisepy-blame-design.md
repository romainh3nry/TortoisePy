# tortoisePy — Design, phase 14 : qui a écrit cette ligne

**Date :** 2026-09-30
**Statut :** brouillon, en attente de relecture

## 1. Problème

L'application sait montrer ce qu'un commit a changé. Elle ne sait pas répondre
à la question inverse, qui est celle qu'on se pose devant du code : **« qui a
écrit cette ligne, et pourquoi ? »**

C'est le geste d'enquête le plus courant après la recherche, et il oblige
aujourd'hui à retourner au terminal.

## 2. Ce qui rend cette phase peu risquée

Trois mesures, prises avant de concevoir :

- **`repo.blame()` coûte 42 ms** sur un fichier à 3 000 révisions — sans
  commune mesure avec l'historique de fichier (2,1 s, écarté §8) ;
- **l'API donne directement ce qu'il faut** : plages de lignes, commit
  d'origine, auteur ;
- **rien n'est écrit** : le blame lit, donc §7.0 est respecté sans effort.

C'est aussi la première phase depuis longtemps qui **n'ajoute aucune opération
destructrice**. Elle ne peut pas faire perdre de travail.

| # | Décision | Alternative écartée |
|---|---|---|
| D27 | On blâme depuis la **fenêtre de détail d'un commit** | Depuis la fenêtre de commit — les lignes non commitées ne sont pas couvertes (§4.3) |
| D28 | Cliquer une ligne **ouvre le commit d'origine** | Affichage seul — il faudrait retrouver le commit à la main |
| D29 | Le blâme part du **commit affiché**, pas de HEAD | Toujours HEAD — on veut voir l'état à ce moment de l'histoire |

## 3. Le geste

Double-clic sur un commit → la fenêtre de détail liste ses fichiers → clic
droit sur un fichier → **« Blame »** → une fenêtre montre le fichier, une ligne
par ligne, précédée de son commit, son auteur et sa date.

**Cliquer une ligne ouvre le détail de son commit d'origine** (D28) : c'est
l'enchaînement de l'enquête — « qui » puis « pourquoi ». La fenêtre de détail
existe déjà et sert les deux.

**D29 :** le blâme part du commit affiché. Depuis un commit de l'an dernier, on
voit qui avait écrit chaque ligne **à ce moment-là**, pas aujourd'hui. C'est ce
qu'on cherche quand on remonte une piste.

## 4. Ce que le blâme ne couvre pas — vérifié

### 4.1 Un fichier absent du commit

```
fichier non suivi    -> NotFoundError: "the path 'neuf.txt' does not exist…"
fichier inexistant   -> NotFoundError
```

L'entrée de menu ne se propose que sur les fichiers **listés par le commit** :
ils y sont par construction. Le cœur refuse tout de même proprement, pour qui
l'appellerait autrement.

### 4.2 Un fichier binaire

```
fichier binaire -> 1 hunk
```

libgit2 ne lève pas : il rend un bloc unique et inutile. L'application
**détecte le binaire et le dit**, plutôt que d'afficher des octets comme s'ils
étaient du texte.

### 4.3 Les lignes non commitées

```
4 lignes sur disque, 3 couvertes par le blâme
```

C'est la raison de D27. Depuis la fenêtre de commit, un fichier en cours de
modification aurait des lignes que le blâme ignore, sans rien pour le signaler.
Depuis un commit, le contenu blâmé est celui du commit : la question ne se pose
pas.

## 5. L'attribution

`hunk.final_committer` existe, mais **c'est l'auteur du commit qu'on affiche** :
le committer peut être celui qui a appliqué un patch, pas celui qui l'a écrit.
Vérifié sur un dépôt à deux auteurs — `commit.author` donne bien Bob pour la
ligne que Bob a écrite.

Chaque ligne montre : **SHA court**, **auteur**, **date**, puis le texte.
Les lignes d'un même commit partagent la même teinte de fond, pour que les
blocs se voient d'un coup d'œil sans lire les SHA.

## 6. Architecture

```
core/
  blame.py            annoter un fichier, ligne par ligne   (nouveau)
ui/
  blame_window.py     la vue                                (nouveau)
  commit_detail_window.py  entrée « Blame » sur un fichier  (modifié)
```

**`ui/graph_items.py`, `ui/theme.py`, `layout/` ne sont pas touchés** : cette
phase n'approche pas le graphe.

`core/blame.py` ne dépend pas de Qt.

`BlameWindow` suit le motif des fenêtres existantes (`CommitDetailWindow`,
`ConflictWindow`), y compris sa leçon : **la fenêtre est gardée en référence
par son parent**, sinon Python la ramasse aussitôt ouverte — défaut vécu en
phase 6.

## 7. Tests

- **Attribution** — deux auteurs, chacun ses lignes ; l'**auteur** est retenu,
  pas le committer (§5).
- **Un fichier d'un seul commit** — toutes les lignes lui reviennent.
- **Un fichier absent du commit** — refus clair, pas d'exception nue.
- **Un fichier binaire** — détecté et annoncé, pas affiché comme du texte.
- **Le blâme part du commit demandé** (D29) — blâmer depuis un commit ancien
  ne montre pas les modifications postérieures. C'est le test qui distingue
  cette conception d'un blâme de HEAD.
- **Un fichier vide** — aucune ligne, aucune erreur.
- **Navigation** — cliquer une ligne émet l'OID de son commit.
- **Lecture seule (§7.0)** — blâmer n'écrit rien : empreinte `.git` inchangée.

## 8. Hors périmètre

- **L'historique d'un fichier** (`git log -- fichier`) — **mesuré à 2,1 s**
  pour 500 commits, un diff par commit. Utile, mais quatre fois plus cher que
  tout le reste ; à traiter séparément si le besoin se confirme.
- **Suivre les renommages** (`-C`, `-M`) — pygit2 l'expose, mais cela change
  le sens de « la ligne vient de » et mérite sa propre réflexion.
- **Blâmer une plage de lignes** — l'API le permet ; l'intérêt est de
  l'accélérer sur de très gros fichiers, ce que les 42 ms mesurés ne
  justifient pas.
- **Blâmer depuis la fenêtre de commit** — écarté par D27 (§4.3).
