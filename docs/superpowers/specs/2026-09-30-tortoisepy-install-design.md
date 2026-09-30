# tortoisePy — Design, phase 15 : installer et lancer

**Date :** 2026-09-30
**Statut :** brouillon, en attente de relecture

## 1. Problème

Il n'existe aucun moyen d'installer tortoisePy sans cloner le dépôt et
bricoler un environnement. L'outil est fini ; il est inutilisable par qui que
ce soit d'autre.

**Le public est constitué de développeurs** (décidé avec l'utilisateur). Cela
change tout : un terminal est acquis, un installeur graphique serait du travail
perdu.

## 2. Ce que la mesure a établi

Sondé avant de concevoir :

- **le point d'entrée existe déjà** — `tgraph = "tortoisepy.cli:main"` dans
  `pyproject.toml` ;
- **`topy .` et `topy /chemin` fonctionnent déjà** : `cli.py:96` fait
  `target = arguments[0] if arguments else "."`, et `find_repository` remonte
  l'arborescence comme git. Il ne manque que le **nom** ;
- **aucune compilation chez l'utilisateur** : `pygit2` et `PySide6` ont des
  roues précompilées pour `win_amd64` et `macosx universal2` — vérifié en les
  téléchargeant ;
- **le paquet pèse 1,7 Mo**, mais **PySide6 pèse 1,2 Go**. C'est ce qui sera
  téléchargé, et il faut le dire ;
- **une installation isolée prend une minute**, mesurée de bout en bout, et la
  commande répond depuis n'importe quel répertoire.

| # | Décision | Alternative écartée |
|---|---|---|
| D30 | La commande s'appelle **`topy`** | `tgraph` — ne dit pas le nom du produit |
| D31 | Installation par **`uv tool install`** | `pipx` (exige un Python configuré) ; installeur `.dmg`/`.msi` (inutile pour des développeurs, et coûteux : signature Apple, certificat Windows) |
| D32 | Le script d'installation **vérifie que la commande répond** | Installer et se taire — le piège du PATH (§4) |
| D33 | Le paquet s'installe **depuis GitHub**, pas depuis PyPI | Publier d'abord — irréversible, et inutile pour démarrer |
| D34 | L'URL d'installation pointe vers un **tag figé** | `main` — un commit cassé deviendrait aussitôt ce que les nouveaux installent |

## 3. Le geste

**Une commande, par plateforme.** Vérifié : le dépôt
`romainh3nry/TortoisePy` est public, branche `main`, et GitHub sert ses
fichiers en brut sans authentification.

```
# macOS / Linux
curl -LsSf https://raw.githubusercontent.com/romainh3nry/TortoisePy/v0.1.0/scripts/install.sh | sh

# Windows (PowerShell)
irm https://raw.githubusercontent.com/romainh3nry/TortoisePy/v0.1.0/scripts/install.ps1 | iex
```

Le script installe `uv` s'il manque, puis tortoisePy **depuis le dépôt, au
même tag** :

```
uv tool install git+https://github.com/romainh3nry/TortoisePy@v0.1.0
```

Puis, dans n'importe quel projet :

```
topy .              # le dépôt du répertoire courant
topy /chemin/projet # un dépôt ailleurs
topy                # équivalent à « topy . »
```

`uv` crée un environnement isolé et télécharge l'interpréteur au besoin :
**l'utilisateur n'a pas à installer Python lui-même**.

### 3.1 Pourquoi GitHub plutôt que PyPI (D33)

Installer depuis le dépôt **retire l'irréversible de l'équation** : aucun nom
n'est réservé, aucune version n'est figée, rien ne devient public de façon
permanente. La publication PyPI reste possible plus tard, pour que
`uv tool install tortoisepy` fonctionne sans URL — mais ce n'est **plus un
préalable**.

### 3.2 Le piège du tag : DEUX endroits à synchroniser (D34)

Figer l'URL du script **sans figer ce qu'il installe ne fige rien**. Le script
prendrait la branche par défaut du dépôt, c'est-à-dire le dernier `main`.

À chaque version, deux changements vont ensemble :

| Où | Quoi |
|---|---|
| `README.md` | `.../TortoisePy/**v0.1.0**/scripts/install.sh` |
| `scripts/install.sh` et `.ps1` | `git+https://github.com/romainh3nry/TortoisePy**@v0.1.0**` |

**Le second est celui qu'on oublie**, parce qu'il est invisible depuis le
README. Un test le vérifie (§8) : les deux références doivent nommer la même
version.

### 3.3 Ce que `curl | sh` implique, et qu'il faut assumer

**Le script devient du code public exécuté sur la machine des autres.** Une
erreur dedans s'exécute chez eux. C'est la norme de l'écosystème — `uv`,
Homebrew et rustup s'installent ainsi — mais cela impose deux choses :

- **pointer vers un tag, pas vers `main`** : sinon un utilisateur installe la
  dernière version, même cassée. Le README nommera une version figée ;
- **garder la forme en deux étapes** dans le README, pour les développeurs qui
  refusent par principe de piper un script distant dans un shell. Ils sont
  nombreux, et ils ont raison de se méfier.

## 4. Le piège : l'installation réussit, la commande reste introuvable

Vérifié lors d'une installation réelle :

```
Installed 1 executable: tgraph
warning: `/Users/r.henry/.local/bin` is not on your PATH.
```

**C'est là qu'un utilisateur abandonne** : tout s'est bien passé, et `topy`
répond « command not found ». Le script d'installation doit donc, après coup :

1. lancer `topy --version` ;
2. si la commande ne répond pas, **dire où elle a été posée** et quelle ligne
   ajouter au shell — pas se contenter d'un avertissement générique.

Un installeur qui ne vérifie pas son propre résultat n'a pas fini son travail.

## 5. La ligne de commande

`main()` traite déjà `--version` et `--install-icon`. Deux défauts vérifiés :

```
tgraph --help  ->  « Pas de dépôt Git trouvé dans --help »
```

**`--help` est pris pour un chemin de dépôt.** C'est la première chose que tape
quelqu'un qui découvre l'outil.

Cette phase ajoute donc `--help`, et **refuse toute option inconnue** au lieu
de la traiter comme un chemin : `topy --verison` (faute de frappe) doit dire
que l'option n'existe pas, et non chercher un dépôt nommé « --verison ».

**Les codes de sortie sont déjà justes** (vérifié : `1` en cas d'échec, `0`
sinon) — rien à corriger de ce côté.

## 6. Publier sur PyPI — plus tard, et seulement si l'utilisateur le veut

L'installation depuis GitHub (D33) rend la publication **facultative**. Elle
n'apporterait qu'une chose : `uv tool install tortoisepy` sans URL.

**Elle reste irréversible**, et appartient à l'utilisateur :

- un numéro de version ne se réutilise **jamais** — une erreur dans la `0.1.0`
  oblige à publier une `0.1.1` ;
- le nom est réservé **définitivement** ;
- le code devient public de façon permanente, sous son identité.

**Vérifié :** `tortoisepy` est libre sur PyPI. `topy` y est **pris** par un
correcteur de fautes de frappe sans mise à jour depuis 2021 — sans
conséquence, le nom du paquet et celui de la commande étant indépendants, mais
à savoir avant de figer quoi que ce soit.

Cette phase prépare les métadonnées pour que ce soit possible, et **ne publie
pas**.

## 7. Architecture

```
pyproject.toml     `topy` remplace `tgraph`, métadonnées de publication
cli.py             `--help`, refus des options inconnues       (modifié)
scripts/install.sh    macOS et Linux                            (nouveau)
scripts/install.ps1   Windows                                   (nouveau)
README.md          installation et usage                        (modifié)
```

Aucun fichier de `src/tortoisepy/ui/` ni de `layout/` n'est touché : cette
phase ne change pas le comportement de l'application, seulement la façon de
l'obtenir et de la lancer.

## 8. Tests

- **`--help`** — affiche l'usage, sort en `0`, et **ne cherche aucun dépôt**.
- **Une option inconnue** — message clair, sortie `1`, pas de tentative
  d'ouverture.
- **`topy`, `topy .`, `topy /chemin`** — les trois formes visent le bon dépôt.
- **Un sous-répertoire** — `topy` depuis `projet/src/` trouve `projet/.git`,
  comme git.
- **Un chemin sans dépôt** — message nommant le chemin, sortie `1`.
- **Le point d'entrée s'appelle bien `topy`** — un test lit `pyproject.toml`,
  pour que le renommage ne se perde pas.
- **Les scripts d'installation** ne sont pas exécutés en test (ils
  installeraient vraiment) : on vérifie qu'ils existent, et qu'ils contiennent
  l'étape de vérification exigée par D32.
- **Les deux références de version concordent** (§3.2) — le tag de l'URL dans
  le README et le `@tag` dans les scripts. C'est le test qui empêche l'oubli
  silencieux, celui qui ferait installer `main` en croyant installer une
  version figée.

## 9. Hors périmètre

- **Publier sur PyPI** — c'est à l'utilisateur (§6).
- **Un installeur `.dmg` / `.msi`** — inutile pour des développeurs, et
  coûteux : signature Apple à 99 €/an, certificat Windows sans lequel
  SmartScreen bloque.
- **Un exécutable autonome** (PyInstaller, Nuitka) — PySide6 pèse 1,2 Go : le
  binaire ferait plusieurs centaines de Mo, pour un public qui sait déjà
  installer un outil en ligne de commande.
- **Homebrew, winget, apt** — chacun demande sa propre recette et son propre
  cycle de publication ; à considérer si la demande vient.
- **Mettre à jour automatiquement** — `uv tool upgrade tortoisepy` existe déjà.
