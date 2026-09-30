# tortoisePy — Design, phase 20 : réglages persistés et raccourcis modifiables

**Date :** 2026-09-30
**Statut :** brouillon, en attente de relecture

## 1. Problème

Trois constats, vérifiés dans le code plutôt que supposés.

**Rien n'est mémorisé.** `QSettings` n'apparaît nulle part dans `src/`. À
chaque lancement on retrouve la taille de fenêtre par défaut, le zoom par
défaut, la largeur de panneau par défaut. Sur un outil ouvert plusieurs fois
par jour, c'est la friction la plus répétée de l'application.

**Les raccourcis sont codés en dur.** `main_window.py:405-418` les déclare
dans une liste littérale :

```python
("Commit…", QKeySequence("Ctrl+K"), self.open_commit_window),
```

Le raccourci est dans le tuple. Rien ne peut le surcharger.

**Ils sont invisibles.** Dix raccourcis existent ; aucune fenêtre ne les
liste. On les découvre en lisant le code.

## 2. Les deux questions de l'utilisateur, mesurées

### 2.1 Les raccourcis fonctionnent-ils sur Windows ET macOS ?

**Oui, et c'est déjà le cas.** Qt traduit `Ctrl` selon la plateforme —
mesuré :

```
Ctrl+F        -> NativeText « ⌘F »    PortableText « Ctrl+F »
Ctrl+Shift+F  -> NativeText « ⇧⌘F »   PortableText « Ctrl+Shift+F »
```

Une seule chaîne source, deux rendus. C'est pourquoi le ⌘F de la phase 16
fonctionne sans code spécifique à macOS.

**Conséquence pour le stockage** (D1) : on écrit du `PortableText`. Un
fichier de préférences contenant `⌘F` serait illisible sur Windows.

### 2.2 Une mise à jour fait-elle perdre les réglages ?

**Non.** Vérifié par l'expérience, pas par raisonnement : écriture d'un
raccourci, `pip install --force-reinstall` (le mécanisme exact de
`install.sh`), relecture — valeur intacte.

La raison est structurelle, donc durable : les emplacements sont disjoints.

| | Chemin (macOS) |
|---|---|
| L'application, effacée à chaque `--force` | `~/.local/share/uv/tools/tortoisepy` |
| Les préférences, jamais touchées | `~/Library/Preferences/com.tortoisepy.tortoisePy.plist` |

Sur Windows : registre `HKCU\Software\tortoisePy`, également disjoint du
dossier d'installation.

**Réserve documentée :** une *désinstallation* ne supprime pas non plus les
préférences ; elles restent orphelines. C'est le comportement usuel des
applications de bureau, et c'est assumé.

## 3. Décisions

| # | Décision | Alternative écartée |
|---|---|---|
| D47 | Stockage en **PortableText** | NativeText — illisible en changeant de plateforme (§2.1) |
| D48 | **Version de schéma** dès la v1 | Aucune — un format qui évolue casserait les réglages existants |
| D49 | Seuls les raccourcis **modifiés** sont stockés | Tous — figerait les défauts et empêcherait de les faire évoluer |
| D50 | Les actions destructrices sont **réassignables**, mais leur confirmation est **inconditionnelle** | Les figer — l'utilisateur a demandé « toutes les actions » |
| D51 | La géométrie restaurée est **validée contre les écrans** | La restaurer telle quelle — rouvrirait hors écran après débranchement d'un moniteur |
| D52 | Le filtre de refs est **exposé dans l'UI** avant d'être persisté | Persister un réglage inaccessible (§5.3) |

## 4. Architecture

```
core/
  settings.py      schéma, défauts, validation — AUCUN Qt   (nouveau)
  shortcuts.py     catalogue des actions, détection de conflits (nouveau)
ui/
  settings_store.py    pont QSettings                        (nouveau)
  shortcuts_window.py  liste et édition                      (nouveau)
  main_window.py       lit le catalogue, restaure/sauve      (modifié)
  graph_view.py        expose et restaure le zoom            (modifié)
```

`test_architecture.py` interdit à `core/` d'importer Qt. La validation
travaille donc sur des **chaînes portables**, jamais sur `QKeySequence` —
ce que D47 impose de toute façon. C'est aussi ce qui la rend testable sans
fenêtre.

`main_window.py` fait déjà 1098 lignes : la fenêtre des raccourcis prend son
propre fichier.

## 5. Ce qui est persisté

| Clé | Contenu | Défaut |
|---|---|---|
| `settings/version` | version du schéma | `1` |
| `window/geometry` | taille et position | celle de Qt |
| `view/zoom` | zoom du graphe | `1.0` |
| `view/panel_width` | largeur du panneau latéral | répartition actuelle |
| `view/show_tags` | filtre d'affichage des tags | `True` |
| `recent/repositories` | N derniers dépôts ouverts | `[]` |
| `shortcuts/<action>` | **uniquement les raccourcis modifiés** | absent |

### 5.1 Pourquoi une version de schéma (D48)

Sans elle, ajouter une clé ou changer un type casse les réglages des
utilisateurs déjà installés — et §2.2 garantit précisément que ces réglages
survivent aux mises à jour. Une version inconnue (issue d'une version plus
récente) fait repartir des défauts plutôt que planter.

### 5.2 Pourquoi seulement les écarts (D49)

Stocker les dix raccourcis figerait les défauts dans le fichier de
l'utilisateur : changer un défaut plus tard n'aurait aucun effet chez lui.
En ne stockant que ce qu'il a modifié, un défaut peut évoluer sans écraser
son choix.

### 5.3 Le filtre de refs n'existe pas encore dans l'UI (D52)

Vérifié : `GraphOptions` porte cinq filtres (`show_local_branches`,
`show_remote_branches`, `show_tags`, `show_stashes`, `show_junctions`) et
**aucun n'est exposé dans `ui/`**. Persister `show_tags` suppose donc
d'abord de créer le contrôle.

Le périmètre retenu est `show_tags` seul — celui que l'utilisateur a
nommé. Les quatre autres restent à leurs défauts mesurés, que le commentaire
de `options.py` justifie et qu'il ne faut pas remettre en cause ici.

## 6. Les raccourcis

### 6.1 Catalogue

Les dix raccourcis actuels quittent le littéral de `main_window.py` pour un
catalogue dans `core/shortcuts.py` : identifiant stable, libellé, défaut
portable, caractère destructeur.

L'**identifiant** est stable et distinct du libellé : renommer un libellé ne
doit pas perdre le raccourci que l'utilisateur a choisi.

`StandardKey.Refresh` donne **F5 même sur macOS** (mesuré), ce qui n'y est
pas une convention. Le défaut est conservé tel quel — le changer sous
l'utilisateur serait une régression de comportement — mais il devient
modifiable, ce qui règle le problème pour qui le souhaite.

### 6.2 Affichage

Une fenêtre « Keyboard Shortcuts » liste les actions, groupées, avec leur
séquence en **NativeText** (⌘F sur Mac, Ctrl+F sur Windows). L'affichage est
natif, le stockage portable (D47).

### 6.3 Édition et refus

Trois refus, tous testables comme fonctions pures :

1. **Conflit** — deux actions ne peuvent partager une séquence. Le conflit
   est signalé en nommant l'action déjà titulaire.
2. **Séquence réservée** — ⌘Q, ⌘W, ⌘Tab et leurs équivalents Windows sont
   refusés : les réassigner rendrait l'application inutilisable.
3. **Séquence vide ou invalide** — refusée.

Un « Reset to defaults » est disponible en permanence, par action et global.

### 6.4 Les actions destructrices (D50)

L'utilisateur a demandé que **toutes** les actions soient réassignables. Le
risque est réel : un `Ctrl+D` réassigné sur « Drop stash » et frappé par
réflexe détruirait du travail.

**La protection ne passe PAS par un drapeau.** `MenuEntry.needs_confirmation`
existe déjà et sa docstring documente son échec : en phase 11, « Drop stash »
portait ce drapeau, un test l'affirmait, et le stash était pourtant détruit
même quand l'utilisateur refusait — parce que `confirmation_for` n'avait pas
de branche `drop_stash`. **Poser un drapeau ne protège rien.**

La garantie est donc : **toute action destructrice déclenchée au clavier
passe par `confirmation_for`, exactement comme au menu**. Un test vérifie
qu'aucun chemin clavier ne contourne cette fonction — c'est l'assertion
centrale de cette section.

## 7. Ce qui ne doit pas se dégrader

**Le rendu du graphe est validé par l'utilisateur** (mémoire du projet).
Cette phase ne touche ni les couleurs, ni les courbes, ni les flèches, ni la
mise en page. Elle restaure un niveau de zoom et une largeur de panneau —
des réglages de vue, pas de rendu.

**La garantie de lecture seule (§7.0)** est intacte : les préférences vivent
hors du dépôt. Aucune écriture supplémentaire dans `.git`. Un test vérifie
que le dossier d'installation ne reçoit jamais de préférences.

## 8. Tests

- **Un aller-retour conserve chaque réglage** — écrit, relu, identique.
- **Le stockage est portable** : la valeur enregistrée pour `Ctrl+F` est
  `"Ctrl+F"`, jamais `"⌘F"`. C'est le test qui protège le multiplateforme.
- **Une version de schéma inconnue retombe sur les défauts** sans lever.
- **Un fichier de préférences absent, vide ou corrompu** donne les défauts.
- **Seuls les raccourcis modifiés sont écrits** — après reset, la clé
  disparaît au lieu de contenir le défaut.
- **Un conflit est refusé** et nomme l'action déjà titulaire.
- **Une séquence réservée (⌘Q) est refusée.**
- **Une action destructrice déclenchée au clavier passe par
  `confirmation_for`** — et un « Non » ne détruit rien. C'est l'assertion
  centrale (§6.4), celle qui distingue cette phase de la régression de la
  phase 11.
- **Une géométrie hors des écrans disponibles est ignorée** au profit du
  défaut (D51).
- **Les préférences survivent à une réinstallation** — le test encode §2.2.
- **Aucune préférence n'est écrite dans le dossier d'installation.**
- **Le rendu du graphe est inchangé** : les tests de `graph_items` et de
  `theme` restent verts sans modification.

## 9. Hors périmètre

- **Le mode sombre** — chantier distinct, qui touche la palette validée.
- **Les quatre autres filtres de `GraphOptions`** — leurs défauts sont
  mesurés et justifiés ; seul `show_tags` a été demandé.
- **Des raccourcis par dépôt** — complexité sans besoin exprimé.
- **L'import/export de profils de réglages.**
- **La suppression des préférences à la désinstallation** (§2.2).
