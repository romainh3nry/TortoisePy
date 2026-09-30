# Blame Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Voir qui a écrit chaque ligne d'un fichier, et sauter au commit qui
l'a écrite.

**Architecture:** `core/blame.py` annote un fichier à partir d'un commit donné,
en lisant l'arbre de ce commit. `ui/blame_window.py` l'affiche, une ligne par
ligne, et émet l'OID au clic. La fenêtre de détail y mène par un clic droit.

**Tech Stack:** Python 3.13, pygit2 1.20.1, PySide6 6.11.2, pytest.

**Spec:** `docs/superpowers/specs/2026-09-30-tortoisepy-blame-design.md`

## Global Constraints

- **Ne jamais lancer de commande git sur CE dépôt** (add, commit, branch,
  checkout, stash, push, reset). L'utilisateur gère git lui-même. `git` dans un
  dépôt jetable sous `tmp_path` est attendu et normal.
- **Ne pas modifier** `src/tortoisepy/ui/theme.py`, `src/tortoisepy/layout/**`,
  `src/tortoisepy/ui/graph_items.py` — cette phase n'approche pas le graphe.
- `src/tortoisepy/core/**` n'importe jamais Qt (`tests/test_architecture.py`).
- **§7.0** : blâmer ne doit rien écrire.
- Commentaires et docstrings **en français**, expliquant le *pourquoi*.
- **Libellés : français dans les fenêtres** (`commit_detail_window.py` dit
  déjà « Fichier »), anglais dans la barre de statut et les menus principaux.

## Review Focus

1. **Le contenu vient de l'arbre du commit, pas du disque.** Vérifié : au
   commit ancien le fichier vaut `['A','B','C']` alors que le disque porte
   `['A','B par Bob','C','D non commitee']`. Lire le disque afficherait des
   lignes que le blâme n'a pas annotées.
2. **L'auteur, pas le committer** (spec §5) — `hunk.final_committer` existe et
   serait le mauvais choix : il peut désigner qui a appliqué un patch.
3. **Le blâme part du commit demandé** (D29) — `newest_commit=` ; vérifié, sans
   lui on blâmerait HEAD et on verrait des modifications postérieures.
4. **Fichier binaire** — libgit2 ne lève pas, il rend un bloc unique inutile.
   Il faut le détecter (`blob.is_binary`, vérifié disponible).
5. **La fenêtre doit être retenue par son parent** — sinon Python la ramasse
   aussitôt ouverte (défaut vécu en phase 6, voir `_detail_windows`).

---

### Task 1: `core/blame.py`

**Files:**
- Create: `src/tortoisepy/core/blame.py`
- Test: `tests/core/test_blame.py`

**Interfaces:**
- Produces:
  - `BlameLine` — `number`, `text`, `oid`, `short_oid`, `author`, `when`, `summary`
  - `blame_file(repo, path, oid) -> tuple[BlameLine, ...] | BlameError`
  - `BlameError` — `reason: str`

**Vérifié sur pygit2 1.20 (ne pas redécouvrir) :**
- `repo.blame(path, newest_commit=...)` rend des hunks portant
  `final_start_line_number`, `lines_in_hunk`, `final_commit_id` ;
- **les numéros de ligne commencent à 1** ;
- un chemin absent du commit lève `NotFoundError` ;
- `blob.is_binary` existe et répond juste ;
- coût mesuré : **42 ms** sur un fichier à 3 000 révisions.

- [ ] **Step 1: Écrire les tests**

```python
# tests/core/test_blame.py
import os
import subprocess

import pygit2
import pytest

from tortoisepy.core.blame import BlameError, blame_file


def run_git(path, *args, auteur="Alice"):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": auteur, "GIT_AUTHOR_EMAIL": f"{auteur}@x",
        "GIT_COMMITTER_NAME": auteur, "GIT_COMMITTER_EMAIL": f"{auteur}@x",
    }
    return subprocess.run(
        ["git", *args], cwd=path, env=env, capture_output=True, text=True
    )


@pytest.fixture
def repo(tmp_path):
    """Trois lignes d'Alice, dont une réécrite par Bob."""
    path = tmp_path / "d"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "f.txt").write_text("A\nB\nC\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "premier jet")

    (path / "f.txt").write_text("A\nB par Bob\nC\n")
    run_git(path, "commit", "-q", "-am", "Bob modifie B", auteur="Bob")
    return pygit2.Repository(str(path))


def _tete(repo):
    return str(repo.head.target)


def test_each_line_is_attributed_to_its_author(repo):
    """Spec §5 : l'auteur, pas le committer."""
    lignes = blame_file(repo, "f.txt", _tete(repo))
    assert not isinstance(lignes, BlameError)
    assert [l.author for l in lignes] == ["Alice", "Bob", "Alice"]
    assert [l.text for l in lignes] == ["A", "B par Bob", "C"]
    assert [l.number for l in lignes] == [1, 2, 3]


def test_every_line_carries_its_commit(repo):
    lignes = blame_file(repo, "f.txt", _tete(repo))
    assert lignes[1].summary == "Bob modifie B"
    assert lignes[0].summary == "premier jet"
    assert len(lignes[1].short_oid) == 8
    assert lignes[1].oid != lignes[0].oid


def test_blaming_from_an_older_commit_ignores_later_changes(repo):
    """D29, et Review Focus 3 : sans `newest_commit`, on blâmerait HEAD."""
    ancien = [
        c
        for c in repo.walk(repo.head.target, pygit2.GIT_SORT_TOPOLOGICAL)
        if "premier jet" in c.message
    ][0]

    lignes = blame_file(repo, "f.txt", str(ancien.id))
    assert not isinstance(lignes, BlameError)
    assert [l.author for l in lignes] == ["Alice", "Alice", "Alice"]
    assert [l.text for l in lignes] == ["A", "B", "C"], (
        "le contenu doit venir de l'arbre du commit"
    )


def test_the_content_comes_from_the_tree_not_the_disk(repo):
    """Review Focus 1 : le disque peut porter des lignes non commitées."""
    chemin = os.path.join(repo.workdir, "f.txt")
    with open(chemin, "a") as fichier:
        fichier.write("D jamais commitee\n")

    lignes = blame_file(repo, "f.txt", _tete(repo))
    assert len(lignes) == 3, "la ligne non commitée ne doit pas apparaître"


def test_a_file_absent_from_the_commit_is_refused(repo):
    resultat = blame_file(repo, "fantome.txt", _tete(repo))
    assert isinstance(resultat, BlameError)
    assert "fantome.txt" in resultat.reason


def test_a_binary_file_is_refused_with_a_clear_reason(repo):
    """libgit2 ne lève pas : il rend un bloc unique et inutile."""
    chemin = os.path.join(repo.workdir, "bin.dat")
    with open(chemin, "wb") as fichier:
        fichier.write(b"\xff\xfe\x00binaire\n")
    run_git(repo.workdir, "add", "bin.dat")
    run_git(repo.workdir, "commit", "-q", "-m", "binaire")

    fresh = pygit2.Repository(repo.path)
    resultat = blame_file(fresh, "bin.dat", str(fresh.head.target))
    assert isinstance(resultat, BlameError)
    assert "binary" in resultat.reason.lower()


def test_an_empty_file_yields_no_lines(repo):
    chemin = os.path.join(repo.workdir, "vide.txt")
    open(chemin, "w").close()
    run_git(repo.workdir, "add", "vide.txt")
    run_git(repo.workdir, "commit", "-q", "-m", "vide")

    fresh = pygit2.Repository(repo.path)
    resultat = blame_file(fresh, "vide.txt", str(fresh.head.target))
    assert resultat == ()


def test_blaming_writes_nothing(repo):
    """§7.0."""
    import hashlib

    def empreinte():
        h = hashlib.sha256()
        for racine, _, fichiers in os.walk(os.path.join(repo.workdir, ".git")):
            for f in sorted(fichiers):
                p = os.path.join(racine, f)
                h.update(p.encode())
                try:
                    h.update(str(os.stat(p).st_mtime_ns).encode())
                except OSError:
                    pass
        return h.hexdigest()

    avant = empreinte()
    blame_file(repo, "f.txt", _tete(repo))
    assert empreinte() == avant
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/core/test_blame.py -q`
Expected: FAIL — le module n'existe pas.

- [ ] **Step 3: Implémenter**

```python
"""Qui a écrit chaque ligne — phase 14.

Le blâme **lit** : c'est la première fonctionnalité depuis longtemps qui
n'ajoute aucune opération destructrice, et elle ne peut pas faire perdre
de travail.

Mesuré : 42 ms sur un fichier à 3 000 révisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pygit2


@dataclass(frozen=True)
class BlameLine:
    """Une ligne, et le commit qui l'a écrite."""

    number: int
    text: str
    oid: str
    short_oid: str
    author: str
    when: datetime
    summary: str


@dataclass(frozen=True)
class BlameError:
    """Pourquoi ce fichier ne peut pas être blâmé."""

    reason: str


def blame_file(
    repo: pygit2.Repository, path: str, oid: str
) -> tuple[BlameLine, ...] | BlameError:
    """Annote un fichier tel qu'il était au commit `oid`.

    **Le contenu vient de l'arbre du commit, pas du disque** : vérifié,
    le fichier de travail peut porter des lignes non commitées que le
    blâme n'annote pas, et les afficher laisserait croire qu'elles sont
    sans auteur.

    **On retient l'auteur du commit**, pas `hunk.final_committer` : le
    committer peut être celui qui a appliqué un patch écrit par un autre.

    Rend un `BlameError` plutôt que de lever : l'appelant est une
    fenêtre, qui doit afficher la raison.
    """
    try:
        commit = repo.get(oid)
        if commit is None:
            return BlameError(reason=f"unknown commit: {oid[:8]}")
        entry = commit.tree[path]
    except (KeyError, pygit2.GitError, ValueError):
        return BlameError(reason=f"'{path}' is not in this commit")

    blob = repo.get(entry.id)
    if blob is None:
        return BlameError(reason=f"'{path}' cannot be read")

    # libgit2 ne lève pas sur un binaire : il rend un bloc unique et
    # inutile. Mieux vaut le dire que d'afficher des octets comme du
    # texte.
    if blob.is_binary:
        return BlameError(reason=f"'{path}' is a binary file")

    contenu = blob.data.decode("utf-8", errors="replace").splitlines()
    if not contenu:
        return ()

    try:
        blame = repo.blame(path, newest_commit=commit.id)
    except (pygit2.GitError, KeyError, ValueError) as erreur:
        return BlameError(reason=str(erreur))

    # Un commit par ligne, indexé : les hunks couvrent des plages, et
    # l'affichage veut une ligne à la fois.
    par_ligne: dict[int, pygit2.Commit] = {}
    for hunk in blame:
        origine = repo.get(hunk.final_commit_id)
        if origine is None:
            continue
        for decalage in range(hunk.lines_in_hunk):
            par_ligne[hunk.final_start_line_number + decalage] = origine

    lignes: list[BlameLine] = []
    for numero, texte in enumerate(contenu, start=1):
        origine = par_ligne.get(numero)
        if origine is None:
            # Une ligne que le blâme ne couvre pas : la montrer sans
            # auteur plutôt que de la taire.
            lignes.append(
                BlameLine(
                    number=numero, text=texte, oid="", short_oid="",
                    author="", when=datetime.fromtimestamp(0, timezone.utc),
                    summary="",
                )
            )
            continue

        lignes.append(
            BlameLine(
                number=numero,
                text=texte,
                oid=str(origine.id),
                short_oid=str(origine.id)[:8],
                author=origine.author.name,
                when=datetime.fromtimestamp(
                    origine.author.time, timezone.utc
                ),
                summary=origine.message.strip().splitlines()[0]
                if origine.message.strip()
                else "",
            )
        )

    return tuple(lignes)
```

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/core/test_blame.py -q`
Expected: PASS.

- [ ] **Step 5: Signaler les fichiers prêts** — ne commite pas.

---

### Task 2: La fenêtre et son entrée

**Files:**
- Create: `src/tortoisepy/ui/blame_window.py`
- Modify: `src/tortoisepy/ui/commit_detail_window.py`
- Test: `tests/ui/test_blame_window.py`

**Interfaces:**
- Consumes: `blame_file`, `BlameLine`, `BlameError` (tâche 1)
- Produces: `BlameWindow(repository, path, oid)` avec le signal
  `commit_activated(str)`

**Vérifié :** `commit_detail_window.py` a `self._files` (un `QTreeWidget`
listant les fichiers du commit), `self.repository` et `self.oid`. Ses libellés
sont **en français**.

**Piège à ne pas reproduire :** une fenêtre non retenue est ramassée par
Python aussitôt ouverte. `main_window.py` garde `_detail_windows: list` pour
cette raison exacte — faire de même.

- [ ] **Step 1: Écrire les tests**

```python
# tests/ui/test_blame_window.py
import os
import subprocess

import pygit2
import pytest

from tortoisepy.ui.blame_window import BlameWindow


def run_git(path, *args, auteur="Alice"):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": auteur, "GIT_AUTHOR_EMAIL": f"{auteur}@x",
        "GIT_COMMITTER_NAME": auteur, "GIT_COMMITTER_EMAIL": f"{auteur}@x",
    }
    return subprocess.run(
        ["git", *args], cwd=path, env=env, capture_output=True, text=True
    )


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "d"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "f.txt").write_text("A\nB\nC\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "premier jet")
    (path / "f.txt").write_text("A\nB par Bob\nC\n")
    run_git(path, "commit", "-q", "-am", "Bob modifie B", auteur="Bob")
    return pygit2.Repository(str(path))


def test_the_window_lists_every_line(qtbot, repo):
    fenetre = BlameWindow(repo, "f.txt", str(repo.head.target))
    qtbot.addWidget(fenetre)
    assert fenetre.line_count() == 3


def test_each_row_shows_its_author(qtbot, repo):
    fenetre = BlameWindow(repo, "f.txt", str(repo.head.target))
    qtbot.addWidget(fenetre)
    assert fenetre.author_at(1) == "Alice"
    assert fenetre.author_at(2) == "Bob"


def test_clicking_a_line_emits_its_commit(qtbot, repo):
    """D28 : « qui » puis « pourquoi »."""
    fenetre = BlameWindow(repo, "f.txt", str(repo.head.target))
    qtbot.addWidget(fenetre)

    with qtbot.waitSignal(fenetre.commit_activated, timeout=1000) as bloqueur:
        fenetre.activate_line(2)

    assert bloqueur.args[0] == fenetre.oid_at(2)


def test_a_binary_file_says_so_instead_of_showing_bytes(qtbot, repo):
    chemin = os.path.join(repo.workdir, "bin.dat")
    with open(chemin, "wb") as fichier:
        fichier.write(b"\xff\xfe\x00binaire\n")
    run_git(repo.workdir, "add", "bin.dat")
    run_git(repo.workdir, "commit", "-q", "-m", "binaire")

    fresh = pygit2.Repository(repo.path)
    fenetre = BlameWindow(fresh, "bin.dat", str(fresh.head.target))
    qtbot.addWidget(fenetre)

    assert fenetre.line_count() == 0
    assert "binary" in fenetre.message().lower()


def test_a_missing_file_says_why(qtbot, repo):
    fenetre = BlameWindow(repo, "fantome.txt", str(repo.head.target))
    qtbot.addWidget(fenetre)
    assert fenetre.line_count() == 0
    assert "fantome.txt" in fenetre.message()


def test_the_title_names_the_file_and_the_commit(qtbot, repo):
    fenetre = BlameWindow(repo, "f.txt", str(repo.head.target))
    qtbot.addWidget(fenetre)
    assert "f.txt" in fenetre.windowTitle()
    assert str(repo.head.target)[:8] in fenetre.windowTitle()
```

```python
# à ajouter dans tests/ui/test_commit_detail_window.py


def test_blame_is_offered_on_a_file(qtbot, window):
    """L'entrée n'a de sens que sur un fichier du commit."""
    entrees = window.context_actions_for_row(0)
    assert "Blame" in entrees


def test_blaming_opens_a_window_that_stays_alive(qtbot, window):
    """Review Focus 5 : une fenêtre non retenue est ramassée aussitôt.

    Le défaut a déjà été vécu en phase 6 — `main_window` garde
    `_detail_windows` pour cette raison.
    """
    import gc

    window.blame_row(0)
    gc.collect()

    assert window.blame_windows
    assert window.blame_windows[-1].isVisible()
```

- [ ] **Step 2: Vérifier l'échec**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_blame_window.py -q`
Expected: FAIL — le module n'existe pas.

- [ ] **Step 3: La fenêtre**

`BlameWindow` est un `QMainWindow` contenant un `QTreeWidget` à quatre
colonnes — **Commit**, **Auteur**, **Date**, **Ligne** — plus un `QLabel` pour
les messages d'erreur.

```python
class BlameWindow(QMainWindow):
    """Qui a écrit chaque ligne d'un fichier, à un commit donné."""

    commit_activated = Signal(str)
    """OID du commit d'origine de la ligne activée (D28)."""
```

- chaque ligne porte son OID dans `Qt.ItemDataRole.UserRole` ;
- les lignes d'un même commit partagent une teinte de fond, pour que les blocs
  se voient sans lire les SHA — alterner deux teintes discrètes à chaque
  changement de commit, **sans toucher à `theme.py`** ;
- `activate_line(n)`, `author_at(n)`, `oid_at(n)`, `line_count()`,
  `message()` sont les accès dont les tests ont besoin ;
- un `BlameError` remplit `message()` et laisse la liste vide.

Le titre : `f"Blame — {path} @ {oid[:8]}"`.

- [ ] **Step 4: L'entrée dans la fenêtre de détail**

Dans `commit_detail_window.py` :

- un menu contextuel sur `self._files` avec une entrée **« Blame »** ;
- `context_actions_for_row(index) -> tuple[str, ...]` pour que le test lise le
  menu sans l'ouvrir ;
- `blame_row(index)` ouvre la fenêtre, **la retient dans
  `self.blame_windows: list`**, et branche `commit_activated` sur l'ouverture
  d'un nouveau `CommitDetailWindow`.

**Vérifié :** le chemin nu est **déjà** stocké dans les données de l'item
(`item.setData(0, PATH_ROLE, change.path)`, ligne 87). Le lire par `PATH_ROLE`
— surtout pas rogner le libellé affiché, qui est préfixé par le type de
changement.

**Vérifié :** la fixture de `tests/ui/test_commit_detail_window.py` s'appelle
`window` (pas `detail_window`), et `repo` y existe aussi.

- [ ] **Step 5: Vérifier le succès**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/ -q`
Expected: PASS.

- [ ] **Step 6: Le rendu du graphe n'a pas bougé**

Run: `git status --short` (lecture seule) — `graph_items.py`, `theme.py` et
`layout/` ne doivent pas apparaître.

- [ ] **Step 7: Lecture seule et architecture**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/test_read_only.py tests/test_architecture.py -q`
Expected: PASS.

- [ ] **Step 8: Suite complète**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`
Expected: 945 + ~20 tests. **Deux échecs connus et sans rapport** :
`test_fetch_hides_the_bar_when_done` et `test_worker_reports_its_result`.

- [ ] **Step 9: Signaler les fichiers prêts** — ne commite pas. Donner le
décompte exact.

---

## Fin de phase 14

On voit qui a écrit chaque ligne, et un clic mène au commit qui l'a écrite.

**Hors périmètre**, conformément à la spec §8 : l'historique d'un fichier
(mesuré à 2,1 s), le suivi des renommages, le blâme d'une plage, et le blâme
depuis la fenêtre de commit.
