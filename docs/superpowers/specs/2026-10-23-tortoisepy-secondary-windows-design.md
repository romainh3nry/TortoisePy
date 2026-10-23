# Fenêtres secondaires — journal, comparaison, fusion, écran d'attente

**Date :** 2026-10-23 (rétrospective — construit entre le 5 et le 16
octobre)
**Modules :** `ui/log_window.py`, `ui/compare_window.py`,
`ui/merge_editor.py`, `ui/splash.py`, `ui/child_windows.py`,
`core/log.py`

> **Spec rétrospective.** Ces fenêtres ont été construites en
> conversation directe. Ce texte les écrit après coup pour qu'une
> reconstruction les retrouve.

---

## 1. Le journal (`log_window`, `core/log.py`)

### Pourquoi

Deux entrées du menu contextuel **mentaient** : `show_log` rendait un
succès vide, et l'historique d'un fichier n'existait pas. Une commande
qui ne fait rien tout en signalant une réussite est pire qu'une
commande absente — l'utilisateur cherche son résultat.

### Une fenêtre pour deux usages

La liste, la recherche et le rendu sont communs ; seule la source
change :

- une **ref** — les commits d'une branche
- un **chemin** — les commits qui ont touché ce fichier

Deux fenêtres auraient divergé à la première correction.

### Le point difficile : « ce commit a-t-il touché ce fichier ? »

Comparer les **identifiants de blob**, et non les dates ou les
messages. Un commit de fusion dont le blob est identique à celui du
premier parent n'a pas modifié le fichier, même s'il le mentionne.

Le cas de la **suppression** est celui qu'on oublie : le blob passe de
« existe » à « absent », ce qui est bien une modification. Un test le
couvre, et un mutant le prouve — sans lui, les suppressions
disparaissaient du journal.

`DEFAULT_LIMIT = 100` : au-delà, la fenêtre serait illisible et le
calcul inutile.

## 2. La comparaison (`compare_window`)

Même défaut d'origine : « Compare revisions » était câblé sur
`_not_available`.

Deux révisions sélectionnées dans le graphe, `git diff A B` affiché
avec la coloration syntaxique et le diff au mot. **L'ordre compte** :
A → B et B → A ne donnent pas le même résultat, et l'ordre est celui de
la sélection, pas celui de l'historique.

## 3. L'éditeur de fusion (`merge_editor`)

### Pourquoi — le cas que la fenêtre de conflits ne couvre pas

Signalé après un rebase réel, où deux clés YAML indépendantes —
`rate-limit:` et `twoFactorAuth:` — étaient marquées en conflit parce
qu'adjacentes :

> « j'aimerai que les deux blocs qui causent le conflit soient
> présents, sauf qu'en l'état on me propose uniquement l'un ou
> l'autre »

Choisir un camp par fichier couvre la majorité des cas. Pas celui-ci :
**garder les deux**.

### Trois colonnes

```
yours  |  résultat  |  theirs
```

Les deux côtés sont en **lecture seule** : ce sont des références. Les
rendre modifiables laisserait croire qu'on peut y écrire, alors que
seule la colonne du milieu est enregistrée.

La colonne centrale est éditable, d'où `QSyntaxHighlighter` plutôt que
des formats posés une fois — voir la spec d'affichage du code.

### Ce que la reconstruction doit préserver

- **Les marqueurs `<<<<<<<` doivent disparaître** quand on choisit un
  côté. Signalé par l'utilisateur : ils restaient dans le résultat.
- Enregistrer écrit le fichier **et** marque le conflit résolu. L'un
  sans l'autre laisse un dépôt dans un état que l'utilisateur ne
  comprend pas.
- La coloration ne doit pas toucher au **texte** enregistré, seulement
  à son format. Un test le vérifie en relisant le fichier.

## 4. L'écran d'attente (`splash`)

### Pourquoi

`build_graph` coûte **1 522 ms sur un dépôt de 935 nœuds** (mesuré).
Pendant ce temps, rien ne s'affichait : l'application paraissait ne pas
démarrer.

### Quand l'afficher

`should_show_splash` compte les **refs**, il ne mesure pas : construire
le graphe pour savoir s'il faut annoncer sa construction serait
absurde. Le comptage coûte 9 ms sur 650 refs.

Sur un petit dépôt, l'écran clignoterait pour rien — et le mode
synchrone évite un aller-retour entre fils pour 17 ms.

### Les trois pièges, tous rencontrés

| Piège | Conséquence | Correction |
|---|---|---|
| Pas de `processEvents` après `show()` | l'écran est créé mais jamais peint | appeler `processEvents` |
| Écran sans `defer_graph` | le fil principal est bloqué, l'écran ne se peint pas | les deux vont ensemble |
| `graph_ready` émis avant la connexion | l'écran reste affiché pour toujours | si le graphe est déjà là, fermer directement |

Le dernier est subtil : quand le report en arrière-plan ne peut pas
démarrer (verrou pris), la construction se fait dans le constructeur,
et `graph_ready` part avant que l'appelant ne s'y abonne.

### Où l'écran doit apparaître

Au lancement en ligne de commande, **et** à l'ouverture d'un projet
depuis l'interface — « Open Project » comme « Open Recent ». Les trois
chemins passent par une méthode commune, et un test interdit à chacun
de construire sa propre fenêtre : deux copies divergeraient à la
première correction.

## 5. Le registre de fenêtres (`child_windows`)

### Pourquoi

Quatre listes et quatre méthodes `_forget_*` quasi identiques vivaient
dans `MainWindow`, qui atteignait **1 999 lignes et 79 méthodes** — le
fichier où le plus de régressions sont apparues.

### Ce qu'il résout

Une fenêtre fille sans référence est **détruite par le ramasse-miettes
aussitôt ouverte**. Les garder toutes les ferait s'accumuler.

`ChildWindows` retient, oublie à la fermeture, et vérifie la validité
avec `shiboken6.isValid` — un objet Qt détruit côté C++ laisse un
objet Python vivant qui lèvera à la première méthode appelée.
