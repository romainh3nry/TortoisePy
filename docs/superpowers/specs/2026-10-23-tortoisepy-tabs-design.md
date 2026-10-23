# Onglets — plusieurs dépôts dans une fenêtre

**Date :** 2026-10-23
**Statut :** spec à valider — aucun code écrit
**Modules visés :** `ui/main_window.py` (2705 lignes, 89 méthodes),
`ui/repository_panel.py` (à créer)

---

## 1. Pourquoi

Demandé par l'utilisateur, après la livraison du menu « Windows » :

> « on aurait pas pu faire des onglets qu'un menu avec liste ? »

Le menu répond à la question « combien de graphes sont ouverts ? » en
un clic. Des onglets y répondent **sans clic** : la réponse est
affichée en permanence. Pour l'usage décrit — jongler entre plusieurs
dépôts — c'est la meilleure réponse, et je ne l'avais pas proposée.

Le menu « Windows » est **conservé** (décision de l'utilisateur) : il
reste le seul moyen d'atteindre une fenêtre ouverte depuis le
terminal, qui n'est pas un onglet (§3).

## 2. Ce que mesure l'état actuel

Chiffres relevés sur le code, non estimés.

| Mesure | Valeur |
|---|---|
| `main_window.py` | 2705 lignes, 89 méthodes |
| `self.repository` | 45 occurrences |
| `self.view` | 34 |
| `self.statusBar` | 37 |
| `self.graph` | 15 |
| Constructions `MainWindow(...)` dans les tests | **114, sur 27 fichiers** |
| Accès des tests | `.view` ×123, `.graph` ×47, `.repository` ×43, `.refresh()` ×22 |

**Le problème n'est pas le `QTabWidget`.** C'est que `MainWindow`
**est** la vue d'un dépôt dans tout le code et tous les tests. Les
onglets demandent de séparer deux rôles aujourd'hui confondus : le
**cadre** (fenêtre, barre d'outils, géométrie) et le **panneau**
(graphe, dépôt, liste des commits).

### Ce qui facilite

Le contenu propre à un dépôt est **déjà** une unité assemblée en un
seul endroit :

```python
central = QWidget()
disposition = QVBoxLayout(central)
disposition.addWidget(self._banner)      # bandeau d'opération
disposition.addWidget(self.splitter)     # graphe + liste
self.setCentralWidget(central)
```

C'est `central` qui devient un onglet. Le découpage n'est pas à
inventer, il existe.

La table `slots` de `_build_actions` centralise déjà les cibles des
actions — un seul point de passage à rebrancher, pas vingt.

L'état se sépare proprement :

| Par dépôt (va dans l'onglet) | Par fenêtre (reste au cadre) |
|---|---|
| `repository`, `graph`, `state` | `window/geometry` |
| `watcher`, `_task` | `view/panel_width`, `view/panel_hidden` |
| `_head_avant_refresh` | `view/show_tags`, `view/zoom` |
| `_selection_avant_refresh` | `view/workdir` |
| `_dernier_motif_branche` | |

### Ce qui complique

**La poignée de repli du panneau.** Elle est parentée à la FENÊTRE,
pas au splitter, et le commentaire du code dit pourquoi : `QSplitter`
adopte tout enfant comme widget géré, et la poignée y redevenait une
colonne de 18 px — la « bordure trop épaisse » signalée par
l'utilisateur. Avec des onglets, elle doit suivre l'onglet actif
**sans** redevenir une colonne. C'est le point qui touche au rendu
validé, et il est protégé par `test_panel_toggle.py`, qui compte les
teintes réellement peintes.

**`closeEvent` arrête un `QThread` et un watcher par dépôt.** Fermer
un onglet doit faire ce travail pour ce dépôt seulement. Se tromper
rend « QThread: Destroyed while thread is still running » — un défaut
déjà rencontré dans ce projet, dont le correctif est documenté dans
`closeEvent`.

## 3. Décisions prises

| Question | Décision | Conséquence |
|---|---|---|
| Barre d'outils | **Une seule, globale**, agissant sur l'onglet actif | Le gros du travail : rebrancher la table `slots` |
| `topy <chemin>` | **Nouvelle fenêtre, inchangé** | Deux comportements (comme VSCode) ; pas de canal entre processus à construire |
| Dernier onglet fermé | **La fenêtre se ferme** | Pas d'état « fenêtre vide » à dessiner |
| Menu « Windows » | **Conservé** | Seul moyen d'atteindre une fenêtre lancée au terminal |

## 4. Architecture proposée

```
MainWindow (le cadre)
├── barre d'outils          ← globale, agit sur l'onglet actif
├── QTabWidget
│   ├── RepositoryPanel(vti)        ← bandeau + splitter(graphe, liste)
│   ├── RepositoryPanel(crm)
│   └── RepositoryPanel(airflow)
└── barre d'état            ← globale, reflète l'onglet actif
```

### La façade, pour ne pas réécrire 114 tests

`MainWindow` expose `.view`, `.repository`, `.graph`, `.state`,
`.refresh()` comme **propriétés déléguant à l'onglet actif**.
`MainWindow(depot)` continue d'ouvrir un premier onglet, donc les 114
constructions existantes et leurs 235 accès continuent de fonctionner
sans modification.

C'est ce qui rend le chantier faisable : sans la façade, il faudrait
réécrire 27 fichiers de tests, et la non-régression deviendrait
invérifiable.

## 5. Étapes

Chaque étape laisse la suite verte et le rendu intact.

1. **Extraire `RepositoryPanel`** — déplacer le contenu par dépôt hors
   de `MainWindow`, qui le garde comme widget central unique. Aucun
   onglet encore : l'aspect doit être **identique au pixel**, et les
   1852 tests passent sans modification. C'est l'étape qui porte le
   risque.
2. **Introduire le `QTabWidget`** avec les propriétés de façade. Un
   seul onglet, barre d'onglets masquée quand il est seul : l'aspect ne
   change toujours pas.
3. **Rebrancher la barre sur l'onglet actif** — la table `slots`, la
   barre d'état, le titre de la fenêtre.
4. **Ouvrir en onglet** depuis « Open Project » et « Open Recent »,
   fermeture, titre d'onglet, et la poignée de repli qui suit l'onglet.

## 6. Ce qui garantit la non-régression

Le rendu actuel est validé à l'œil et protégé par la mémoire du
projet : *« ne jamais dégrader l'aspect actuel »*.

- `test_panel_toggle.py` compte les teintes réellement peintes de la
  poignée — c'est lui qui attrapera la bordure épaisse si elle
  revient ;
- `test_visual_contract.py` épingle les valeurs de rendu ;
- `test_syntax_in_diff.py` et `test_syntax_everywhere.py` lisent des
  pixels, pas des intentions ;
- l'étape 1 impose un aspect **identique** avant toute introduction
  d'onglet : c'est le point de contrôle qui rend les suivantes sûres.

**Critère d'acceptation de chaque étape :** 1852 tests verts, et
aucune modification des tests existants — une modification signalerait
que la façade ne tient pas sa promesse.

## 7. Ce que cette spec ne couvre pas

- **Détacher un onglet** en fenêtre par glissement. Attendu d'une
  interface à onglets, mais ajoutable après sans rien casser.
- **Restaurer les onglets au lancement**. Demanderait un réglage
  `window/tabs` et une décision sur les dépôts disparus.
- **`topy` rejoignant une fenêtre existante** (§3) : demanderait un
  canal entre processus.
