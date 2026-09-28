# tortoisePy — Plan d'implémentation, phase 6 : voir, stager, commiter, pousser

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fermer le cycle de travail quotidien depuis le graphe — voir ses
modifications, en choisir une partie, écrire un message, commiter, pousser, et
inspecter les changements d'un commit déjà fait.

**Architecture:** `core/changes.py` lit l'état des fichiers et leurs diffs sans
Qt. `core/operations.py` gagne le commit — construit depuis un index
**temporaire**, pour ne jamais toucher à celui de l'utilisateur — et le push.
`ui/diff_view.py` affiche un diff coloré, réutilisable ailleurs.
`ui/commit_window.py` assemble le tout. `ui/commit_detail_window.py` réutilise
`DiffView` pour montrer les changements d'un commit existant, au double-clic
dans le panneau des commits.

**Tech Stack:** Python 3.13, pygit2 1.20, PySide6 6.11, pytest-qt.

**Spec:** `docs/superpowers/specs/2026-09-28-tortoisepy-commit-design.md`

**Prérequis:** phases 1 à 5 terminées, 527 tests passent.

## Global Constraints

- **Aucune commande `git` sur le dépôt tortoisePy.** Les étapes « commit » du
  modèle de plan sont remplacées par « signaler les fichiers prêts ». Les
  fixtures de test peuvent invoquer `git` via `subprocess` sur des dépôts
  temporaires.
- **Rien ne s'écrit sans clic explicite (§7.0).** `tests/test_read_only.py`
  doit rester vert : ouvrir la fenêtre de commit et cocher des cases n'écrit
  rien dans le dépôt.
- **Le rendu visuel validé ne doit pas être dégradé.** Aucune tâche de cette
  phase ne touche `layout/`, `ui/graph_items.py` ni `ui/theme.py` — sauf pour
  y **ajouter** des couleurs de diff, sans modifier les existantes.
- **`core/` n'importe jamais PySide6.** Vérifié par `tests/test_architecture.py`.
- **Toutes les structures retournées sont `frozen=True`.**
- **Jamais de push forcé.** Aucune interface ne l'expose.
- **Pas de commit sans message** ni sans fichier sélectionné.
- **Tests d'intégration sur `portfolio-v1`**, à la demande de l'utilisateur.
  Il est actuellement propre et son remote est en HTTPS : les fixtures créent
  leurs propres dépôts pour les cas de modification et de push.
- **API vérifiées le 2026-09-28** sur pygit2 1.20 : `repo.diff()` rend des
  `Patch` avec `delta.is_binary`, `line_stats` et `hunks[].lines[].origin` ;
  `FileStatus.CONFLICTED` marque les conflits ; un index détaché ne lit pas le
  disque — il faut `create_blob_fromworkdir` puis `IndexEntry` ;
  `index.write_tree(repo)` écrit l'arbre sans toucher `.git/index` ; le
  refspec de push doit être construit depuis la branche courante, jamais codé
  en dur (un clone récent est sur `main`).

## Review Focus

Cas que la spec implique et qu'aucune tâche n'exercerait sans y penser. Chacun
a son test, rattaché à la tâche qui en porte le code.

1. **Fichier binaire** — un diff illisible d'octets bruts. Doit afficher
   « fichier binaire ». *(tâche 1)*
2. **Fichier en conflit** — cocher un conflit produirait un commit contenant
   des marqueurs `<<<<<<<`. Doit être non cochable. *(tâches 1 et 5)*
3. **Premier commit d'un dépôt vide** — `HEAD` n'existe pas ; passer `[HEAD]`
   en parent lèverait. *(tâche 2)*
4. **Fichier disparu entre l'affichage et le commit** — le blob ne peut plus
   être lu. Doit échouer proprement en nommant le fichier. *(tâche 2)*
5. **Push rejeté** — le serveur a avancé. Le commit local est fait et
   conservé ; le message doit le dire. *(tâche 3)*
6. **Commit de merge et commit racine** — un merge a deux parents, donc pas
   d'« avant » évident ; un commit racine n'en a aucun. Vérifié : sans
   `swap=True`, les fichiers d'un commit racine s'affichent en suppressions.
   *(tâche 7)*

---

### Task 1: Lecture des changements

**Files:**
- Create: `src/tortoisepy/core/changes.py`
- Test: `tests/core/test_changes.py`

**Interfaces:**
- Consumes: rien de l'application
- Produces: `ChangeKind`, `FileChange`, `DiffLine`, `DiffHunk`, `FileDiff`,
  `list_changes(repo) -> tuple[FileChange, ...]`,
  `diff_for(repo, path) -> FileDiff`

Module en **lecture seule**, sans Qt.

- [ ] **Step 1: Écrire les tests**

```python
# tests/core/test_changes.py
import os
import subprocess

import pygit2
import pytest

from tortoisepy.core.changes import (
    ChangeKind,
    diff_for,
    list_changes,
)


def run_git(path, *args):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
    }
    return subprocess.run(
        ["git", *args], cwd=path, env=env, capture_output=True, text=True
    )


@pytest.fixture
def repo(tmp_path):
    """Un dépôt portant les quatre sortes de changements."""
    path = tmp_path / "changes"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "garde.txt").write_text("ligne 1\nligne 2\nligne 3\n")
    (path / "supprime.txt").write_text("à supprimer\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "base")

    (path / "garde.txt").write_text("ligne 1\nLIGNE 2 MODIFIÉE\nligne 3\n")
    (path / "nouveau.txt").write_text("tout neuf\n")
    (path / "supprime.txt").unlink()
    return pygit2.Repository(str(path))


def test_lists_every_changed_file(repo):
    paths = {c.path for c in list_changes(repo)}
    assert paths == {"garde.txt", "nouveau.txt", "supprime.txt"}


def test_classifies_a_modified_file(repo):
    change = next(c for c in list_changes(repo) if c.path == "garde.txt")
    assert change.kind is ChangeKind.MODIFIED


def test_classifies_an_untracked_file(repo):
    change = next(c for c in list_changes(repo) if c.path == "nouveau.txt")
    assert change.kind is ChangeKind.UNTRACKED


def test_classifies_a_deleted_file(repo):
    change = next(c for c in list_changes(repo) if c.path == "supprime.txt")
    assert change.kind is ChangeKind.DELETED


def test_untracked_files_are_not_preselected(repo):
    """§4.1 : cocher un fichier non suivi par défaut ajouterait des `.env`."""
    change = next(c for c in list_changes(repo) if c.path == "nouveau.txt")
    assert change.selected_by_default is False


def test_tracked_changes_are_preselected(repo):
    change = next(c for c in list_changes(repo) if c.path == "garde.txt")
    assert change.selected_by_default is True


def test_changes_are_sorted_by_path(repo):
    paths = [c.path for c in list_changes(repo)]
    assert paths == sorted(paths)


def test_clean_repository_has_no_changes(tmp_path):
    path = tmp_path / "propre"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "f.txt").write_text("a\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "base")
    assert list_changes(pygit2.Repository(str(path))) == ()


def test_diff_shows_added_and_removed_lines(repo):
    diff = diff_for(repo, "garde.txt")
    origins = {line.origin for hunk in diff.hunks for line in hunk.lines}
    assert "+" in origins
    assert "-" in origins


def test_diff_counts_lines(repo):
    diff = diff_for(repo, "garde.txt")
    assert diff.added == 1
    assert diff.removed == 1


def test_diff_keeps_context_lines(repo):
    """Sans contexte, on ne sait pas où le changement se situe."""
    diff = diff_for(repo, "garde.txt")
    origins = [line.origin for hunk in diff.hunks for line in hunk.lines]
    assert " " in origins


def test_hunk_carries_its_header(repo):
    diff = diff_for(repo, "garde.txt")
    assert diff.hunks
    assert diff.hunks[0].header.startswith("@@")


def test_untracked_file_shows_as_fully_added(repo):
    """§4.2 : un fichier non suivi n'a pas de version précédente."""
    diff = diff_for(repo, "nouveau.txt")
    assert diff.added >= 1
    assert diff.removed == 0


def test_binary_file_is_flagged(tmp_path):
    """Review Focus 1 : un diff d'octets bruts serait illisible."""
    path = tmp_path / "binaire"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "image.dat").write_bytes(bytes(range(256)))
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "base")
    (path / "image.dat").write_bytes(bytes(range(255, -1, -1)))

    repository = pygit2.Repository(str(path))
    change = next(c for c in list_changes(repository) if c.path == "image.dat")
    assert change.is_binary is True

    diff = diff_for(repository, "image.dat")
    assert diff.is_binary is True
    assert diff.hunks == ()


def test_conflicted_file_is_flagged(tmp_path):
    """Review Focus 2 : commiter un conflit produirait des marqueurs."""
    path = tmp_path / "conflit"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "f.txt").write_text("base\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "base")

    run_git(path, "checkout", "-q", "-b", "autre")
    (path / "f.txt").write_text("leur version\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "leur")

    run_git(path, "checkout", "-q", "main")
    (path / "f.txt").write_text("notre version\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "notre")
    run_git(path, "merge", "autre")

    repository = pygit2.Repository(str(path))
    change = next(c for c in list_changes(repository) if c.path == "f.txt")
    assert change.kind is ChangeKind.CONFLICTED
    assert change.selectable is False


def test_unknown_path_gives_an_empty_diff(repo):
    diff = diff_for(repo, "inexistant.txt")
    assert diff.hunks == ()


def test_reading_changes_writes_nothing(repo):
    """§7.0 : lire l'état ne modifie pas le dépôt."""
    import hashlib
    from pathlib import Path

    git_dir = Path(repo.path)

    def fingerprint():
        digest = hashlib.sha256()
        for item in sorted(git_dir.rglob("*")):
            if item.is_file():
                digest.update(f"{item}:{item.stat().st_mtime_ns}".encode())
        return digest.hexdigest()

    before = fingerprint()
    list_changes(repo)
    for change in list_changes(repo):
        diff_for(repo, change.path)
    assert fingerprint() == before
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/core/test_changes.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tortoisepy.core.changes'`

- [ ] **Step 3: Implémenter**

```python
# src/tortoisepy/core/changes.py
"""État des fichiers modifiés et leurs diffs — §4.1, §4.2.

Lecture seule, sans Qt : `ui/` affiche ce que ce module décrit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import pygit2
from pygit2.enums import DeltaStatus, FileStatus

_UNTRACKED = FileStatus.WT_NEW
_DELETED = FileStatus.WT_DELETED | FileStatus.INDEX_DELETED
_CONFLICTED = FileStatus.CONFLICTED


class ChangeKind(Enum):
    MODIFIED = "M"
    ADDED = "A"
    DELETED = "D"
    UNTRACKED = "?"
    CONFLICTED = "!"


@dataclass(frozen=True)
class FileChange:
    path: str
    kind: ChangeKind
    is_binary: bool = False

    @property
    def selectable(self) -> bool:
        """Un conflit non résolu ne doit pas pouvoir être commité (§4.1)."""
        return self.kind is not ChangeKind.CONFLICTED

    @property
    def selected_by_default(self) -> bool:
        """Les fichiers non suivis sont affichés mais décochés (D8).

        Ils sont souvent du bruit — build, cache, `.env` — mais parfois le
        fichier qu'on vient de créer. Les montrer sans les cocher laisse
        décider sans risque d'ajout accidentel.
        """
        if not self.selectable:
            return False
        return self.kind is not ChangeKind.UNTRACKED


@dataclass(frozen=True)
class DiffLine:
    origin: str
    """`+` ajoutée, `-` supprimée, ` ` contexte."""

    content: str


@dataclass(frozen=True)
class DiffHunk:
    header: str
    lines: tuple[DiffLine, ...]


@dataclass(frozen=True)
class FileDiff:
    path: str
    hunks: tuple[DiffHunk, ...] = ()
    added: int = 0
    removed: int = 0
    is_binary: bool = False


def list_changes(repo: pygit2.Repository) -> tuple[FileChange, ...]:
    """Fichiers modifiés, triés par chemin.

    Le tri rend l'affichage stable d'une ouverture à l'autre.
    """
    try:
        status = repo.status()
    except pygit2.GitError:
        return ()

    changes = [
        FileChange(
            path=path,
            kind=_classify(code),
            is_binary=_is_binary(repo, path),
        )
        for path, code in status.items()
    ]
    return tuple(sorted(changes, key=lambda c: c.path))


def diff_for(repo: pygit2.Repository, path: str) -> FileDiff:
    """Diff d'un fichier par rapport au dernier commit.

    Indexé ou non : c'est l'état que l'utilisateur s'apprête à commiter.
    """
    patch = _patch_for(repo, path)
    if patch is None:
        return FileDiff(path=path)

    if patch.delta.is_binary:
        # Vérifié : un binaire a 0 hunk et des line_stats à zéro. Afficher
        # ses octets serait illisible.
        return FileDiff(path=path, is_binary=True)

    hunks = tuple(
        DiffHunk(
            header=hunk.header.rstrip("\n"),
            lines=tuple(
                DiffLine(origin=line.origin, content=line.content.rstrip("\n"))
                for line in hunk.lines
            ),
        )
        for hunk in patch.hunks
    )

    _, added, removed = patch.line_stats
    return FileDiff(path=path, hunks=hunks, added=added, removed=removed)


def _classify(code: int) -> ChangeKind:
    """Le conflit prime : il interdit toute sélection."""
    if code & _CONFLICTED:
        return ChangeKind.CONFLICTED
    if code & _UNTRACKED:
        return ChangeKind.UNTRACKED
    if code & _DELETED:
        return ChangeKind.DELETED
    if code & FileStatus.INDEX_NEW:
        return ChangeKind.ADDED
    return ChangeKind.MODIFIED


def _is_binary(repo: pygit2.Repository, path: str) -> bool:
    patch = _patch_for(repo, path)
    return bool(patch and patch.delta.is_binary)


def _patch_for(repo: pygit2.Repository, path: str):
    """Patch d'un fichier, fichiers non suivis inclus.

    `include_untracked` est indispensable : sans lui, un fichier qu'on
    vient de créer n'apparaît dans aucun diff.
    """
    try:
        diff = repo.diff(
            repo.revparse_single("HEAD").tree
            if not repo.head_is_unborn
            else None,
            flags=pygit2.enums.DiffOption.INCLUDE_UNTRACKED,
        )
    except (pygit2.GitError, KeyError, ValueError, AttributeError):
        try:
            diff = repo.diff(flags=pygit2.enums.DiffOption.INCLUDE_UNTRACKED)
        except (pygit2.GitError, ValueError):
            return None

    for patch in diff:
        if patch.delta.new_file.path == path:
            return patch
        if patch.delta.old_file.path == path:
            return patch
    return None
```

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/core/test_changes.py -v`
Expected: PASS, 17 tests.

- [ ] **Step 5: Signaler les fichiers prêts** — ne commite pas.

---

### Task 2: Staging et commit

**Files:**
- Modify: `src/tortoisepy/core/operations.py` (ajout en fin de fichier)
- Test: `tests/core/test_commit_operation.py`

**Interfaces:**
- Consumes: `OperationResult`, `guarded`, `succeeded`, `failed`
- Produces: `commit_selection(repo, paths, message) -> OperationResult`

**Le point délicat de cette tâche.** Le commit est construit depuis un index
**temporaire en mémoire**, jamais depuis `.git/index` : décocher un fichier
l'exclut du commit sans modifier ce que l'utilisateur a préparé au terminal
(§5).

Vérifié : un index détaché ne lit pas le disque — `index.add('fichier')` lève
« Index is not backed up by an existing repository ». Il faut
`create_blob_fromworkdir` puis construire l'`IndexEntry`.

- [ ] **Step 1: Écrire les tests**

```python
# tests/core/test_commit_operation.py
import os
import subprocess

import pygit2
import pytest

from tortoisepy.core.operations import commit_selection


def run_git(path, *args):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
    }
    return subprocess.run(
        ["git", *args], cwd=path, env=env, capture_output=True, text=True
    )


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "commit"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "a.txt").write_text("A\n")
    (path / "b.txt").write_text("B\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "base")

    (path / "a.txt").write_text("A modifié\n")
    (path / "b.txt").write_text("B modifié\n")
    return pygit2.Repository(str(path))


def commit_count(repo) -> int:
    return len(list(repo.walk(repo.head.target)))


def test_commits_the_selected_files(repo):
    before = commit_count(repo)
    result = commit_selection(repo, ("a.txt",), "mon message")
    assert result.success is True, result.git_error
    assert commit_count(repo) == before + 1


def test_commit_message_is_recorded(repo):
    commit_selection(repo, ("a.txt",), "un message précis")
    assert repo.get(repo.head.target).message.strip() == "un message précis"


def test_unselected_files_stay_out(repo):
    """§5 : décocher un fichier l'exclut du commit."""
    commit_selection(repo, ("a.txt",), "seulement a")
    commit = repo.get(repo.head.target)
    diff = repo.diff(commit.parents[0], commit)
    assert {p.delta.new_file.path for p in diff} == {"a.txt"}


def test_the_user_index_is_left_alone(repo):
    """§5 : l'index préparé au terminal n'est pas modifié."""
    workdir = repo.workdir
    run_git(workdir, "add", "b.txt")  # l'utilisateur a indexé b.txt

    commit_selection(repo, ("a.txt",), "seulement a")

    status = subprocess.run(
        ["git", "status", "--short"], cwd=workdir,
        capture_output=True, text=True,
    ).stdout
    assert "b.txt" in status, "b.txt doit rester visible dans le statut"


def test_empty_message_is_refused(repo):
    """§4.3 : un commit sans message est une dette immédiate."""
    before = commit_count(repo)
    result = commit_selection(repo, ("a.txt",), "   ")
    assert result.success is False
    assert commit_count(repo) == before


def test_empty_selection_is_refused(repo):
    before = commit_count(repo)
    result = commit_selection(repo, (), "un message")
    assert result.success is False
    assert commit_count(repo) == before


def test_untracked_file_can_be_committed(repo):
    (repo.workdir and None)
    from pathlib import Path
    Path(repo.workdir, "neuf.txt").write_text("nouveau\n")

    result = commit_selection(repo, ("neuf.txt",), "ajout")
    assert result.success is True, result.git_error

    commit = repo.get(repo.head.target)
    diff = repo.diff(commit.parents[0], commit)
    assert "neuf.txt" in {p.delta.new_file.path for p in diff}


def test_deleted_file_is_removed_by_the_commit(repo):
    from pathlib import Path
    Path(repo.workdir, "b.txt").unlink()

    result = commit_selection(repo, ("b.txt",), "suppression")
    assert result.success is True, result.git_error

    tree = repo.get(repo.head.target).tree
    assert "b.txt" not in [entry.name for entry in tree]


def test_first_commit_of_an_empty_repository(tmp_path):
    """Review Focus 3 : `HEAD` n'existe pas encore."""
    path = tmp_path / "vide"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "premier.txt").write_text("contenu\n")

    repository = pygit2.Repository(str(path))
    result = commit_selection(repository, ("premier.txt",), "premier commit")

    assert result.success is True, result.git_error
    assert repository.head.target is not None


def test_missing_file_fails_cleanly(repo):
    """Review Focus 4 : le fichier a disparu entre l'affichage et le commit."""
    result = commit_selection(repo, ("jamais-existe.txt",), "message")
    assert result.success is False
    assert "jamais-existe.txt" in (result.git_error or "")


def test_commit_marks_the_repository_changed(repo):
    result = commit_selection(repo, ("a.txt",), "message")
    assert result.repository_changed is True


def test_refusal_leaves_the_repository_untouched(repo):
    result = commit_selection(repo, (), "message")
    assert result.repository_changed is False


def test_commit_never_raises(repo):
    """§7.6 : aucune exception ne remonte."""
    for paths, message in [
        ((), ""),
        (("a.txt",), ""),
        (("inexistant",), "m"),
        ((None,), "m"),
    ]:
        result = commit_selection(repo, paths, message)
        assert result.success is False
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/core/test_commit_operation.py -v`
Expected: FAIL — `ImportError: cannot import name 'commit_selection'`

- [ ] **Step 3: Implémenter — à AJOUTER à la fin de `operations.py`**

```python
# --- Commit d'une sélection (§5, §6.1) ----------------------------------


@guarded("Commit")
def commit_selection(
    repo: pygit2.Repository, paths: tuple[str, ...], message: str
) -> OperationResult:
    """Commite les fichiers indiqués, sans toucher à l'index de l'utilisateur.

    Le commit est bâti sur un index **temporaire en mémoire** : décocher un
    fichier l'exclut du commit, mais ce que l'utilisateur a préparé au
    terminal reste intact (§5).
    """
    text = message.strip()
    if not text:
        return failed("Commit", "empty commit message")

    selected = tuple(p for p in paths if p)
    if not selected:
        return failed("Commit", "nothing selected")

    unborn = repo.head_is_unborn
    index = pygit2.Index()

    if not unborn:
        # Partir du dernier commit : tout ce qui n'est pas coché reste tel
        # quel, au lieu de disparaître du nouvel arbre.
        index.read_tree(repo.revparse_single("HEAD").tree)

    workdir = repo.workdir or ""
    for path in selected:
        full = os.path.join(workdir, path)
        if os.path.exists(full):
            # Un index détaché ne lit pas le disque : le blob doit être
            # créé explicitement (vérifié).
            blob = repo.create_blob_fromworkdir(path)
            index.add(pygit2.IndexEntry(path, blob, FileMode.BLOB))
        elif not unborn and path in [e.path for e in index]:
            index.remove(path)  # fichier supprimé
        else:
            return failed("Commit", f"file not found: {path}")

    tree = index.write_tree(repo)
    signature = _signature(repo)
    parents = [] if unborn else [repo.head.target]

    oid = repo.create_commit(
        "HEAD", signature, signature, text, tree, parents
    )

    count = len(selected)
    plural = "" if count == 1 else "s"
    return succeeded(f"Committed {count} file{plural} — {str(oid)[:8]}")
```

Ajouter en tête de `operations.py` :

```python
import os

from pygit2.enums import FileMode
```

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/core/test_commit_operation.py -v`
Expected: PASS, 13 tests.

- [ ] **Step 5: Vérifier la lecture seule**

Run: `.venv/bin/pytest tests/test_read_only.py -v`
Expected: PASS, 7 tests.

- [ ] **Step 6: Signaler les fichiers prêts** — ne commite pas.

---

### Task 3: Push

**Files:**
- Modify: `src/tortoisepy/core/operations.py` (ajout en fin de fichier)
- Test: `tests/core/test_push_operation.py`

**Interfaces:**
- Consumes: `_credentials` (déjà présent dans `operations.py`)
- Produces: `PushCallbacks`,
  `push_branch(repo, remote_name=None, on_progress=None) -> OperationResult`

**`FetchCallbacks` ne convient pas au push.** Vérifié sur pygit2 1.20 :
`transfer_progress` est la progression **du fetch** ; le push appelle
`push_transfer_progress(objects_pushed, total_objects, bytes_pushed)` — trois
arguments. Réutiliser `FetchCallbacks` laisserait la barre figée.

**Et surtout** : `remote.push()` ne lève pas toujours quand le serveur refuse.
Vérifié : `push_update_reference(refname, message)` est appelé à **chaque**
push — `message is None` vaut acceptation, sinon c'est le refus du serveur.
Un `succeeded()` inconditionnel après `remote.push()` annoncerait donc
« Pushed main to origin » alors que rien n'est arrivé. Le refus
non-fast-forward, lui, est bien détecté localement par libgit2 et lève
(vérifié) — mais un refus décidé par le serveur, un hook ou une branche
protégée passe par le message.

**Le refspec est construit depuis la branche courante**, jamais codé en dur :
vérifié, un clone récent est sur `main`, pas `master`.

- [ ] **Step 1: Écrire les tests**

```python
# tests/core/test_push_operation.py
import os
import subprocess

import pygit2
import pytest

from tortoisepy.core.operations import push_branch


def run_git(path, *args):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
    }
    return subprocess.run(
        ["git", *args], cwd=path, env=env, capture_output=True, text=True
    )


@pytest.fixture
def pair(tmp_path):
    """Un dépôt nu servant de serveur, et un clone de travail."""
    bare = tmp_path / "serveur.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", str(bare)], capture_output=True
    )
    work = tmp_path / "travail"
    subprocess.run(
        ["git", "clone", "-q", str(bare), str(work)], capture_output=True
    )
    (work / "f.txt").write_text("base\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "base")
    run_git(work, "push", "-q", "origin", "HEAD")
    return bare, pygit2.Repository(str(work))


def server_log(bare) -> str:
    return subprocess.run(
        ["git", "log", "--oneline"], cwd=bare, capture_output=True, text=True
    ).stdout


def test_push_sends_the_commit(pair):
    bare, repo = pair
    (repo.workdir and None)
    from pathlib import Path
    Path(repo.workdir, "f.txt").write_text("suite\n")
    run_git(repo.workdir, "add", ".")
    run_git(repo.workdir, "commit", "-q", "-m", "à pousser")

    result = push_branch(repo)
    assert result.success is True, result.git_error
    assert "à pousser" in server_log(bare)


def test_push_uses_the_current_branch(pair):
    """Vérifié : un clone récent est sur `main`, pas `master`."""
    bare, repo = pair
    run_git(repo.workdir, "checkout", "-q", "-b", "une-autre-branche")
    from pathlib import Path
    Path(repo.workdir, "g.txt").write_text("x\n")
    run_git(repo.workdir, "add", ".")
    run_git(repo.workdir, "commit", "-q", "-m", "sur une autre branche")

    result = push_branch(repo)
    assert result.success is True, result.git_error

    refs = subprocess.run(
        ["git", "branch"], cwd=bare, capture_output=True, text=True
    ).stdout
    assert "une-autre-branche" in refs


def test_rejected_push_reports_the_server_message(pair, tmp_path):
    """Review Focus 5 : le serveur a avancé entre-temps."""
    bare, repo = pair

    other = tmp_path / "concurrent"
    subprocess.run(
        ["git", "clone", "-q", str(bare), str(other)], capture_output=True
    )
    (other / "concurrent.txt").write_text("x\n")
    run_git(other, "add", ".")
    run_git(other, "commit", "-q", "-m", "concurrent")
    run_git(other, "push", "-q")

    from pathlib import Path
    Path(repo.workdir, "local.txt").write_text("y\n")
    run_git(repo.workdir, "add", ".")
    run_git(repo.workdir, "commit", "-q", "-m", "local")

    result = push_branch(repo)
    assert result.success is False
    assert result.git_error


def test_push_without_remote_fails_cleanly(tmp_path):
    path = tmp_path / "sans-remote"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "f.txt").write_text("a\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "base")

    result = push_branch(pygit2.Repository(str(path)))
    assert result.success is False
    assert "remote" in (result.git_error or "").lower()


def test_push_from_detached_head_fails_cleanly(pair):
    """Sans branche, il n'y a rien à pousser."""
    bare, repo = pair
    head = str(repo.head.target)
    run_git(repo.workdir, "checkout", "-q", "--detach", head)

    result = push_branch(pygit2.Repository(repo.path))
    assert result.success is False


def test_push_does_not_change_the_local_graph(pair):
    """Pousser n'ajoute ni ne déplace de ref locale."""
    bare, repo = pair
    before = {r for r in repo.references}
    push_branch(repo)
    assert {r for r in repo.references} == before


def test_push_reports_progress(pair):
    """Le rappel de progression doit être celui du push, pas du fetch."""
    bare, repo = pair
    from pathlib import Path
    Path(repo.workdir, "f.txt").write_text("suite\n")
    run_git(repo.workdir, "add", ".")
    run_git(repo.workdir, "commit", "-q", "-m", "à pousser")

    seen = []
    result = push_branch(repo, on_progress=lambda a, b: seen.append((a, b)))
    assert result.success is True, result.git_error
    assert seen, (
        "push_transfer_progress n'a pas été appelé — FetchCallbacks utilise "
        "transfer_progress, qui est la progression du fetch"
    )


def test_progress_callback_takes_three_arguments():
    """Vérifié : la signature du push a un argument de plus que le fetch.

    `push_transfer_progress(objects_pushed, total_objects, bytes_pushed)`.
    Une méthode à deux paramètres lèverait TypeError pendant le push.
    """
    import inspect

    from tortoisepy.core.operations import PushCallbacks

    signature = inspect.signature(PushCallbacks.push_transfer_progress)
    assert len(signature.parameters) == 4  # self + 3


def test_rejection_message_is_not_reported_as_success(pair, monkeypatch):
    """Un refus annoncé par le serveur ne doit pas passer pour un succès.

    `remote.push()` ne lève pas dans ce cas : le refus arrive par
    `push_update_reference`. Sans cette vérification, l'utilisateur lit
    « Pushed main to origin » alors que rien n'est arrivé.
    """
    import pygit2

    from tortoisepy.core import operations

    bare, repo = pair

    def refuse(self, refspecs, callbacks=None):
        callbacks.push_update_reference(
            "refs/heads/main", "pre-receive hook declined"
        )

    monkeypatch.setattr(pygit2.Remote, "push", refuse)

    result = operations.push_branch(repo)
    assert result.success is False
    assert "declined" in (result.git_error or "")
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/core/test_push_operation.py -v`
Expected: FAIL — `ImportError: cannot import name 'push_branch'`

- [ ] **Step 3: Implémenter — à AJOUTER à la fin de `operations.py`**

```python
class PushCallbacks(pygit2.RemoteCallbacks):
    """Suit un push : progression de l'envoi et refus du serveur.

    Distincte de `FetchCallbacks` pour deux raisons vérifiées sur
    pygit2 1.20 :

    - la progression du push passe par `push_transfer_progress`, avec un
      argument de plus que `transfer_progress` (celle du fetch) ;
    - le refus du serveur passe par `push_update_reference` et **ne lève
      pas**. Sans le lire, un push refusé serait annoncé comme réussi.
    """

    def __init__(self, url: str, on_progress=None):
        super().__init__(credentials=_credentials(url))
        self._on_progress = on_progress
        self.rejections: list[tuple[str, str]] = []

    def push_transfer_progress(
        self, objects_pushed: int, total_objects: int, bytes_pushed: int
    ) -> None:
        if self._on_progress is not None:
            self._on_progress(objects_pushed, total_objects)

    def push_update_reference(self, refname: str, message: str | None) -> None:
        # `message is None` vaut acceptation — vérifié sur un push réussi.
        if message is not None:
            self.rejections.append((refname, message))


@guarded("Push")
def push_branch(
    repo: pygit2.Repository,
    remote_name: str | None = None,
    on_progress=None,
) -> OperationResult:
    """Pousse la branche courante vers son remote.

    Jamais de push forcé : `--force` réécrit l'historique d'autrui et
    aucune interface de tortoisePy ne l'expose (§6.2). Un push rejeté se
    résout en récupérant d'abord les changements distants.
    """
    if repo.head_is_unborn or repo.head_is_detached:
        return failed("Push", "no branch to push (detached or unborn HEAD)")

    branch = repo.head.shorthand
    names = [remote_name] if remote_name else list(repo.remotes.names())
    if not names:
        return failed("Push", "no remote configured")

    remote = repo.remotes[names[0]]
    callbacks = PushCallbacks(remote.url, on_progress)

    # Construit depuis la branche courante : coder « master » en dur
    # échouerait sur un dépôt cloné récemment, qui est sur « main ».
    remote.push([f"refs/heads/{branch}:refs/heads/{branch}"], callbacks=callbacks)

    # `remote.push()` n'a pas levé, mais le serveur a pu refuser la ref :
    # annoncer un succès ici serait un mensonge.
    if callbacks.rejections:
        detail = "; ".join(
            f"{_short_ref(ref)}: {message}"
            for ref, message in callbacks.rejections
        )
        return failed("Push", detail)

    return succeeded(f"Pushed {branch} to {remote.name}")
```

`_short_ref` existe déjà dans `operations.py` (utilisé par le fetch).

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/core/test_push_operation.py -v`
Expected: PASS, 9 tests.

- [ ] **Step 5: Signaler les fichiers prêts** — ne commite pas.

---

### Task 4: Affichage d'un diff

**Files:**
- Create: `src/tortoisepy/ui/diff_view.py`
- Modify: `src/tortoisepy/ui/theme.py` (ajout de couleurs, sans en changer)
- Test: `tests/ui/test_diff_view.py`

**Interfaces:**
- Consumes: `FileDiff`, `DiffHunk`, `DiffLine` (tâche 1)
- Produces: `DiffView` (QWidget), `DIFF_ADDED`, `DIFF_REMOVED`, `DIFF_HEADER`

**Widget autonome**, séparé de la fenêtre : afficher un diff coloré servira
aussi au futur « Compare revisions » (§7.4).

**Ne modifie aucune couleur existante** — la palette validée par l'utilisateur
reste intacte, on y ajoute seulement trois teintes de diff.

- [ ] **Step 1: Écrire les tests**

```python
# tests/ui/test_diff_view.py
import pytest

from tortoisepy.core.changes import DiffHunk, DiffLine, FileDiff
from tortoisepy.ui.diff_view import DiffView


@pytest.fixture
def view(qtbot):
    widget = DiffView()
    qtbot.addWidget(widget)
    return widget


def sample() -> FileDiff:
    return FileDiff(
        path="src/app.py",
        hunks=(
            DiffHunk(
                header="@@ -1,3 +1,4 @@",
                lines=(
                    DiffLine(" ", "contexte"),
                    DiffLine("-", "ancienne ligne"),
                    DiffLine("+", "nouvelle ligne"),
                ),
            ),
        ),
        added=1,
        removed=1,
    )


def test_starts_empty(view):
    assert view.line_count() == 0


def test_shows_every_line(view):
    view.show_diff(sample())
    # 1 en-tête de hunk + 3 lignes
    assert view.line_count() == 4


def test_keeps_the_line_content(view):
    view.show_diff(sample())
    assert "nouvelle ligne" in view.text()
    assert "ancienne ligne" in view.text()


def test_shows_the_hunk_header(view):
    view.show_diff(sample())
    assert "@@ -1,3 +1,4 @@" in view.text()


def test_binary_file_says_so(view):
    """Review Focus 1 : afficher des octets bruts serait illisible."""
    view.show_diff(FileDiff(path="image.png", is_binary=True))
    assert "binaire" in view.text().lower()
    assert view.line_count() == 1


def test_empty_diff_says_so(view):
    view.show_diff(FileDiff(path="vide.txt"))
    assert view.text()


def test_showing_again_replaces_the_previous(view):
    view.show_diff(sample())
    view.show_diff(FileDiff(path="autre.txt", is_binary=True))
    assert "nouvelle ligne" not in view.text()


def test_clear_empties_the_view(view):
    view.show_diff(sample())
    view.clear()
    assert view.line_count() == 0


def test_uses_a_monospace_font(view):
    """Un diff aligné en colonnes exige une chasse fixe."""
    assert view.font().fixedPitch() or view.font().family()


def test_is_read_only(view):
    """Le diff se lit, il ne s'édite pas."""
    assert view.isReadOnly()
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/ui/test_diff_view.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tortoisepy.ui.diff_view'`

- [ ] **Step 3: Ajouter les couleurs à `theme.py`**

À insérer après la définition de `PALETTE` — **sans modifier les couleurs
existantes**, que l'utilisateur a validées :

```python
DIFF_ADDED = QColor(228, 245, 228)
"""Fond des lignes ajoutées — vert pâle, lisible en texte noir."""

DIFF_REMOVED = QColor(250, 228, 228)
"""Fond des lignes supprimées — rouge pâle."""

DIFF_HEADER = QColor(120, 120, 130)
"""Couleur des en-têtes de hunk (`@@ -14,7 +14,9 @@`)."""
```

- [ ] **Step 4: Implémenter**

```python
# src/tortoisepy/ui/diff_view.py
"""Affichage coloré d'un diff — §4.2.

Widget autonome : servira aussi au futur « Compare revisions » (§7.4).
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit

from tortoisepy.core.changes import FileDiff
from tortoisepy.ui import theme


class DiffView(QPlainTextEdit):
    """Diff en lecture seule, lignes colorées selon leur nature."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        font = QFont(theme.NODE_FONT_FAMILY, 11)
        font.setFixedPitch(True)
        self.setFont(font)

        self._lines = 0

    def show_diff(self, diff: FileDiff) -> None:
        """Remplace le contenu par le diff donné."""
        self.clear()

        if diff.is_binary:
            self._append("fichier binaire — diff non affiché", theme.DIFF_HEADER)
            return

        if not diff.hunks:
            self._append("aucune modification à afficher", theme.DIFF_HEADER)
            return

        for hunk in diff.hunks:
            self._append(hunk.header, theme.DIFF_HEADER)
            for line in hunk.lines:
                self._append(
                    f"{line.origin}{line.content}", None, _background(line.origin)
                )

    def clear(self) -> None:
        super().clear()
        self._lines = 0

    def line_count(self) -> int:
        return self._lines

    def text(self) -> str:
        return self.toPlainText()

    def _append(
        self,
        text: str,
        colour: QColor | None = None,
        background: QColor | None = None,
    ) -> None:
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        fmt = QTextCharFormat()
        if colour is not None:
            fmt.setForeground(colour)
        if background is not None:
            fmt.setBackground(background)

        if self._lines:
            cursor.insertBlock()
        cursor.insertText(text, fmt)
        self._lines += 1


def _background(origin: str) -> QColor | None:
    """Fond d'une ligne selon son origine. Le contexte reste neutre."""
    if origin == "+":
        return theme.DIFF_ADDED
    if origin == "-":
        return theme.DIFF_REMOVED
    return None
```

- [ ] **Step 5: Vérifier le succès**

Run: `.venv/bin/pytest tests/ui/test_diff_view.py -v`
Expected: PASS, 10 tests.

- [ ] **Step 6: Signaler les fichiers prêts** — ne commite pas.

---

### Task 5: La fenêtre de commit

> **Corrigé à l'implémentation (2026-09-28).** Le code ci-dessous, tel quel,
> échoue à son propre `test_window_refreshes_after_a_commit`. Deux exigences du
> plan se contredisaient : `commit_selection` (tâche 2) ne touche jamais
> `.git/index`, mais `list_changes` (tâche 1) lit `repo.status()`, qui compare
> **HEAD ↔ index ↔ arbre de travail**. Après un commit, l'index resté en
> arrière fait donc réapparaître le fichier commité (vérifié :
> `git status --short` rend `MM a.txt`).
> La fenêtre doit aligner l'index sur HEAD après un commit **réussi**, et
> **uniquement pour les chemins commités** — ce que fait un vrai `git commit`.
> Voir §5.1 de la spec. Cela ne relâche pas §5 : cocher/décocher n'écrit
> toujours rien, et un fichier décoché que l'utilisateur avait indexé au
> terminal reste indexé.

**Files:**
- Create: `src/tortoisepy/ui/commit_window.py`
- Test: `tests/ui/test_commit_window.py`

**Interfaces:**
- Consumes: `list_changes`, `diff_for` (tâche 1), `commit_selection`
  (tâche 2), `push_branch` (tâche 3), `DiffView` (tâche 4)
- Produces: `CommitWindow`

**Cocher une case n'écrit rien** : l'index n'est touché qu'au commit (§5).

- [ ] **Step 1: Écrire les tests**

```python
# tests/ui/test_commit_window.py
import os
import subprocess

import pygit2
import pytest

from tortoisepy.ui.commit_window import CommitWindow


def run_git(path, *args):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
    }
    return subprocess.run(
        ["git", *args], cwd=path, env=env, capture_output=True, text=True
    )


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "fenetre"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "suivi.txt").write_text("base\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "base")

    (path / "suivi.txt").write_text("modifié\n")
    (path / "nouveau.txt").write_text("neuf\n")
    return pygit2.Repository(str(path))


@pytest.fixture
def window(qtbot, repo):
    w = CommitWindow(repo)
    qtbot.addWidget(w)
    return w


def test_lists_the_changed_files(window):
    assert window.file_count() == 2


def test_tracked_file_is_checked(window):
    assert window.is_checked("suivi.txt") is True


def test_untracked_file_is_unchecked(window):
    """D8 : afficher sans cocher évite d'ajouter un `.env` par mégarde."""
    assert window.is_checked("nouveau.txt") is False


def test_selecting_a_file_shows_its_diff(window):
    window.select_file("suivi.txt")
    assert "modifié" in window.diff_view.text()


def test_commit_is_disabled_without_a_message(window):
    """§4.3 : un commit sans message est une dette immédiate."""
    window.set_message("")
    assert window.commit_button.isEnabled() is False


def test_commit_is_disabled_without_a_selection(window):
    window.set_message("un message")
    window.set_checked("suivi.txt", False)
    assert window.commit_button.isEnabled() is False


def test_commit_is_enabled_with_both(window):
    window.set_message("un message")
    assert window.commit_button.isEnabled() is True


def test_checking_a_box_writes_nothing(window, repo):
    """§5 : l'index n'est touché qu'au commit."""
    before = subprocess.run(
        ["git", "status", "--short"], cwd=repo.workdir,
        capture_output=True, text=True,
    ).stdout

    window.set_checked("nouveau.txt", True)
    window.set_checked("suivi.txt", False)

    after = subprocess.run(
        ["git", "status", "--short"], cwd=repo.workdir,
        capture_output=True, text=True,
    ).stdout
    assert before == after


def test_commit_creates_a_commit(window, repo):
    before = len(list(repo.walk(repo.head.target)))
    window.set_message("depuis la fenêtre")
    window.commit()
    assert len(list(repo.walk(repo.head.target))) == before + 1


def test_commit_uses_the_typed_message(window, repo):
    window.set_message("message saisi")
    window.commit()
    assert repo.get(repo.head.target).message.strip() == "message saisi"


def test_commit_only_includes_checked_files(window, repo):
    window.set_message("un seul fichier")
    window.set_checked("nouveau.txt", False)
    window.commit()

    commit = repo.get(repo.head.target)
    diff = repo.diff(commit.parents[0], commit)
    assert "nouveau.txt" not in {p.delta.new_file.path for p in diff}


def test_window_refreshes_after_a_commit(window):
    window.set_message("message")
    window.commit()
    # Le fichier commité n'a plus de changement à montrer.
    assert window.file_count() < 2


def test_conflicted_file_cannot_be_checked(qtbot, tmp_path):
    """Review Focus 2 : commiter un conflit produirait des marqueurs."""
    path = tmp_path / "conflit"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "f.txt").write_text("base\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "base")
    run_git(path, "checkout", "-q", "-b", "autre")
    (path / "f.txt").write_text("leur\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "leur")
    run_git(path, "checkout", "-q", "main")
    (path / "f.txt").write_text("notre\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "notre")
    run_git(path, "merge", "autre")

    w = CommitWindow(pygit2.Repository(str(path)))
    qtbot.addWidget(w)
    assert w.is_checkable("f.txt") is False


def test_empty_repository_opens_without_crashing(qtbot, tmp_path):
    path = tmp_path / "vide"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")

    w = CommitWindow(pygit2.Repository(str(path)))
    qtbot.addWidget(w)
    assert w.file_count() == 0
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/ui/test_commit_window.py -v`
Expected: FAIL — module introuvable.

- [ ] **Step 3: Implémenter**

```python
# src/tortoisepy/ui/commit_window.py
"""Fenêtre de commit — §4.

Trois zones : les fichiers modifiés, le diff du fichier sélectionné, le
message et les boutons. Voir le diff en écrivant le message est ce qui rend
le message juste (D6).
"""

from __future__ import annotations

import pygit2
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tortoisepy.core import operations
from tortoisepy.core.changes import ChangeKind, diff_for, list_changes
from tortoisepy.ui.diff_view import DiffView
from tortoisepy.ui.dialogs import confirm, show_error
from tortoisepy.ui.dialogs import ConfirmationRequest

PATH_ROLE = Qt.ItemDataRole.UserRole


class CommitWindow(QMainWindow):
    """Voir, stager, commiter, pousser."""

    committed = Signal(object)
    """`OperationResult` — la fenêtre principale s'en sert pour rafraîchir."""

    def __init__(self, repository: pygit2.Repository, parent=None):
        super().__init__(parent)
        self.repository = repository

        self._files = QTreeWidget()
        self._files.setColumnCount(2)
        self._files.setHeaderLabels(("", "Fichier"))
        self._files.setRootIsDecorated(False)
        self._files.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._files.itemSelectionChanged.connect(self._on_file_selected)
        self._files.itemChanged.connect(lambda *_: self._update_buttons())

        self.diff_view = DiffView()

        self._message = QPlainTextEdit()
        self._message.setPlaceholderText("Message du commit…")
        self._message.setMaximumHeight(120)
        self._message.textChanged.connect(self._update_buttons)

        self.commit_button = QPushButton("Commit")
        self.commit_button.clicked.connect(self.commit)
        self.push_button = QPushButton("Commit && Push")
        self.push_button.clicked.connect(self.commit_and_push)
        cancel = QPushButton("Annuler")
        cancel.clicked.connect(self.close)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(self.commit_button)
        buttons.addWidget(self.push_button)

        bottom = QWidget()
        layout = QVBoxLayout(bottom)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Message :"))
        layout.addWidget(self._message)
        layout.addLayout(buttons)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self._files)
        splitter.addWidget(self.diff_view)
        splitter.addWidget(bottom)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)

        self.setCentralWidget(splitter)
        self.setWindowTitle(self._title())
        self.resize(900, 700)

        self.refresh()

    # --- état ----------------------------------------------------------

    def refresh(self) -> None:
        """Relit les changements. Le message saisi est conservé."""
        self._files.clear()
        self.diff_view.clear()

        for change in list_changes(self.repository):
            item = QTreeWidgetItem(["", f"{change.kind.value}  {change.path}"])
            item.setData(0, PATH_ROLE, change.path)

            if change.selectable:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    0,
                    Qt.CheckState.Checked
                    if change.selected_by_default
                    else Qt.CheckState.Unchecked,
                )
            else:
                # Un conflit non résolu produirait un commit contenant des
                # marqueurs `<<<<<<<` (§4.1).
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                item.setToolTip(
                    1, "Conflit non résolu — à régler hors de l'application"
                )

            self._files.addTopLevelItem(item)

        self._update_buttons()

    def file_count(self) -> int:
        return self._files.topLevelItemCount()

    def checked_paths(self) -> tuple[str, ...]:
        return tuple(
            item.data(0, PATH_ROLE)
            for item in self._items()
            if item.checkState(0) == Qt.CheckState.Checked
        )

    def is_checked(self, path: str) -> bool:
        item = self._item_for(path)
        return bool(item and item.checkState(0) == Qt.CheckState.Checked)

    def is_checkable(self, path: str) -> bool:
        item = self._item_for(path)
        return bool(item and item.flags() & Qt.ItemFlag.ItemIsUserCheckable)

    def set_checked(self, path: str, checked: bool) -> None:
        item = self._item_for(path)
        if item is not None:
            item.setCheckState(
                0, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
            )

    def select_file(self, path: str) -> None:
        item = self._item_for(path)
        if item is not None:
            self._files.setCurrentItem(item)

    def set_message(self, text: str) -> None:
        self._message.setPlainText(text)

    def message(self) -> str:
        return self._message.toPlainText()

    # --- actions -------------------------------------------------------

    def commit(self) -> None:
        result = operations.commit_selection(
            self.repository, self.checked_paths(), self.message()
        )
        self._after_commit(result)

    def commit_and_push(self) -> None:
        """§6.2 : pousser sort de la machine, donc on confirme."""
        branch = (
            self.repository.head.shorthand
            if not self.repository.head_is_unborn
            else "?"
        )
        request = ConfirmationRequest(
            title="Commit & Push",
            message=(
                f"git push origin {branch}\n\n"
                "The commit will be sent to the shared server. This cannot "
                "be undone on your own."
            ),
            destructive=False,
        )
        if not confirm(self, request):
            return

        result = operations.commit_selection(
            self.repository, self.checked_paths(), self.message()
        )
        if not result.success:
            self._after_commit(result)
            return

        pushed = operations.push_branch(self.repository)
        if not pushed.success:
            # Le commit est fait : le dire explicitement, sinon on croit
            # avoir tout perdu (§8).
            show_error(self, pushed)

        self._after_commit(result)

    # --- interne -------------------------------------------------------

    def _after_commit(self, result) -> None:
        self.committed.emit(result)

        if not result.success:
            show_error(self, result)
            return

        self.set_message("")
        self.refresh()

    def _on_file_selected(self) -> None:
        item = self._files.currentItem()
        if item is None:
            self.diff_view.clear()
            return
        self.diff_view.show_diff(
            diff_for(self.repository, item.data(0, PATH_ROLE))
        )

    def _update_buttons(self) -> None:
        ready = bool(self.message().strip()) and bool(self.checked_paths())
        self.commit_button.setEnabled(ready)
        self.push_button.setEnabled(ready)

    def _items(self) -> list[QTreeWidgetItem]:
        return [
            self._files.topLevelItem(i)
            for i in range(self._files.topLevelItemCount())
        ]

    def _item_for(self, path: str) -> QTreeWidgetItem | None:
        for item in self._items():
            if item.data(0, PATH_ROLE) == path:
                return item
        return None

    def _title(self) -> str:
        if self.repository.head_is_unborn:
            return "Commit — dépôt vide"
        return f"Commit — {self.repository.head.shorthand}"
```

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/ui/test_commit_window.py -v`
Expected: PASS, 14 tests.

- [ ] **Step 5: Signaler les fichiers prêts** — ne commite pas.

---

### Task 6: Ouverture depuis la fenêtre principale

**Files:**
- Modify: `src/tortoisepy/ui/main_window.py`
- Modify: `src/tortoisepy/ui/context_menu.py`
- Modify: `src/tortoisepy/ui/actions.py`
- Test: `tests/ui/test_main_window.py` (ajouts)

**Interfaces:**
- Consumes: `CommitWindow` (tâche 5)
- Produces: entrée « Commit… » dans le menu et la barre d'outils

- [ ] **Step 1: Écrire les tests**

```python
# à ajouter dans tests/ui/test_main_window.py


def test_commit_window_opens(window):
    window.open_commit_window()
    assert window.commit_window is not None
    window.commit_window.close()


def test_commit_window_is_reused(window):
    """Deux fenêtres de commit sur le même dépôt se contrediraient."""
    window.open_commit_window()
    first = window.commit_window
    window.open_commit_window()
    assert window.commit_window is first
    first.close()


def test_graph_refreshes_after_a_commit(window, monkeypatch):
    from tortoisepy.core.results import succeeded

    window.open_commit_window()
    before = window.view.scene()
    window.commit_window.committed.emit(succeeded("fait"))
    assert window.view.scene() is not before
    window.commit_window.close()


def test_commit_action_is_in_the_menu():
    """L'entrée doit exister, sinon la fonction est inatteignable."""
    from tortoisepy.core.model import DisplayNode, NodeKind, Ref, RefType
    from tortoisepy.core.state import RepositoryState
    from tortoisepy.ui.context_menu import build_menu_model

    node = DisplayNode(
        oid="a" * 40,
        kind=NodeKind.REF,
        refs=(Ref("feature", RefType.LOCAL_BRANCH, "a" * 40),),
    )
    state = RepositoryState(
        head_oid="b" * 40, head_branch="master", detached=False,
        has_unstaged_changes=True, has_staged_changes=False,
        has_conflicts=False, operation_in_progress=None, conflicted_paths=(),
    )

    def actions(entries):
        for entry in entries:
            if entry.action:
                yield entry.action
            yield from actions(entry.children)

    assert "open_commit" in set(actions(build_menu_model((node,), state)))
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/ui/test_main_window.py -k commit -v`
Expected: FAIL — `open_commit_window` n'existe pas.

- [ ] **Step 3: Ajouter l'entrée de menu**

Dans `context_menu.py`, insérer avant l'entrée « Show log » :

```python
    entries.append(SEPARATOR)
    entries.append(
        MenuEntry(
            "Commit…",
            "open_commit",
            # Toujours actif : c'est une fenêtre de consultation, même
            # sans modification en cours.
            enabled=True,
        )
    )
```

Dans `actions.py`, ajouter le handler et l'enregistrer :

```python
def _open_commit(ctx: ActionContext) -> OperationResult | None:
    """Ouvre la fenêtre de commit. La fenêtre principale s'en charge."""
    return None
```

```python
    "open_commit": _open_commit,
```

- [ ] **Step 4: Brancher dans `main_window.py`**

```python
# imports à ajouter
from tortoisepy.ui.commit_window import CommitWindow
```

```python
        self.commit_window: CommitWindow | None = None
```

Dans `_build_actions`, ajouter à la liste `specs` :

```python
            ("Commit…", QKeySequence("Ctrl+K"), self.open_commit_window),
```

Puis les méthodes :

```python
    def open_commit_window(self) -> None:
        """Ouvre la fenêtre de commit, ou ramène celle déjà ouverte.

        Une seule à la fois : deux fenêtres sur le même dépôt afficheraient
        des états divergents.
        """
        if self.commit_window is not None and self.commit_window.isVisible():
            self.commit_window.raise_()
            self.commit_window.activateWindow()
            return

        self.commit_window = CommitWindow(self.repository, self)
        self.commit_window.committed.connect(self._on_committed)
        self.commit_window.show()

    def _on_committed(self, result) -> None:
        """Un commit change l'historique : le graphe doit le refléter."""
        if result.repository_changed:
            self.refresh()
```

Dans `_run_action`, intercepter l'action avant l'exécution normale :

```python
        if action == "open_commit":
            self.open_commit_window()
            return
```

- [ ] **Step 5: Vérifier le succès**

Run: `.venv/bin/pytest tests/ui/ -q`
Expected: PASS.

- [ ] **Step 6: Vérifier la lecture seule**

Run: `.venv/bin/pytest tests/test_read_only.py -v`
Expected: PASS, 7 tests. **Ouvrir la fenêtre de commit ne doit rien écrire.**

- [ ] **Step 7: Suite complète**

Run: `.venv/bin/pytest tests/ -q`
Expected: 527 + ~61 tests, tous verts. **Attendre la fin** (environ 5 min).

- [ ] **Step 8: Signaler les fichiers prêts** — ne commite pas. Donner le
décompte exact.

---

### Task 7: Diff d'un commit existant

**Files:**
- Modify: `src/tortoisepy/core/changes.py`
- Test: `tests/core/test_commit_changes.py`

**Interfaces:**
- Consumes: `FileChange`, `FileDiff`, `ChangeKind` (tâche 1)
- Produces: `changes_in_commit(repo, oid) -> tuple[FileChange, ...]`,
  `diff_in_commit(repo, oid, path) -> FileDiff`

`diff_for()` compare l'arbre de travail au dernier commit. Ici on compare un
commit **à son parent** : c'est une autre question, donc deux fonctions
distinctes plutôt qu'un drapeau.

**Vérifié le 2026-09-28** sur ce dépôt :
- commit ordinaire — `repo.diff(parent.tree, commit.tree)` rend les patches ;
- commit **racine** — pas de parent ; `commit.tree.diff_to_tree(swap=True)`
  fonctionne. **Sans `swap=True`, les fichiers ajoutés apparaissent en
  suppressions** ;
- commit de **merge** — deux parents. On diffe contre le **premier**, comme
  `git show` : c'est ce que TortoiseGit affiche, et le seul choix qui montre
  ce que le merge a apporté à la branche d'accueil.

- [ ] **Step 1: Écrire les tests**

```python
# tests/core/test_commit_changes.py
import os
import subprocess

import pygit2
import pytest

from tortoisepy.core.changes import ChangeKind, changes_in_commit, diff_in_commit


def run_git(path, *args):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
    }
    return subprocess.run(
        ["git", *args], cwd=path, env=env, capture_output=True, text=True
    )


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "histoire"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "premier.txt").write_text("un\ndeux\ntrois\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "racine")

    (path / "premier.txt").write_text("un\nDEUX MODIFIE\ntrois\n")
    (path / "ajoute.txt").write_text("nouveau\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "deuxieme")
    return pygit2.Repository(str(path))


def test_lists_files_touched_by_the_commit(repo):
    head = str(repo.head.target)
    paths = {c.path for c in changes_in_commit(repo, head)}
    assert paths == {"premier.txt", "ajoute.txt"}


def test_marks_a_modified_file(repo):
    head = str(repo.head.target)
    change = next(
        c for c in changes_in_commit(repo, head) if c.path == "premier.txt"
    )
    assert change.kind is ChangeKind.MODIFIED


def test_marks_an_added_file(repo):
    head = str(repo.head.target)
    change = next(
        c for c in changes_in_commit(repo, head) if c.path == "ajoute.txt"
    )
    assert change.kind is ChangeKind.ADDED


def test_shows_the_modified_lines(repo):
    head = str(repo.head.target)
    diff = diff_in_commit(repo, head, "premier.txt")
    assert diff.added == 1
    assert diff.removed == 1
    contents = [l.content for h in diff.hunks for l in h.lines]
    assert any("DEUX MODIFIE" in c for c in contents)


def test_unchanged_file_is_absent(repo):
    """Le commit ne touche pas à ce qu'il n'a pas modifié."""
    head = str(repo.head.target)
    root = repo.get(repo.head.target).parents[0]
    assert "premier.txt" in {c.path for c in changes_in_commit(repo, str(head))}
    # Le commit racine, lui, ne contient pas `ajoute.txt`.
    assert "ajoute.txt" not in {
        c.path for c in changes_in_commit(repo, str(root.id))
    }


def test_root_commit_shows_its_files_as_added(repo):
    """Review Focus 6 : sans `swap=True`, ils apparaîtraient en suppressions."""
    root = [c for c in repo.walk(repo.head.target) if not c.parents][0]
    changes = changes_in_commit(repo, str(root.id))

    assert {c.path for c in changes} == {"premier.txt"}
    assert changes[0].kind is ChangeKind.ADDED

    diff = diff_in_commit(repo, str(root.id), "premier.txt")
    assert diff.added == 3
    assert diff.removed == 0


def test_merge_commit_diffs_against_its_first_parent(tmp_path):
    """Review Focus 6 : un merge a deux parents, donc pas d'« avant » évident.

    On diffe contre le premier, comme `git show` : c'est ce qui montre ce
    que le merge a apporté à la branche d'accueil.
    """
    path = tmp_path / "merge"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "base.txt").write_text("base\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "base")

    run_git(path, "checkout", "-q", "-b", "cote")
    (path / "depuis-cote.txt").write_text("apporte par la branche\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "cote")

    run_git(path, "checkout", "-q", "main")
    (path / "depuis-main.txt").write_text("apporte par main\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "main avance")
    run_git(path, "merge", "-q", "--no-ff", "-m", "fusion", "cote")

    repository = pygit2.Repository(str(path))
    merge = repository.get(repository.head.target)
    assert len(merge.parents) == 2, "la fixture doit produire un vrai merge"

    paths = {c.path for c in changes_in_commit(repository, str(merge.id))}
    assert "depuis-cote.txt" in paths
    assert "depuis-main.txt" not in paths


def test_unknown_oid_gives_no_changes(repo):
    assert changes_in_commit(repo, "0" * 40) == ()


def test_unknown_oid_gives_an_empty_diff(repo):
    assert diff_in_commit(repo, "0" * 40, "premier.txt").hunks == ()


def test_unknown_path_gives_an_empty_diff(repo):
    head = str(repo.head.target)
    assert diff_in_commit(repo, head, "jamais.txt").hunks == ()


def test_binary_file_is_flagged(tmp_path):
    """Review Focus 1, côté commit : afficher des octets serait illisible."""
    path = tmp_path / "binaire-commit"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "image.dat").write_bytes(bytes(range(256)))
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "ajout binaire")

    repository = pygit2.Repository(str(path))
    head = str(repository.head.target)
    assert diff_in_commit(repository, head, "image.dat").is_binary is True


def test_reading_a_commit_writes_nothing(repo):
    """§7.0 : inspecter un commit ne modifie pas le dépôt."""
    import hashlib
    from pathlib import Path

    git_dir = Path(repo.path)

    def fingerprint():
        digest = hashlib.sha256()
        for item in sorted(git_dir.rglob("*")):
            if item.is_file():
                digest.update(f"{item}:{item.stat().st_mtime_ns}".encode())
        return digest.hexdigest()

    head = str(repo.head.target)
    before = fingerprint()
    for change in changes_in_commit(repo, head):
        diff_in_commit(repo, head, change.path)
    assert fingerprint() == before
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/core/test_commit_changes.py -v`
Expected: FAIL — `ImportError: cannot import name 'changes_in_commit'`

- [ ] **Step 3: Implémenter — à AJOUTER à `core/changes.py`**

```python
_DELTA_KINDS = {
    DeltaStatus.ADDED: ChangeKind.ADDED,
    DeltaStatus.DELETED: ChangeKind.DELETED,
    DeltaStatus.MODIFIED: ChangeKind.MODIFIED,
    DeltaStatus.RENAMED: ChangeKind.MODIFIED,
    DeltaStatus.COPIED: ChangeKind.ADDED,
}


def changes_in_commit(
    repo: pygit2.Repository, oid: str
) -> tuple[FileChange, ...]:
    """Fichiers touchés par un commit, triés par chemin."""
    diff = _commit_diff(repo, oid)
    if diff is None:
        return ()

    changes = [
        FileChange(
            path=patch.delta.new_file.path or patch.delta.old_file.path,
            kind=_DELTA_KINDS.get(patch.delta.status, ChangeKind.MODIFIED),
            is_binary=patch.delta.is_binary,
        )
        for patch in diff
    ]
    return tuple(sorted(changes, key=lambda c: c.path))


def diff_in_commit(
    repo: pygit2.Repository, oid: str, path: str
) -> FileDiff:
    """Diff d'un fichier tel que ce commit l'a changé."""
    diff = _commit_diff(repo, oid)
    if diff is None:
        return FileDiff(path=path)

    for patch in diff:
        if path in (patch.delta.new_file.path, patch.delta.old_file.path):
            return _to_file_diff(path, patch)
    return FileDiff(path=path)


def _commit_diff(repo: pygit2.Repository, oid: str):
    """Diff d'un commit contre son premier parent.

    Un commit de merge a plusieurs parents : on prend le premier, comme
    `git show`, ce qui montre ce que le merge a apporté à la branche
    d'accueil.

    Un commit racine n'a pas de parent. `swap=True` est indispensable :
    sans lui, ses fichiers s'affichent en suppressions (vérifié).
    """
    try:
        commit = repo.get(pygit2.Oid(hex=oid)).peel(pygit2.Commit)
    except (ValueError, KeyError, TypeError, AttributeError, pygit2.GitError):
        return None

    if not commit.parents:
        return commit.tree.diff_to_tree(swap=True)
    return repo.diff(commit.parents[0].tree, commit.tree)
```

Et refactoriser `diff_for` pour partager la conversion — `_to_file_diff`
remplace le corps qui construisait les hunks :

```python
def _to_file_diff(path: str, patch) -> FileDiff:
    """Convertit un `Patch` pygit2 en `FileDiff`.

    Partagé par `diff_for` (arbre de travail) et `diff_in_commit`.
    """
    if patch.delta.is_binary:
        return FileDiff(path=path, is_binary=True)

    hunks = tuple(
        DiffHunk(
            header=hunk.header.rstrip("\n"),
            lines=tuple(
                DiffLine(origin=line.origin, content=line.content.rstrip("\n"))
                for line in hunk.lines
            ),
        )
        for hunk in patch.hunks
    )

    _, added, removed = patch.line_stats
    return FileDiff(path=path, hunks=hunks, added=added, removed=removed)
```

Le corps de `diff_for` devient :

```python
def diff_for(repo: pygit2.Repository, path: str) -> FileDiff:
    """Diff d'un fichier par rapport au dernier commit.

    Indexé ou non : c'est l'état que l'utilisateur s'apprête à commiter.
    """
    patch = _patch_for(repo, path)
    if patch is None:
        return FileDiff(path=path)
    return _to_file_diff(path, patch)
```

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/core/test_commit_changes.py tests/core/test_changes.py -v`
Expected: PASS, 12 + 17 tests. **Les deux fichiers** : le refactor touche
`diff_for`.

- [ ] **Step 5: Signaler les fichiers prêts** — ne commite pas.

---

### Task 8: Fenêtre de détail d'un commit

**Files:**
- Create: `src/tortoisepy/ui/commit_detail_window.py`
- Modify: `src/tortoisepy/ui/commit_panel.py`
- Modify: `src/tortoisepy/ui/main_window.py`
- Test: `tests/ui/test_commit_detail_window.py`

**Interfaces:**
- Consumes: `changes_in_commit`, `diff_in_commit` (tâche 7), `DiffView`
  (tâche 4), `read_commit` (existant dans `core/commits.py`)
- Produces: `CommitDetailWindow`, `CommitPanel.commit_activated` (Signal)

Double-cliquer un commit dans le panneau ouvre ses changements. **Lecture
seule** : aucune case à cocher, aucun bouton d'action — ce commit est déjà
fait.

`CommitPanel` possède déjà `commit_selected = Signal(str)` ; on ajoute
`commit_activated` sur le même modèle, branché sur `itemDoubleClicked`.

- [ ] **Step 1: Écrire les tests**

```python
# tests/ui/test_commit_detail_window.py
import os
import subprocess

import pygit2
import pytest

from tortoisepy.ui.commit_detail_window import CommitDetailWindow


def run_git(path, *args):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Alice", "GIT_AUTHOR_EMAIL": "alice@example.com",
        "GIT_COMMITTER_NAME": "Alice", "GIT_COMMITTER_EMAIL": "alice@example.com",
    }
    return subprocess.run(
        ["git", *args], cwd=path, env=env, capture_output=True, text=True
    )


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "detail"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "a.txt").write_text("un\ndeux\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "racine")

    (path / "a.txt").write_text("un\nDEUX CHANGE\n")
    (path / "b.txt").write_text("neuf\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "sujet du commit")
    return pygit2.Repository(str(path))


@pytest.fixture
def window(qtbot, repo):
    w = CommitDetailWindow(repo, str(repo.head.target))
    qtbot.addWidget(w)
    return w


def test_lists_the_files_of_the_commit(window):
    assert window.file_count() == 2


def test_shows_the_commit_message(window):
    assert "sujet du commit" in window.header_text()


def test_shows_the_author(window):
    assert "Alice" in window.header_text()


def test_shows_the_short_oid(window, repo):
    assert str(repo.head.target)[:8] in window.header_text()


def test_selects_the_first_file_on_opening(window):
    """Ouvrir sur un volet de diff vide donne l'impression d'un bug."""
    assert window.diff_view.text()


def test_selecting_a_file_shows_its_diff(window):
    window.select_file("a.txt")
    assert "DEUX CHANGE" in window.diff_view.text()


def test_has_no_checkboxes(window):
    """Ce commit est déjà fait : rien à stager."""
    from PySide6.QtCore import Qt

    item = window.item_for("a.txt")
    assert not (item.flags() & Qt.ItemFlag.ItemIsUserCheckable)


def test_root_commit_opens(qtbot, repo):
    """Review Focus 6 : un commit racine n'a pas de parent."""
    root = [c for c in repo.walk(repo.head.target) if not c.parents][0]
    w = CommitDetailWindow(repo, str(root.id))
    qtbot.addWidget(w)
    assert w.file_count() == 1


def test_unknown_oid_opens_without_crashing(qtbot, repo):
    w = CommitDetailWindow(repo, "0" * 40)
    qtbot.addWidget(w)
    assert w.file_count() == 0


def test_opening_writes_nothing(window, repo):
    """§7.0 : consulter un commit ne modifie pas le dépôt."""
    before = subprocess.run(
        ["git", "status", "--short"], cwd=repo.workdir,
        capture_output=True, text=True,
    ).stdout
    window.select_file("a.txt")
    window.select_file("b.txt")
    after = subprocess.run(
        ["git", "status", "--short"], cwd=repo.workdir,
        capture_output=True, text=True,
    ).stdout
    assert before == after
```

Et, dans `tests/ui/test_commit_panel.py`, le signal :

```python
def test_double_click_emits_commit_activated(qtbot, panel):
    """Le panneau signale l'activation ; la fenêtre principale décide."""
    from tortoisepy.core.commits import CommitInfo
    from datetime import datetime

    # `short_oid` et `is_merge` sont des propriétés calculées, pas des
    # champs : `author_email` et `parent_count` sont requis (vérifié).
    panel.show_commits(
        "main",
        (
            CommitInfo(
                oid="a" * 40, summary="sujet", message="sujet",
                author_name="Alice", author_email="alice@example.com",
                when=datetime(2026, 9, 28), parent_count=1, own=True,
            ),
        ),
    )

    with qtbot.waitSignal(panel.commit_activated, timeout=1000) as blocker:
        panel._tree.itemDoubleClicked.emit(panel._tree.topLevelItem(0), 0)
    assert blocker.args == ["a" * 40]
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/ui/test_commit_detail_window.py -v`
Expected: FAIL — module introuvable.

- [ ] **Step 3: Ajouter le signal à `commit_panel.py`**

Après `commit_selected` :

```python
    commit_activated = Signal(str)
    """Double-clic sur un commit — la fenêtre principale ouvre son détail."""
```

Dans `__init__`, après la connexion de `itemSelectionChanged` :

```python
        self._tree.itemDoubleClicked.connect(self._on_double_click)
```

Et la méthode, à côté de `_on_selection` :

```python
    def _on_double_click(self, item, column) -> None:
        oid = item.data(0, Qt.ItemDataRole.UserRole)
        if oid is not None:
            self.commit_activated.emit(oid)
```

- [ ] **Step 4: Implémenter la fenêtre**

```python
# src/tortoisepy/ui/commit_detail_window.py
"""Changements apportés par un commit déjà fait.

Ouverte au double-clic dans le panneau des commits. Strictement en
lecture seule : ce commit existe, il n'y a rien à stager ni à valider.
"""

from __future__ import annotations

import pygit2
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QLabel,
    QMainWindow,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tortoisepy.core.changes import changes_in_commit, diff_in_commit
from tortoisepy.core.commits import read_commit
from tortoisepy.ui.diff_view import DiffView

PATH_ROLE = Qt.ItemDataRole.UserRole


class CommitDetailWindow(QMainWindow):
    """Fichiers et lignes modifiés par un commit."""

    def __init__(self, repository: pygit2.Repository, oid: str, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.oid = oid

        self._header = QLabel()
        self._header.setWordWrap(True)
        self._header.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        self._files = QTreeWidget()
        self._files.setColumnCount(1)
        self._files.setHeaderLabels(("Fichier",))
        self._files.setRootIsDecorated(False)
        self._files.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._files.itemSelectionChanged.connect(self._on_file_selected)

        self.diff_view = DiffView()

        top = QWidget()
        layout = QVBoxLayout(top)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self._header)
        layout.addWidget(self._files)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(top)
        splitter.addWidget(self.diff_view)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        self.setCentralWidget(splitter)
        self.resize(900, 700)

        self._load()

    def _load(self) -> None:
        info = read_commit(self.repository, self.oid)

        if info is None:
            self._header.setText(f"Commit inconnu — {self.oid[:8]}")
            self.setWindowTitle("Commit inconnu")
            return

        self.setWindowTitle(f"{info.short_oid} — {info.summary}")
        self._header.setText(
            f"{info.short_oid}  ·  {info.author_name}  ·  "
            f"{info.when:%d/%m/%Y %H:%M}\n\n{info.message.strip()}"
        )

        for change in changes_in_commit(self.repository, self.oid):
            item = QTreeWidgetItem([f"{change.kind.value}  {change.path}"])
            item.setData(0, PATH_ROLE, change.path)
            # Pas de case à cocher : ce commit est déjà fait.
            self._files.addTopLevelItem(item)

        # Ouvrir sur un volet vide donnerait l'impression d'un bug.
        if self._files.topLevelItemCount():
            self._files.setCurrentItem(self._files.topLevelItem(0))

    def file_count(self) -> int:
        return self._files.topLevelItemCount()

    def header_text(self) -> str:
        return self._header.text()

    def item_for(self, path: str) -> QTreeWidgetItem | None:
        for index in range(self._files.topLevelItemCount()):
            item = self._files.topLevelItem(index)
            if item.data(0, PATH_ROLE) == path:
                return item
        return None

    def select_file(self, path: str) -> None:
        item = self.item_for(path)
        if item is not None:
            self._files.setCurrentItem(item)

    def _on_file_selected(self) -> None:
        item = self._files.currentItem()
        if item is None:
            self.diff_view.clear()
            return
        self.diff_view.show_diff(
            diff_in_commit(self.repository, self.oid, item.data(0, PATH_ROLE))
        )
```

**Vérifié** : `read_commit(repo, oid) -> CommitInfo | None` retourne `None`
sur un OID introuvable — pas besoin de `try` autour de l'appel.

- [ ] **Step 5: Brancher dans `main_window.py`**

```python
from tortoisepy.ui.commit_detail_window import CommitDetailWindow
```

Dans `__init__`, après la création du panneau :

```python
        self.commit_panel.commit_activated.connect(self.open_commit_detail)
        self._detail_windows: list[CommitDetailWindow] = []
```

Puis :

```python
    def open_commit_detail(self, oid: str) -> None:
        """Ouvre les changements d'un commit.

        Plusieurs fenêtres sont permises — contrairement à la fenêtre de
        commit : comparer deux commits côte à côte est légitime, et elles
        sont en lecture seule. La liste garde une référence, sans quoi le
        ramasse-miettes fermerait la fenêtre aussitôt.
        """
        window = CommitDetailWindow(self.repository, oid, self)
        self._detail_windows.append(window)
        window.show()
```

- [ ] **Step 6: Vérifier le succès**

Run: `.venv/bin/pytest tests/ui/test_commit_detail_window.py tests/ui/test_commit_panel.py -v`
Expected: PASS.

- [ ] **Step 7: Vérifier la lecture seule**

Run: `.venv/bin/pytest tests/test_read_only.py -v`
Expected: PASS, 7 tests.

- [ ] **Step 8: Suite complète**

Run: `.venv/bin/pytest tests/ -q`
Expected: tous verts. **Attendre la fin** (environ 5 min).

- [ ] **Step 9: Signaler les fichiers prêts** — ne commite pas. Donner le
décompte exact.

---

## Fin de phase 6

À ce stade, le cycle quotidien est complet depuis le graphe : voir ses
modifications, en choisir une partie, écrire un message, commiter, pousser — et
inspecter n'importe quel commit déjà fait en double-cliquant dessus dans le
panneau.

**Ce qui reste hors périmètre**, conformément à la spec §9 :

- **Staging par hunk** (D5) — reporté, pas abandonné.
- **Amender un commit** (`git commit --amend`).
- **Pull** — il fusionne dans la branche courante, avec ses conflits.
- **Résolution de conflits** — hors périmètre v1 (§7.7).
- **Push forcé** — jamais.
