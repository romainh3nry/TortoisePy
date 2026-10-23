# Points d'entrée — ouvrir un projet, chercher, éditer

**Date :** 2026-10-23 (rétrospective — construit entre le 14 et le 23
octobre)
**Modules :** `core/projects.py`, `core/editors.py`,
`core/protocols.py`, et les parties correspondantes de `cli.py` et
`ui/main_window.py`

> **Spec rétrospective.** Construit en conversation directe ; écrit
> après coup pour qu'une reconstruction retrouve ces chemins.

---

## 1. Le dossier de projets (`core/projects.py`)

### Pourquoi

« Open Recent » ne liste que ce qui a **déjà** été ouvert. Ouvrir un
projet neuf imposait la ligne de commande.

### Ce qui compte pour la reconstruction

**Ne pas réutiliser `find_repository`.** Elle s'appuie sur
`discover_repository`, qui **remonte** l'arborescence comme le fait
Git. Appelée sur chaque sous-dossier d'un workdir lui-même versionné,
elle « trouverait » partout le dépôt parent, et la liste serait
entièrement fausse.

La détection regarde donc chaque dossier **lui-même**, sans jamais
remonter.

| Décision | Valeur | Raison |
|---|---|---|
| Profondeur | `PROFONDEUR = 2` | couvre les arborescences rangées par client (`~/Projets/client/api`) sans parcourir des `node_modules` entiers |
| Arrêt | dès qu'un `.git` est trouvé | un dépôt ne contient pas d'autres projets à lister |
| `.git` fichier | accepté | c'est ainsi que se présentent les worktrees et sous-modules |
| Dossiers cachés | écartés | `.cache` n'est pas un projet, et un workdir versionné se listerait comme son propre enfant |
| Noms imbriqués | portent le parent (`client-a/api`) | deux « api » seraient indiscernables dans le menu |
| Tri | alphabétique, insensible à la casse | l'ordre d'`iterdir` n'est pas stable d'une machine à l'autre |

**Le scan n'instancie aucun dépôt** (§7.0) : `pygit2.Repository` peut
poser un fichier de verrou sur un dépôt abîmé, alors que lister reste
une lecture. Un test compare les dates de modification.

Une `PermissionError` sur un sous-dossier ne doit pas priver
l'utilisateur de **tous** ses projets.

### Le réglage

`view/workdir`, déclaré au schéma de `core/settings.py`. Il n'est
**pas** vérifié à la lecture : le dossier peut être sur un disque
externe débranché, et l'oublier en silence perdrait le réglage. C'est
à l'affichage de dire qu'il est introuvable.

## 2. La recherche en ligne de commande

### Pourquoi

Ouvrir un projet demandait son chemin complet. Sur un dossier de
61 projets aux noms de 15 caractères en moyenne, c'est long.

### Le comportement

```
topy -s vti      → 1 résultat  → ouvre directement
topy -s crm      → 5 résultats → liste numérotée, lit un choix
topy -s zzz      → message, code 1
topy -s          → usage, code 1
```

**Un seul résultat ouvre sans demander** : `topy -s vti` sans frappe
supplémentaire est le but de la fonctionnalité.

**Liste numérotée et non menu à curseur.** `curses` est absent de
CPython sous Windows, et un menu plein écran ne fonctionne pas dans un
tube — il aurait fallu écrire les deux. Et sur des listes de 1 à 5
résultats, taper « 4 » est plus rapide que quatre flèches.

### Deux points d'ordre

**L'invite vient AVANT le détachement.** `topy` se relance en
arrière-plan pour rendre la main au terminal en 0,07 s, les trois flux
vers le vide : une question posée après n'atteindrait personne.

**Toute annulation rend 1, pas 0.** Entrée vide, `Ctrl-C`, `Ctrl-D` :
`0` signifierait « ce qui était demandé a été fait », et un script
enchaînant `topy -s crm && deploy` partirait sur un déploiement alors
que rien n'a été ouvert.

### Les trois refus, et pourquoi ils diffèrent

Le réglage `view/workdir` n'est pas vérifié à l'écriture ; trois états
mènent donc à zéro résultat, et les confondre envoie l'utilisateur
chercher au mauvais endroit.

| État | Message | Pourquoi distinct |
|---|---|---|
| Aucun dossier choisi | « Aucun dossier de projets choisi » + où en définir un | Le réglage n'existe pas : rien à corriger, tout à faire. |
| Dossier réglé mais introuvable | « Le dossier de projets est introuvable : *chemin* » + où en définir un | **Le chemin est nommé.** Renommé, déplacé, supprimé : la cause n'est pas devinable, et l'annoncer serait une hypothèse. |
| Dossier présent, sans dépôt correspondant | « Aucun projet ne correspond à *motif* dans *chemin* » | Le réglage est bon. Renvoyer ici vers « Open Project » ferait refaire un réglage correct. |

Le contrôle teste `is_dir`, pas `exists` : un réglage pointant sur un
**fichier** est aussi inexploitable, et `find_projects` le traite déjà
comme absent. Les deux doivent dire la même chose.

Les trois rendent **1**.

## 3. Ouvrir dans un éditeur (`core/editors.py`)

### Pourquoi

Faire ce que fait `code .`, depuis l'application.

### Le piège décisif

L'application se lance depuis un **bundle macOS**, qui ne reçoit pas
le `PATH` du terminal. Mesuré :

```
which("code") depuis le terminal    → /usr/local/bin/code
which("code") avec un PATH minimal  → None
```

Une détection par `shutil.which` seul **cacherait le bouton chez
quelqu'un ayant VSCode** — l'inverse exact de ce qui est voulu.

D'où la double recherche : le `PATH` **d'abord** — ce que
l'utilisateur y a mis fait foi, une version précise ou un script à lui
— puis les chemins de repli, qui sont un filet et non une préférence.

### Le catalogue

Liste fixe, ordre fixe : deviner l'éditeur préféré serait arbitraire,
et l'ordre du disque n'est pas stable.

Famille VSCode (`code`, `code-insiders`, `codium`, `cursor`), `zed`,
`subl`, et **toute la famille JetBrains** — `phpstorm`, `pycharm`,
`idea`, `webstorm`, `goland`, `rubymine`, `clion`, `rider`,
`datagrip`, `studio`. Ils partagent le même dossier de scripts posé
par Toolbox ; en oublier un revient à le rendre invisible sans raison.

**Toute entrée du catalogue doit avoir un chemin de repli**, sinon
elle serait morte : listée mais jamais trouvée. Un test l'exige.

### Deux règles de comportement

- **Un seul éditeur : un bouton direct**, pas de menu. Dérouler pour
  choisir entre une option serait un clic de trop.
- **Le lancement est détaché** (`start_new_session`). Attendre la
  fermeture de l'éditeur gèlerait l'application — un éditeur reste
  ouvert des heures.

Un fichier du bon nom mais sans droit d'exécution n'est pas un
éditeur : le proposer ferait cliquer pour rien.

## 4. Savoir combien de graphes sont ouverts (menu « Windows »)

### Pourquoi

Signalé par l'utilisateur :

> « si j'ouvre un deuxième repo depuis le open project ou open recent,
> le graph s'affiche bien mais pas de deuxième icône, ce qui fait qu'on
> ne sait pas très bien combien de graph est ouvert »

### Ce n'est pas un défaut, c'est la plateforme

Le Dock de macOS représente des **processus**, pas des fenêtres.

| Chemin | Mécanisme | Icônes |
|---|---|---|
| `topy <chemin>` | `Popen` → nouveau processus | une par graphe |
| « Open Project » / « Open Recent » | `MainWindow(...)` dans le processus courant | une seule, partagée |

Aucun réglage ne change cela : une application avec cinq fenêtres a
une icône. La réponse est donc la convention macOS pour ce problème —
un menu listant les fenêtres ouvertes — qui règle le **comptage** et
la **navigation**, le vrai besoin derrière la question.

### Ce qui compte pour la reconstruction

**La source est `QApplication.topLevelWidgets()`, pas
`_recent_windows`.** Ce registre est **par fenêtre** : la fenêtre A
ouvre B et C, mais B ne connaît ni A ni C. Un menu alimenté par lui
aurait montré une liste différente selon l'endroit d'où on l'ouvre —
exactement la confusion à lever.

**Le filtre porte sur `isVisible()`.** Mesuré : la fenêtre racine,
celle lancée depuis le terminal, ne porte pas `WA_DeleteOnClose` ;
fermée, elle **reste** dans `topLevelWidgets()`, `isVisible()` à
False. Sans ce filtre, le menu listerait une fenêtre fermée.

**Pas de garde `still_alive` dans ce filtre.** Mesuré : Qt retire
lui-même l'objet qu'il a détruit. Le garde serait du code mort, et la
mutation l'a confirmé — aucun test ne pouvait le tuer. Il reste
**nécessaire** dans le gestionnaire de clic, où la référence figée
dans la fermeture peut vieillir entre l'ouverture du menu et le clic.

**Le test de type est nécessaire** : `topLevelWidgets()` rend toutes
les fenêtres de premier niveau, écran d'attente et dialogues compris.

**L'ordre suit le titre.** Celui de `topLevelWidgets()` est arbitraire
(mesuré : beta, gamma, alpha pour trois fenêtres créées dans l'ordre
inverse) et changerait d'une ouverture à l'autre, faisant cliquer à
côté.

**Un `QToolButton`, pas un `QMenuBar`** : ce projet n'a pas de barre
de menus, tout vit dans la barre d'outils. En introduire une pour une
entrée changerait l'aspect de la fenêtre, que l'utilisateur a validé.

**Trois appels pour remonter une fenêtre** — `show` rétablit une
fenêtre réduite, `raise_` la remonte dans la pile, `activateWindow`
donne le focus clavier. Omettre le dernier la fait apparaître sans
qu'on puisse y taper.

Le titre portait déjà le dépôt et la branche
(« alpha [main] — tortoisePy ») : le menu le réutilise en retirant le
suffixe de l'application, inutile dans un menu qui lui appartient.
**Par `removesuffix`, jamais `rstrip`** : `rstrip(" — tortoisePy")`
ampute tout titre finissant par une de ces lettres.

**Le bouton se place hors du bloc conditionnel de « Open in editor »**,
qui n'existe que si un éditeur est installé. À l'intérieur, le bouton
disparaîtrait chez quelqu'un sans éditeur — invisible en
développement, où il y en a toujours un. Un test pose le cas.

## 5. Les protocoles réseau (`core/protocols.py`)

### Pourquoi

Signalé sur une installation **Windows** : toute commande réseau
répondait « Unsupported URL protocol in git provider ». Le message
vient de libgit2 et ne dit ni quel protocole manque, ni quoi faire.

### Ce que ça fait

`check_url_supported` interroge les fonctionnalités de libgit2 avant
de tenter l'opération, et rend un refus qui **nomme le protocole** et
dit comment installer une version complète.

C'est un cas de la règle §9 : un message d'erreur doit permettre
d'agir, pas seulement constater.
