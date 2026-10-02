# tortoisePy — Design, phase 24 : plus aucune action ne gèle l'interface

**Date :** 2026-10-02
**Statut :** brouillon, en attente de relecture

## 1. Problème

Demandé par l'utilisateur : « à chaque fois qu'une action est susceptible de
faire freezer l'app pendant quelques secondes, on la fait en arrière-plan
avec un loader ».

Trois opérations réseau le font déjà — fetch, push, pull. **Tout le reste est
synchrone**, et gèle l'interface le temps du calcul.

## 2. Ce qui gèle, mesuré

Sur le dépôt réel de l'utilisateur (713 refs, ~1000 nœuds) :

| Opération | Coût | Déclenchée par |
|---|---|---|
| `build_graph` | **2185 ms** | ouverture, rafraîchissement, bascule du filtre |
| `list_changes` | **~760 ms** | fenêtre de commit |
| `read_state` | **436 ms** | ouverture, après chaque action |
| `diff_for` | **~385 ms** | clic sur un fichier |
| `commits_for_node` | 292 ms | clic sur un nœud |

Sur un petit dépôt, les mêmes opérations coûtent 3 à 100 ms : le gel ne se
manifeste qu'à l'échelle. C'est pourquoi le seuil doit être une **règle**, et
non une liste figée.

## 3. Décisions

| # | Décision | Alternative écartée |
|---|---|---|
| D58 | **Seuil à 300 ms** : au-delà, l'opération part en arrière-plan | Tout basculer — un fil pour 5 ms est de la complexité pure |
| D59 | **Barre de progression indéterminée**, interface utilisable | Fenêtre vide puis remplie — l'utilisateur a choisi la première |
| D60 | **Une seule opération de fond à la fois** ; la seconde demande est ignorée | Annuler et relancer — plus de code pour annuler proprement |
| D61 | Les opérations **d'écriture** restent synchrones | Les basculer aussi — §5.2 |
| D62 | Un worker **générique**, pas un par opération | Dupliquer `FetchWorker` cinq fois |

### 3.1 Pourquoi un seuil et non une liste (D58)

Les coûts dépendent du dépôt : `build_graph` met 7 ms ici et 2185 ms sur
`vti`. Figer une liste d'opérations « lentes » serait faux sur l'un ou
l'autre. La règle est : **toute opération de LECTURE dont le coût croît avec
la taille du dépôt** passe en arrière-plan.

### 3.2 Pourquoi les écritures restent synchrones (D61)

Un commit, un checkout, un cherry-pick modifient le dépôt. Les lancer en
arrière-plan ouvrirait la porte à deux écritures concurrentes, et la
garantie §7.0 (« l'app n'écrit que sur action explicite ») deviendrait
difficile à tenir.

Elles sont par ailleurs rapides : ce qui coûte, c'est le **rafraîchissement
qui suit** — et lui est une lecture, donc couvert.

## 4. Ce qui bascule

```
Lecture, coût croissant          -> arrière-plan
  build_graph (via refresh)
  list_changes  (fenêtre de commit)
  diff_for      (clic sur un fichier)
  commits_for_node (panneau latéral)
  blame         (fenêtre de blame)

Écriture ou coût constant        -> inchangé
  commit, checkout, cherry-pick, reset…
  copier un SHA, ouvrir les raccourcis
```

## 5. Architecture

```
ui/
  tasks.py        `CallableWorker` — exécute n'importe quel appelable  (nouveau)
                  `BackgroundTask` — inchangé, déjà générique
  main_window.py  `run_in_background(appelable, suite, libelle)`       (modifié)
```

`BackgroundTask` est déjà générique : seul `FetchWorker` est spécifique. Un
`CallableWorker` qui exécute un `Callable[[], Any]` et émet son résultat
suffit — les cinq opérations passent par lui (D62).

```python
def run_in_background(self, appelable, suite, libelle: str) -> bool:
    """Lance `appelable` hors du fil principal, puis appelle `suite`.

    Rend `False` si une opération tourne déjà (D60).
    """
```

### 5.1 Le piège du QThread

Déjà rencontré en phase 10 : « QThread: Destroyed while thread is still
running ». `BackgroundTask.stop()` (quit puis wait) le traite, et
`closeEvent` l'appelle déjà. Le réutiliser tel quel évite de refaire
l'erreur.

### 5.2 Ce qui ne doit pas changer

- **La garantie de lecture seule (§7.0)** : aucune écriture nouvelle.
- **Le rendu du graphe** : ni couleurs, ni courbes, ni flèches.
- **Les trois opérations réseau** gardent leur chemin actuel, qui marche.

## 6. Tests

- **Une opération lente ne bloque pas l'interface** : pendant son exécution,
  la fenêtre répond encore. C'est l'assertion centrale.
- **La barre de progression apparaît puis disparaît** — y compris quand
  l'opération échoue, sinon elle resterait affichée indéfiniment.
- **Une seconde demande est ignorée** tant que la première tourne (D60), et
  la première n'est pas perturbée.
- **Le résultat arrive dans le fil principal** : la suite peut toucher
  l'interface sans risque.
- **Une exception dans l'opération** est rapportée, pas avalée — et la barre
  disparaît quand même.
- **Fermer la fenêtre pendant une opération** ne laisse pas de `QThread`
  détruit en pleine exécution (le défaut de la phase 10).
- **Les opérations d'écriture restent synchrones** : leur résultat est
  disponible au retour de l'appel.

## 7. Hors périmètre

- **Annuler une opération en cours** — l'utilisateur a choisi « ignorer la
  seconde demande » plutôt que « annuler et relancer ».
- **Plusieurs opérations de fond simultanées** — une à la fois (D60).
- **Une barre de progression déterminée** pour les opérations locales : leur
  avancement n'est pas mesurable sans instrumenter pygit2.
