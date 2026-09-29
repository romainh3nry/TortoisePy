# tortoisePy — Plan d'implémentation, phase 8 : pull et conflits

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Récupérer les changements distants depuis le graphe — en avançant
simplement quand c'est possible, en demandant merge ou rebase quand les deux
côtés ont avancé, et en donnant de quoi résoudre les conflits sans jamais
rester coincé.

**Architecture:** `core/pull.py` analyse et exécute (fast-forward, merge,
rebase). `core/conflicts.py` liste et résout les conflits. `ui/` ajoute un
bouton Pull, un choix merge/rebase et une fenêtre de résolution. Tout s'appuie
sur `abort_operation`, déjà en place, qui garantit la sortie de secours.

**Tech Stack:** Python 3.13, pygit2 1.20, PySide6 6.11, pytest-qt.

**Spec:** `docs/superpowers/specs/2026-09-28-tortoisepy-pull-design.md`

**Prérequis:** phases 1 à 7 terminées, 700 tests passent.

## Global Constraints

- **Aucune commande `git` sur le dépôt tortoisePy.** Les étapes « commit » du
  modèle de plan sont remplacées par « signaler les fichiers prêts ». Les
  fixtures peuvent invoquer `git` via `subprocess` sur des dépôts temporaires.
- **On ne doit jamais rester coincé.** Tout chemin menant à un conflit expose
  un « Abort » qui restaure l'état d'avant. C'est ce qui rend le reste
  acceptable.
- **Ne jamais commiter un conflit non résolu** : le commit contiendrait des
  marqueurs `<<<<<<<` (règle établie en phase 6).
- **`state_cleanup()` après tout commit terminant une opération.** La phase 7 a
  montré qu'un commit créé sans lui laisse `REVERT_HEAD`/`MERGE_MSG` traîner et
  l'interface grise checkout et merge à tort (signalé sur `portfolio`).
- **Rien ne s'écrit sans clic explicite (§7.0).** `tests/test_read_only.py`
  doit rester vert : analyser l'état ne modifie rien.
- **`core/` n'importe jamais PySide6.** Vérifié par `tests/test_architecture.py`.
- **Le rendu visuel validé ne doit pas être dégradé** : aucune tâche ne touche
  `layout/`, `ui/graph_items.py`, ni une couleur existante de `theme.py`.
- **Libellés d'interface en anglais**, commentaires et docstrings **en français**.
- **Jamais de `pull --force` ni de `rebase --onto`.**
- **API vérifiées le 2026-09-29** sur pygit2 1.20 :
  - `repo.merge_analysis(oid)` rend `(MergeAnalysis, MergePreference)` ;
    `UP_TO_DATE=2`, `FASTFORWARD=4`, `NORMAL=1`, `UNBORN=8`.
  - Le rebase se démarre avec **`repo.rebase_init(branch=…, upstream=None,
    onto=…)`** — `init_rebase` **n'existe pas**. `rebase_open()` reprend un
    rebase interrompu ; l'objet a `commit()`, `finish()`, `abort()`.
  - `repo.index.conflicts['chemin']` rend `(ancestor, ours, theirs)` ;
    `del index.conflicts['chemin']` fonctionne (`__delitem__` présent),
    `path in index` et `index.remove(path)` aussi, et `Blob.is_binary`
    existe — les quatre sont utilisés par la tâche 2.
  - `guarded(summary, changed_on_error=...)`,
    `succeeded(summary, repository_changed=...)` et
    `failed(summary, git_error, repository_changed=...)` ont bien ces
    signatures.
  - `abort_operation` (phase 5) restaure : conflits effacés, HEAD inchangé,
    fichier revenu à la version locale, état à `NONE`. **Vérifié sur un
    conflit réel.**
  - Fast-forward vérifié : `ref.set_target(upstream)` + `checkout_tree` +
    `reset(HARD)` -> HEAD rejoint la distante, arbre propre.
  - Merge conflictuel conclu vérifié : résolution par choix de version, puis
    `create_commit` à **deux parents** + `state_cleanup()` -> dépôt propre et
    `git status` d'accord.

## Review Focus

Cas que la spec implique et qu'aucune tâche n'exercerait sans y penser.

1. **Pull sans fetch préalable** — l'analyse porterait sur une ref distante
   périmée et conclurait « à jour » à tort. Pull doit toujours fetcher d'abord.
   *(tâche 1)*
2. **Arbre de travail sale** — un fast-forward écraserait des modifications non
   commitées. Doit refuser avant de toucher à quoi que ce soit. *(tâche 1)*
3. **Fichier binaire en conflit** — aucun choix « ligne à ligne » n'a de sens ;
   « garder la mienne / prendre la distante » doit rester possible. *(tâche 2)*
4. **Conflit de suppression** — un côté supprime, l'autre modifie : une des
   trois versions de `index.conflicts` est `None`. Ne doit pas planter.
   *(tâche 2)*
5. **Abandon en plein conflit** — l'utilisateur ferme la fenêtre sans résoudre.
   Le dépôt ne doit pas rester en état de fusion silencieux. *(tâche 4)*

---

### Task 1: Analyser et exécuter le pull

**Files:**
- Create: `src/tortoisepy/core/pull.py`
- Test: `tests/core/test_pull.py`

**Interfaces:**
- Consumes: `OperationResult`, `guarded`, `succeeded`, `failed`,
  `fetch_remote` (phase 5)
- Produces: `PullKind`, `PullState`, `analyse_pull(repo)`,
  `pull_fast_forward(repo)`, `pull_merge(repo)`, `pull_rebase(repo)`

- [ ] **Step 1: Écrire les tests**

```python
# tests/core/test_pull.py
import os
import subprocess

import pygit2
import pytest

from tortoisepy.core.pull import (
    PullKind,
    analyse_pull,
    pull_fast_forward,
    pull_merge,
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


def make_pair(tmp_path, name="p"):
    """Un serveur nu, un clone, un commit de base poussé."""
    bare = tmp_path / f"{name}.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", str(bare)], capture_output=True
    )
    work = tmp_path / name
    subprocess.run(
        ["git", "clone", "-q", str(bare), str(work)], capture_output=True
    )
    (work / "f.txt").write_text("ligne1\nligne2\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "base")
    run_git(work, "push", "-q", "origin", "HEAD")
    return bare, work


def advance_remote(tmp_path, bare, contenu="ligne1\nDISTANT\n"):
    """Un tiers pousse une modification."""
    other = tmp_path / "autre"
    subprocess.run(
        ["git", "clone", "-q", str(bare), str(other)], capture_output=True
    )
    (other / "f.txt").write_text(contenu)
    run_git(other, "add", ".")
    run_git(other, "commit", "-q", "-m", "avance distante")
    run_git(other, "push", "-q")


def test_up_to_date(tmp_path):
    bare, work = make_pair(tmp_path)
    repo = pygit2.Repository(str(work))
    assert analyse_pull(repo).kind is PullKind.UP_TO_DATE


def test_fast_forward_is_detected(tmp_path):
    """Le cas courant : la remote a avancé, rien en local."""
    bare, work = make_pair(tmp_path)
    advance_remote(tmp_path, bare)
    run_git(work, "fetch", "-q")

    repo = pygit2.Repository(str(work))
    state = analyse_pull(repo)
    assert state.kind is PullKind.FAST_FORWARD
    assert state.incoming == 1


def test_fast_forward_brings_the_branch_level(tmp_path):
    bare, work = make_pair(tmp_path)
    advance_remote(tmp_path, bare)
    run_git(work, "fetch", "-q")

    repo = pygit2.Repository(str(work))
    result = pull_fast_forward(repo)
    assert result.success is True, result.git_error

    fresh = pygit2.Repository(str(work))
    branch = fresh.branches[fresh.head.shorthand]
    assert branch.target == branch.upstream.target
    assert (work / "f.txt").read_text() == "ligne1\nDISTANT\n"
    assert fresh.state() == pygit2.enums.RepositoryState.NONE


def test_divergence_is_detected(tmp_path):
    bare, work = make_pair(tmp_path)
    advance_remote(tmp_path, bare)
    (work / "f.txt").write_text("ligne1\nLOCAL\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "local")
    run_git(work, "fetch", "-q")

    repo = pygit2.Repository(str(work))
    state = analyse_pull(repo)
    assert state.kind is PullKind.DIVERGED
    assert state.incoming >= 1
    assert state.outgoing >= 1


def test_merge_without_conflict(tmp_path):
    """Deux fichiers différents : la fusion passe toute seule."""
    bare, work = make_pair(tmp_path)
    other = tmp_path / "autre"
    subprocess.run(
        ["git", "clone", "-q", str(bare), str(other)], capture_output=True
    )
    (other / "leur.txt").write_text("leur\n")
    run_git(other, "add", ".")
    run_git(other, "commit", "-q", "-m", "leur")
    run_git(other, "push", "-q")

    (work / "notre.txt").write_text("notre\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "notre")
    run_git(work, "fetch", "-q")

    repo = pygit2.Repository(str(work))
    result = pull_merge(repo)
    assert result.success is True, result.git_error

    fresh = pygit2.Repository(str(work))
    assert fresh.state() == pygit2.enums.RepositoryState.NONE
    assert len(fresh.get(fresh.head.target).parents) == 2
    assert (work / "leur.txt").exists()
    assert (work / "notre.txt").exists()


def test_merge_with_conflict_reports_it(tmp_path):
    """Un conflit n'est pas un échec : l'UI doit pouvoir le résoudre."""
    bare, work = make_pair(tmp_path)
    advance_remote(tmp_path, bare)
    (work / "f.txt").write_text("ligne1\nLOCAL\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "local")
    run_git(work, "fetch", "-q")

    repo = pygit2.Repository(str(work))
    result = pull_merge(repo)

    assert result.success is False
    assert "conflict" in (result.git_error or "").lower()

    fresh = pygit2.Repository(str(work))
    assert fresh.index.conflicts is not None


def test_pull_refuses_a_dirty_tree(tmp_path):
    """Review Focus 2 : un fast-forward écraserait le travail en cours."""
    bare, work = make_pair(tmp_path)
    advance_remote(tmp_path, bare)
    run_git(work, "fetch", "-q")
    (work / "f.txt").write_text("modification non commitée\n")

    repo = pygit2.Repository(str(work))
    result = pull_fast_forward(repo)

    assert result.success is False
    assert "uncommitted" in (result.git_error or "").lower()
    # Le travail en cours est intact.
    assert (work / "f.txt").read_text() == "modification non commitée\n"


def test_no_remote(tmp_path):
    path = tmp_path / "solo"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "f.txt").write_text("a\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "base")

    state = analyse_pull(pygit2.Repository(str(path)))
    assert state.kind is PullKind.UNAVAILABLE
    assert state.reason


def test_detached_head(tmp_path):
    bare, work = make_pair(tmp_path)
    run_git(work, "checkout", "-q", "--detach")

    state = analyse_pull(pygit2.Repository(str(work)))
    assert state.kind is PullKind.UNAVAILABLE
    assert state.reason


def test_branch_without_upstream(tmp_path):
    bare, work = make_pair(tmp_path)
    run_git(work, "checkout", "-q", "-b", "sans-suivi")

    state = analyse_pull(pygit2.Repository(str(work)))
    assert state.kind is PullKind.UNAVAILABLE
    assert state.reason


def test_analysing_writes_nothing(tmp_path):
    """§7.0 : analyser ne modifie pas le dépôt."""
    import hashlib
    from pathlib import Path

    bare, work = make_pair(tmp_path)
    repo = pygit2.Repository(str(work))
    git_dir = Path(repo.path)

    def fingerprint():
        digest = hashlib.sha256()
        for item in sorted(git_dir.rglob("*")):
            if item.is_file():
                digest.update(f"{item}:{item.stat().st_mtime_ns}".encode())
        return digest.hexdigest()

    before = fingerprint()
    analyse_pull(repo)
    assert fingerprint() == before


def test_state_is_frozen(tmp_path):
    import dataclasses

    bare, work = make_pair(tmp_path)
    state = analyse_pull(pygit2.Repository(str(work)))
    with pytest.raises(dataclasses.FrozenInstanceError):
        state.kind = PullKind.UP_TO_DATE
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/core/test_pull.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tortoisepy.core.pull'`

- [ ] **Step 3: Implémenter**

```python
# src/tortoisepy/core/pull.py
"""Récupérer les changements distants — §3 à §5 de la spec phase 8.

Trois situations, distinguées par `merge_analysis` : rien à faire, simple
avance, ou divergence. Seule la troisième pose une question à
l'utilisateur ; c'est `ui/` qui la pose, pas ce module.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pygit2
from pygit2.enums import MergeAnalysis, ResetMode

from tortoisepy.core.results import OperationResult, failed, guarded, succeeded


class PullKind(Enum):
    UP_TO_DATE = "up_to_date"
    FAST_FORWARD = "fast_forward"
    DIVERGED = "diverged"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class PullState:
    kind: PullKind
    branch: str | None = None
    remote_name: str | None = None
    incoming: int = 0
    """Commits présents en amont et pas ici."""

    outgoing: int = 0
    """Commits présents ici et pas en amont — non nul en cas de divergence."""

    reason: str = ""
    """Pourquoi on ne peut pas récupérer ; vide quand on peut."""


def analyse_pull(repo: pygit2.Repository) -> PullState:
    """Que se passerait-il si on récupérait maintenant ?

    **Purement descriptif** : n'écrit rien, ne fetch pas. L'appelant fetch
    d'abord, sans quoi l'analyse porterait sur une ref périmée (§3).
    """
    branch = _current_branch(repo)
    if branch is None:
        return PullState(PullKind.UNAVAILABLE, reason="no branch checked out")

    upstream = branch.upstream
    if upstream is None:
        return PullState(
            PullKind.UNAVAILABLE,
            branch=branch.branch_name,
            reason="branch has no upstream",
        )

    try:
        analysis, _ = repo.merge_analysis(upstream.target)
        ahead, behind = repo.ahead_behind(branch.target, upstream.target)
    except (pygit2.GitError, KeyError, ValueError):
        return PullState(
            PullKind.UNAVAILABLE,
            branch=branch.branch_name,
            reason="cannot compare with the upstream branch",
        )

    common = {
        "branch": branch.branch_name,
        "remote_name": upstream.remote_name,
        "incoming": behind,
        "outgoing": ahead,
    }

    if analysis & MergeAnalysis.UP_TO_DATE:
        return PullState(PullKind.UP_TO_DATE, **common)
    if analysis & MergeAnalysis.FASTFORWARD:
        return PullState(PullKind.FAST_FORWARD, **common)
    return PullState(PullKind.DIVERGED, **common)


@guarded("Pull")
def pull_fast_forward(repo: pygit2.Repository) -> OperationResult:
    """Amène la branche au niveau de l'amont, sans commit de fusion.

    Vérifié : positionner la ref puis remettre l'arbre à jour suffit — la
    branche rejoint la distante et l'arbre reste propre.
    """
    state = analyse_pull(repo)
    if state.kind is PullKind.UNAVAILABLE:
        return failed("Pull", state.reason)
    if state.kind is PullKind.UP_TO_DATE:
        return succeeded("Already up to date", repository_changed=False)

    blocking = _uncommitted_changes(repo)
    if blocking:
        # Un fast-forward écrase l'arbre : refuser AVANT d'y toucher.
        return failed(
            "Pull",
            f"uncommitted changes would be overwritten ({blocking})",
            repository_changed=False,
        )

    branch = _current_branch(repo)
    target = branch.upstream.target

    reference = repo.lookup_reference(repo.head.name)
    reference.set_target(target)
    repo.checkout_tree(repo.get(target))
    repo.reset(target, ResetMode.HARD)

    plural = "" if state.incoming == 1 else "s"
    return succeeded(
        f"Pulled {state.incoming} commit{plural} from {state.remote_name}"
    )


@guarded("Pull", changed_on_error=True)
def pull_merge(repo: pygit2.Repository) -> OperationResult:
    """Fusionne l'amont dans la branche courante.

    Un conflit n'est **pas** une erreur du programme : il est rapporté comme
    un échec pour que l'interface ouvre la fenêtre de résolution, et le
    dépôt reste en état de fusion, prêt à être résolu ou abandonné.
    """
    state = analyse_pull(repo)
    if state.kind is PullKind.UNAVAILABLE:
        return failed("Pull", state.reason, repository_changed=False)
    if state.kind is PullKind.UP_TO_DATE:
        return succeeded("Already up to date", repository_changed=False)

    blocking = _uncommitted_changes(repo)
    if blocking:
        return failed(
            "Pull",
            f"uncommitted changes would be overwritten ({blocking})",
            repository_changed=False,
        )

    branch = _current_branch(repo)
    target = branch.upstream.target
    repo.merge(target)

    if repo.index.conflicts is not None:
        paths = sorted(
            (ours or theirs).path
            for _, ours, theirs in repo.index.conflicts
            if (ours or theirs) is not None
        )
        return failed("Pull", f"conflicts in: {', '.join(paths)}")

    return _finish_merge(repo, target, state)


@guarded("Pull", changed_on_error=True)
def pull_rebase(repo: pygit2.Repository) -> OperationResult:
    """Rejoue les commits locaux par-dessus l'amont.

    **Réécrit les commits locaux** : l'interface l'annonce avant d'appeler
    (§5). Comme pour la fusion, un conflit est rapporté pour résolution.

    Vérifié : le rebase se démarre avec `rebase_init` — `init_rebase`
    n'existe pas.
    """
    state = analyse_pull(repo)
    if state.kind is PullKind.UNAVAILABLE:
        return failed("Pull", state.reason, repository_changed=False)
    if state.kind is PullKind.UP_TO_DATE:
        return succeeded("Already up to date", repository_changed=False)

    blocking = _uncommitted_changes(repo)
    if blocking:
        return failed(
            "Pull",
            f"uncommitted changes would be overwritten ({blocking})",
            repository_changed=False,
        )

    branch = _current_branch(repo)
    onto = repo.lookup_reference(branch.upstream.name)
    rebase = repo.rebase_init(
        branch=repo.lookup_reference(repo.head.name),
        upstream=None,
        onto=onto,
    )

    signature = _signature(repo)
    for _ in rebase:
        if repo.index.conflicts is not None:
            paths = sorted(
                (ours or theirs).path
                for _, ours, theirs in repo.index.conflicts
                if (ours or theirs) is not None
            )
            return failed("Pull", f"conflicts in: {', '.join(paths)}")
        rebase.commit(committer=signature)

    rebase.finish(committer=signature)
    plural = "" if state.incoming == 1 else "s"
    return succeeded(
        f"Rebased onto {state.incoming} commit{plural} from "
        f"{state.remote_name}"
    )


def _finish_merge(repo, target, state) -> OperationResult:
    """Crée le commit de fusion à deux parents et nettoie l'état.

    `state_cleanup()` est indispensable : sans lui, `MERGE_HEAD` traîne et
    l'interface croit la fusion toujours en cours (leçon de la phase 7).
    """
    signature = _signature(repo)
    tree = repo.index.write_tree()
    repo.create_commit(
        "HEAD",
        signature,
        signature,
        f"Merge branch '{state.remote_name}/{state.branch}'",
        tree,
        [repo.head.target, target],
    )
    repo.state_cleanup()

    plural = "" if state.incoming == 1 else "s"
    return succeeded(
        f"Merged {state.incoming} commit{plural} from {state.remote_name}"
    )


def _uncommitted_changes(repo: pygit2.Repository) -> str:
    """Résumé des modifications non commitées, vide s'il n'y en a pas.

    Les fichiers non suivis ne gênent pas une fusion : seuls comptent les
    fichiers suivis modifiés ou indexés.
    """
    from pygit2.enums import FileStatus

    blocking = FileStatus.WT_MODIFIED | FileStatus.WT_DELETED
    blocking |= FileStatus.INDEX_MODIFIED | FileStatus.INDEX_NEW
    blocking |= FileStatus.INDEX_DELETED

    try:
        touched = [p for p, code in repo.status().items() if code & blocking]
    except pygit2.GitError:
        return ""
    return ", ".join(sorted(touched)[:3])


def _current_branch(repo: pygit2.Repository):
    if repo.head_is_unborn or repo.head_is_detached:
        return None
    try:
        return repo.branches[repo.head.shorthand]
    except (KeyError, pygit2.GitError):
        return None


def _signature(repo: pygit2.Repository) -> pygit2.Signature:
    try:
        return repo.default_signature
    except (KeyError, ValueError):
        return pygit2.Signature("tortoisePy", "tortoisepy@localhost")
```

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/core/test_pull.py tests/test_read_only.py tests/test_architecture.py -v`
Expected: PASS, 13 + 7 + 5 tests.

- [ ] **Step 5: Signaler les fichiers prêts** — ne commite pas.

---

### Task 2: Lister et résoudre les conflits

**Files:**
- Create: `src/tortoisepy/core/conflicts.py`
- Test: `tests/core/test_conflicts.py`

**Interfaces:**
- Consumes: `OperationResult`, `guarded`, `succeeded`, `failed`
- Produces: `Side`, `ConflictedFile`, `list_conflicts(repo)`,
  `resolve_with(repo, path, side)`, `conclude_merge(repo)`

**Vérifié :** retirer l'entrée de `index.conflicts`, ajouter l'`IndexEntry`
du côté choisi, écrire l'index, puis récrire le fichier de travail avec le
contenu du blob retenu. Le conflit disparaît et `git status` est d'accord.

- [ ] **Step 1: Écrire les tests**

```python
# tests/core/test_conflicts.py
import os
import subprocess

import pygit2
import pytest

from tortoisepy.core.conflicts import (
    Side,
    conclude_merge,
    list_conflicts,
    resolve_with,
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
def conflicted(tmp_path):
    """Un dépôt en pleine fusion conflictuelle sur `f.txt`."""
    bare = tmp_path / "s.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], capture_output=True)
    work = tmp_path / "w"
    subprocess.run(["git", "clone", "-q", str(bare), str(work)], capture_output=True)
    (work / "f.txt").write_text("ligne1\nligne2\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "base")
    run_git(work, "push", "-q", "origin", "HEAD")

    other = tmp_path / "o"
    subprocess.run(["git", "clone", "-q", str(bare), str(other)], capture_output=True)
    (other / "f.txt").write_text("ligne1\nDISTANT\n")
    run_git(other, "add", ".")
    run_git(other, "commit", "-q", "-m", "distant")
    run_git(other, "push", "-q")

    (work / "f.txt").write_text("ligne1\nLOCAL\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "local")
    run_git(work, "fetch", "-q")

    repo = pygit2.Repository(str(work))
    repo.merge(repo.branches[repo.head.shorthand].upstream.target)
    assert repo.index.conflicts is not None
    return repo


def test_lists_the_conflicted_file(conflicted):
    files = list_conflicts(conflicted)
    assert [f.path for f in files] == ["f.txt"]


def test_reports_both_sides(conflicted):
    conflict = list_conflicts(conflicted)[0]
    assert conflict.has_ours is True
    assert conflict.has_theirs is True


def test_keep_mine(conflicted):
    resolve_with(conflicted, "f.txt", Side.OURS)
    workdir = conflicted.workdir
    assert open(os.path.join(workdir, "f.txt")).read() == "ligne1\nLOCAL\n"
    assert list_conflicts(pygit2.Repository(conflicted.path)) == ()


def test_take_theirs(conflicted):
    resolve_with(conflicted, "f.txt", Side.THEIRS)
    workdir = conflicted.workdir
    assert open(os.path.join(workdir, "f.txt")).read() == "ligne1\nDISTANT\n"
    assert list_conflicts(pygit2.Repository(conflicted.path)) == ()


def test_concluding_creates_a_merge_commit(conflicted):
    resolve_with(conflicted, "f.txt", Side.THEIRS)
    result = conclude_merge(conflicted)
    assert result.success is True, result.git_error

    fresh = pygit2.Repository(conflicted.path)
    assert len(fresh.get(fresh.head.target).parents) == 2
    assert fresh.state() == pygit2.enums.RepositoryState.NONE


def test_cannot_conclude_while_a_conflict_remains(conflicted):
    """Commiter un conflit produirait des marqueurs `<<<<<<<`."""
    result = conclude_merge(conflicted)
    assert result.success is False
    assert "conflict" in (result.git_error or "").lower()

    fresh = pygit2.Repository(conflicted.path)
    assert fresh.index.conflicts is not None


def test_resolving_an_unknown_path_fails_cleanly(conflicted):
    result = resolve_with(conflicted, "jamais.txt", Side.OURS)
    assert result.success is False


def test_binary_conflict_can_be_resolved(tmp_path):
    """Review Focus 3 : aucun choix ligne à ligne n'a de sens ici."""
    bare = tmp_path / "b.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], capture_output=True)
    work = tmp_path / "wb"
    subprocess.run(["git", "clone", "-q", str(bare), str(work)], capture_output=True)
    (work / "img.dat").write_bytes(bytes(range(64)))
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "base")
    run_git(work, "push", "-q", "origin", "HEAD")

    other = tmp_path / "ob"
    subprocess.run(["git", "clone", "-q", str(bare), str(other)], capture_output=True)
    (other / "img.dat").write_bytes(bytes(range(63, -1, -1)))
    run_git(other, "add", ".")
    run_git(other, "commit", "-q", "-m", "distant")
    run_git(other, "push", "-q")

    (work / "img.dat").write_bytes(bytes([7] * 64))
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "local")
    run_git(work, "fetch", "-q")

    repo = pygit2.Repository(str(work))
    repo.merge(repo.branches[repo.head.shorthand].upstream.target)
    assert repo.index.conflicts is not None

    conflict = list_conflicts(repo)[0]
    assert conflict.is_binary is True

    resolve_with(repo, "img.dat", Side.THEIRS)
    assert list_conflicts(pygit2.Repository(str(work))) == ()


def test_delete_modify_conflict_does_not_crash(tmp_path):
    """Review Focus 4 : un côté supprime, l'autre modifie.

    Une des trois versions de `index.conflicts` vaut alors `None`.
    """
    bare = tmp_path / "d.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], capture_output=True)
    work = tmp_path / "wd"
    subprocess.run(["git", "clone", "-q", str(bare), str(work)], capture_output=True)
    (work / "f.txt").write_text("contenu\n")
    (work / "garde.txt").write_text("garde\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "base")
    run_git(work, "push", "-q", "origin", "HEAD")

    other = tmp_path / "od"
    subprocess.run(["git", "clone", "-q", str(bare), str(other)], capture_output=True)
    run_git(other, "rm", "-q", "f.txt")
    run_git(other, "commit", "-q", "-m", "supprime")
    run_git(other, "push", "-q")

    (work / "f.txt").write_text("modifie localement\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "modifie")
    run_git(work, "fetch", "-q")

    repo = pygit2.Repository(str(work))
    repo.merge(repo.branches[repo.head.shorthand].upstream.target)

    files = list_conflicts(repo)
    assert files, "le conflit suppression/modification doit être listé"
    conflict = files[0]
    assert conflict.path == "f.txt"
    # Un des deux côtés n'existe pas — l'interface doit pouvoir le dire.
    assert conflict.has_ours != conflict.has_theirs


def test_no_conflicts_gives_an_empty_tuple(tmp_path):
    path = tmp_path / "propre"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "f.txt").write_text("a\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "base")
    assert list_conflicts(pygit2.Repository(str(path))) == ()


def test_conflicted_file_is_frozen(conflicted):
    import dataclasses

    conflict = list_conflicts(conflicted)[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        conflict.path = "autre.txt"
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/core/test_conflicts.py -v`
Expected: FAIL — module introuvable.

- [ ] **Step 3: Implémenter**

```python
# src/tortoisepy/core/conflicts.py
"""Lister et résoudre les conflits — §6 de la spec phase 8.

Résoudre, ici, c'est choisir un camp par fichier (D12) : ni éditeur de
fusion, ni choix ligne à ligne. Cela couvre la majorité des cas sans
ouvrir un chantier à soi seul.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum

import pygit2

from tortoisepy.core.results import OperationResult, failed, guarded, succeeded


class Side(Enum):
    OURS = "ours"
    THEIRS = "theirs"


@dataclass(frozen=True)
class ConflictedFile:
    path: str
    has_ours: bool
    has_theirs: bool
    is_binary: bool = False

    @property
    def is_delete_modify(self) -> bool:
        """Un côté a supprimé le fichier, l'autre l'a modifié.

        Choisir « le supprimé » revient à effacer le fichier ; l'interface
        doit le dire clairement plutôt que de proposer un contenu vide.
        """
        return self.has_ours != self.has_theirs


def list_conflicts(repo: pygit2.Repository) -> tuple[ConflictedFile, ...]:
    """Fichiers en conflit, triés par chemin."""
    conflicts = repo.index.conflicts
    if conflicts is None:
        return ()

    found = []
    for _, ours, theirs in conflicts:
        entry = ours or theirs
        if entry is None:
            continue
        found.append(
            ConflictedFile(
                path=entry.path,
                has_ours=ours is not None,
                has_theirs=theirs is not None,
                is_binary=_is_binary(repo, ours, theirs),
            )
        )
    return tuple(sorted(found, key=lambda c: c.path))


@guarded("Résolution", changed_on_error=True)
def resolve_with(
    repo: pygit2.Repository, path: str, side: Side
) -> OperationResult:
    """Retient un des deux camps pour ce fichier.

    Vérifié : retirer l'entrée de `index.conflicts`, ajouter l'`IndexEntry`
    du côté choisi, écrire l'index, puis récrire le fichier de travail.
    """
    conflicts = repo.index.conflicts
    if conflicts is None:
        return failed("Résolution", "no conflict in progress")

    try:
        _, ours, theirs = conflicts[path]
    except KeyError:
        return failed("Résolution", f"no conflict on {path}")

    kept = ours if side is Side.OURS else theirs
    index = repo.index
    del index.conflicts[path]

    full = os.path.join(repo.workdir or "", path)
    if kept is None:
        # Le camp retenu a supprimé le fichier : le retirer réellement.
        if path in index:
            index.remove(path)
        if os.path.lexists(full):
            os.remove(full)
    else:
        index.add(pygit2.IndexEntry(path, kept.id, kept.mode))
        os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
        with open(full, "wb") as handle:
            handle.write(repo.get(kept.id).data)

    index.write()
    return succeeded(f"Resolved {path} ({side.value})")


@guarded("Fusion", changed_on_error=True)
def conclude_merge(repo: pygit2.Repository) -> OperationResult:
    """Crée le commit de fusion une fois tout résolu.

    Refuse tant qu'il reste un conflit : le commit contiendrait des
    marqueurs `<<<<<<<` (règle de la phase 6).
    """
    remaining = list_conflicts(repo)
    if remaining:
        names = ", ".join(c.path for c in remaining)
        return failed(
            "Fusion", f"unresolved conflicts remain: {names}",
            repository_changed=False,
        )

    their_head = _merge_head(repo)
    if their_head is None:
        return failed(
            "Fusion", "no merge in progress", repository_changed=False
        )

    signature = _signature(repo)
    tree = repo.index.write_tree()
    repo.create_commit(
        "HEAD", signature, signature, "Merge remote-tracking branch",
        tree, [repo.head.target, their_head],
    )
    # Sans ce nettoyage, `MERGE_HEAD` traîne et l'interface croit la
    # fusion toujours en cours (leçon de la phase 7).
    repo.state_cleanup()
    return succeeded("Merge completed")


def _merge_head(repo: pygit2.Repository):
    """Tête de la branche fusionnée, lue dans `MERGE_HEAD`."""
    try:
        with open(os.path.join(repo.path, "MERGE_HEAD")) as handle:
            return pygit2.Oid(hex=handle.read().strip())
    except (OSError, ValueError):
        return None


def _is_binary(repo: pygit2.Repository, ours, theirs) -> bool:
    """Un contenu binaire ne se fusionne pas ligne à ligne."""
    for entry in (ours, theirs):
        if entry is None:
            continue
        try:
            if repo.get(entry.id).is_binary:
                return True
        except (KeyError, AttributeError):
            continue
    return False


def _signature(repo: pygit2.Repository) -> pygit2.Signature:
    try:
        return repo.default_signature
    except (KeyError, ValueError):
        return pygit2.Signature("tortoisePy", "tortoisepy@localhost")
```

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/core/test_conflicts.py tests/test_architecture.py -v`
Expected: PASS, 11 + 5 tests.

- [ ] **Step 5: Signaler les fichiers prêts** — ne commite pas.

---

### Task 3: Le bouton Pull

**Files:**
- Modify: `src/tortoisepy/ui/main_window.py`
- Modify: `src/tortoisepy/ui/context_menu.py`
- Modify: `src/tortoisepy/ui/actions.py`
- Modify: `src/tortoisepy/ui/dialogs.py`
- Test: `tests/ui/test_main_window.py`, `tests/ui/test_context_menu.py`

**Interfaces:**
- Consumes: `analyse_pull`, `pull_fast_forward`, `pull_merge`, `pull_rebase`
  (tâche 1), `fetch_remote`, `FetchWorker`, `BackgroundTask`
- Produces: `MainWindow.pull_action`, `_start_pull()`, `_on_pull_finished()`,
  `ask_pull_strategy(parent, state)`

**Suivre le patron de Push**, établi en phase 7 : même structure de bouton,
même interception dans `_run_action`, même exécution en arrière-plan.

**Deux différences avec Push**, voulues (§4) :
- **Pull n'est pas confirmé** : son effet ne sort pas de la machine et reste
  annulable. Confirmer chaque récupération serait du bruit.
- **Pull commence par un fetch**, sinon l'analyse porte sur une ref périmée.

- [ ] **Step 1: Écrire les tests**

```python
# à ajouter dans tests/ui/test_main_window.py


def test_pull_action_exists(window):
    assert window.pull_action is not None
    assert window.pull_action.text() == "Pull"


def test_pull_is_disabled_without_a_remote(window):
    window._update_pull_action()
    assert window.pull_action.isEnabled() is False


def test_disabled_pull_explains_why(window):
    window._update_pull_action()
    assert window.pull_action.toolTip()


def test_pull_is_enabled_when_something_is_incoming(window, monkeypatch):
    from tortoisepy.core.pull import PullKind, PullState
    from tortoisepy.ui import main_window as module

    monkeypatch.setattr(
        module,
        "analyse_pull",
        lambda repo: PullState(
            PullKind.FAST_FORWARD, branch="main",
            remote_name="origin", incoming=3,
        ),
    )
    window._update_pull_action()
    assert window.pull_action.isEnabled() is True


def test_pull_refuses_when_a_task_is_running(window):
    class Busy:
        def is_running(self):
            return True

    window._task = Busy()
    window._start_pull()
    assert "running" in window.statusBar().currentMessage().lower()


def test_pull_reports_its_result(window):
    from tortoisepy.core.results import succeeded

    window._on_pull_finished(succeeded("Pulled 3 commits from origin"))
    assert "Pulled 3 commits" in window.statusBar().currentMessage()


def test_pull_conflict_opens_the_resolution_window(window, monkeypatch):
    """Un conflit n'est pas une impasse : la fenêtre doit s'ouvrir."""
    from tortoisepy.core.results import failed
    from tortoisepy.ui import main_window as module

    ouvertes = []
    monkeypatch.setattr(
        module.MainWindow, "open_conflict_window",
        lambda self: ouvertes.append(True),
    )
    monkeypatch.setattr(module, "show_error", lambda *a, **k: None)

    window._on_pull_finished(failed("Pull", "conflicts in: f.txt"))
    assert ouvertes, "la fenêtre de résolution doit s'ouvrir"
```

```python
# à ajouter dans tests/ui/test_context_menu.py


def test_pull_is_in_the_menu():
    from tortoisepy.core.model import DisplayNode, NodeKind, Ref, RefType
    from tortoisepy.core.state import RepositoryState
    from tortoisepy.ui.context_menu import build_menu_model

    node = DisplayNode(
        oid="a" * 40,
        kind=NodeKind.REF,
        refs=(Ref("main", RefType.LOCAL_BRANCH, "a" * 40),),
    )
    state = RepositoryState(
        head_oid="a" * 40, head_branch="main", detached=False,
        has_unstaged_changes=False, has_staged_changes=False,
        has_conflicts=False, operation_in_progress=None, conflicted_paths=(),
    )

    def actions(entries):
        for entry in entries:
            if entry.action:
                yield entry.action
            yield from actions(entry.children)

    assert "pull_branch" in set(actions(build_menu_model((node,), state)))
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/ui/test_main_window.py tests/ui/test_context_menu.py -q -k pull`
Expected: FAIL — `pull_action` n'existe pas.

- [ ] **Step 3: Le choix merge/rebase (`dialogs.py`)**

```python
def ask_pull_strategy(parent, state) -> str | None:
    """Merge ou rebase ? `None` si l'utilisateur annule (§5).

    Posée seulement quand les deux côtés ont avancé. Le rebase est le seul
    des deux à réécrire des commits déjà faits : on le dit, plutôt que de
    laisser l'utilisateur le découvrir après coup.
    """
    choices = [
        "Merge — keep both histories, add a merge commit",
        "Rebase — replay your commits on top (rewrites them)",
    ]
    choice, accepted = QInputDialog.getItem(
        parent,
        "Pull",
        (
            f"{state.branch} and {state.remote_name}/{state.branch} have "
            f"both moved on\n"
            f"({state.incoming} incoming, {state.outgoing} local).\n\n"
            "How should they be combined?"
        ),
        choices,
        0,
        False,
    )
    if not accepted:
        return None
    return "merge" if choice.startswith("Merge") else "rebase"
```

- [ ] **Step 4: Menu et action**

Dans `context_menu.py`, à côté de « Push » :

```python
    entries.append(
        MenuEntry(
            "Pull",
            "pull_branch",
            # Comme Push : seulement sur la branche courante ; récupérer
            # dans une autre demanderait un checkout, qui existe déjà.
            enabled=is_current,
        )
    )
```

Dans `actions.py`, sur le modèle de `_push_branch` :

```python
def _pull_branch(ctx: ActionContext) -> OperationResult | None:
    """La fenêtre principale s'en charge : le pull part en arrière-plan."""
    return None
```

et l'enregistrer : `"pull_branch": _pull_branch,`

- [ ] **Step 5: Bouton et exécution (`main_window.py`)**

Imports à ajouter :

```python
from tortoisepy.core.pull import (
    PullKind,
    analyse_pull,
    pull_fast_forward,
    pull_merge,
    pull_rebase,
)
from tortoisepy.core.results import failed, succeeded
from tortoisepy.ui.dialogs import ask_pull_strategy
```

**Vérifié :** `main_window.py` n'importe aujourd'hui **ni `succeeded` ni
`failed`**. Sans cet ajout, `_pull_after_fetch` lèverait un `NameError` au
premier pull. `ask_pull_strategy` s'ajoute à l'import existant de
`ui.dialogs`, qui liste déjà `ConfirmationRequest`, `confirm` et
`show_error`.

Dans `specs` de `_build_actions` :

```python
            ("Pull", QKeySequence("Ctrl+L"), self._start_pull),
```

en gardant la référence comme pour Push :

```python
            if label == "Pull":
                self.pull_action = action
```

Intercepter dans `_run_action`, à côté de `push_branch` :

```python
        if action == "pull_branch":
            self._start_pull()
            return
```

Puis les méthodes :

```python
    def _update_pull_action(self) -> None:
        """Grise le bouton quand il n'y a rien à récupérer."""
        state = analyse_pull(self.repository)
        can_pull = state.kind in (PullKind.FAST_FORWARD, PullKind.DIVERGED)
        self.pull_action.setEnabled(can_pull)

        if can_pull:
            self.pull_action.setToolTip(
                f"Pull {state.incoming} commit(s) from {state.remote_name}"
            )
        elif state.kind is PullKind.UP_TO_DATE:
            self.pull_action.setToolTip("Already up to date")
        else:
            self.pull_action.setToolTip(state.reason or "nothing to pull")

    def _start_pull(self) -> None:
        """Récupère en arrière-plan.

        Un fetch d'abord, **toujours** : sans lui l'analyse porterait sur
        une ref distante périmée et conclurait « à jour » à tort (§3).
        Pull n'est pas confirmé : son effet reste annulable (§4).
        """
        if self._task is not None and self._task.is_running():
            self.statusBar().showMessage("A background task is running", 3000)
            return

        from tortoisepy.core import operations

        self.progress.setRange(0, 0)
        self.progress.setFormat("Pulling…")
        self.progress.show()
        self.statusBar().showMessage("Pulling…")

        worker = FetchWorker(
            lambda on_progress: self._pull_after_fetch(on_progress)
        )
        self._task = BackgroundTask(worker, self)
        self._task.progress.connect(self._on_fetch_progress)
        self._task.finished.connect(self._on_pull_finished)
        self._task.start()

    def _pull_after_fetch(self, on_progress):
        """Fetch, puis applique la stratégie qui convient.

        Tourne dans le fil de fond. La stratégie a été choisie **avant**,
        dans le fil d'interface : Qt interdit d'ouvrir un dialogue ici.
        """
        from tortoisepy.core import operations

        fetched = operations.fetch_remote(
            self.repository, on_progress=on_progress
        )
        if not fetched.success:
            return fetched

        state = analyse_pull(self.repository)
        if state.kind is PullKind.UP_TO_DATE:
            return succeeded("Already up to date", repository_changed=False)
        if state.kind is PullKind.FAST_FORWARD:
            return pull_fast_forward(self.repository)
        if state.kind is PullKind.UNAVAILABLE:
            return failed("Pull", state.reason)

        if self._pull_strategy == "rebase":
            return pull_rebase(self.repository)
        return pull_merge(self.repository)

    def _on_pull_finished(self, result) -> None:
        """Un conflit ouvre la fenêtre de résolution, jamais une impasse."""
        self.progress.hide()
        self.refresh()          # d'abord : `refresh` réécrit la barre d'état
        self.statusBar().showMessage(result.summary or "Pull finished", 15000)

        if result.success:
            return

        if "conflict" in (result.git_error or "").lower():
            self.open_conflict_window()
            return

        show_error(self, result)
```

**Le choix de stratégie se fait avant de lancer le fil de fond.** Ajouter au
début de `_start_pull`, après la garde « tâche en cours » :

```python
        # La divergence demande une question ; Qt interdit d'ouvrir un
        # dialogue depuis le fil de fond, donc on tranche maintenant.
        self._pull_strategy = "merge"
        preview = analyse_pull(self.repository)
        if preview.kind is PullKind.DIVERGED:
            chosen = ask_pull_strategy(self, preview)
            if chosen is None:
                return
            self._pull_strategy = chosen
```

Et appeler `self._update_pull_action()` à la fin de `refresh()`, à côté de
`_update_push_action()` — **sans supprimer ce dernier.**

- [ ] **Step 6: Vérifier le succès**

Run: `.venv/bin/pytest tests/ui/ -q`
Expected: PASS.

- [ ] **Step 7: Signaler les fichiers prêts** — ne commite pas.

---

### Task 4: La fenêtre de résolution

**Files:**
- Create: `src/tortoisepy/ui/conflict_window.py`
- Modify: `src/tortoisepy/ui/main_window.py`
- Test: `tests/ui/test_conflict_window.py`

**Interfaces:**
- Consumes: `list_conflicts`, `resolve_with`, `conclude_merge`, `Side`
  (tâche 2), `abort_operation` (phase 5), `DiffView` (phase 6)
- Produces: `ConflictWindow`, `MainWindow.open_conflict_window()`

**C'est la tâche qui garantit qu'on ne reste jamais coincé** : la fenêtre
expose toujours « Abort », qui restaure l'état d'avant.

- [ ] **Step 1: Écrire les tests**

```python
# tests/ui/test_conflict_window.py
import os
import subprocess

import pygit2
import pytest

from tortoisepy.ui.conflict_window import ConflictWindow


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
def conflicted(tmp_path):
    bare = tmp_path / "s.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], capture_output=True)
    work = tmp_path / "w"
    subprocess.run(["git", "clone", "-q", str(bare), str(work)], capture_output=True)
    (work / "f.txt").write_text("ligne1\nligne2\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "base")
    run_git(work, "push", "-q", "origin", "HEAD")

    other = tmp_path / "o"
    subprocess.run(["git", "clone", "-q", str(bare), str(other)], capture_output=True)
    (other / "f.txt").write_text("ligne1\nDISTANT\n")
    run_git(other, "add", ".")
    run_git(other, "commit", "-q", "-m", "distant")
    run_git(other, "push", "-q")

    (work / "f.txt").write_text("ligne1\nLOCAL\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "local")
    run_git(work, "fetch", "-q")

    repo = pygit2.Repository(str(work))
    repo.merge(repo.branches[repo.head.shorthand].upstream.target)
    return repo


@pytest.fixture
def window(qtbot, conflicted):
    w = ConflictWindow(conflicted)
    qtbot.addWidget(w)
    w.show()
    return w


def test_lists_the_conflicts(window):
    assert window.file_count() == 1


def test_resolve_is_disabled_while_a_conflict_remains(window):
    assert window.resolve_button.isEnabled() is False


def test_keeping_mine_resolves_the_file(window, conflicted):
    window.select_file("f.txt")
    window.keep_mine()
    assert open(os.path.join(conflicted.workdir, "f.txt")).read() == (
        "ligne1\nLOCAL\n"
    )


def test_taking_theirs_resolves_the_file(window, conflicted):
    window.select_file("f.txt")
    window.take_theirs()
    assert open(os.path.join(conflicted.workdir, "f.txt")).read() == (
        "ligne1\nDISTANT\n"
    )


def test_resolve_becomes_available_once_everything_is_settled(window):
    window.select_file("f.txt")
    window.take_theirs()
    assert window.resolve_button.isEnabled() is True


def test_resolving_creates_the_merge_commit(window, conflicted):
    window.select_file("f.txt")
    window.take_theirs()
    window.resolve()

    fresh = pygit2.Repository(conflicted.path)
    assert len(fresh.get(fresh.head.target).parents) == 2
    assert fresh.state() == pygit2.enums.RepositoryState.NONE


def test_abort_restores_the_previous_state(window, conflicted):
    """Review Focus 5 : on ne doit jamais rester coincé."""
    before = str(conflicted.head.target)
    window.abort()

    fresh = pygit2.Repository(conflicted.path)
    assert fresh.index.conflicts is None
    assert str(fresh.head.target) == before
    assert fresh.state() == pygit2.enums.RepositoryState.NONE
    assert open(os.path.join(conflicted.workdir, "f.txt")).read() == (
        "ligne1\nLOCAL\n"
    )


def test_window_closes_after_resolving(window):
    window.select_file("f.txt")
    window.take_theirs()
    window.resolve()
    assert window.isHidden() is True


def test_window_closes_after_aborting(window):
    window.abort()
    assert window.isHidden() is True


def test_selecting_a_file_shows_both_versions(window):
    window.select_file("f.txt")
    text = window.diff_view.text()
    assert "LOCAL" in text
    assert "DISTANT" in text


def test_the_two_sides_are_coloured_differently(window):
    """Voir sa version en vert et la distante en rouge aide à choisir."""
    window.select_file("f.txt")
    lines = window.diff_view.text().splitlines()
    notre = next(l for l in lines if "LOCAL" in l and "<<<" not in l)
    leur = next(l for l in lines if "DISTANT" in l and ">>>" not in l)
    assert notre.startswith("+")
    assert leur.startswith("-")
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/ui/test_conflict_window.py -v`
Expected: FAIL — module introuvable.

- [ ] **Step 3: Implémenter**

```python
# src/tortoisepy/ui/conflict_window.py
"""Résoudre les conflits d'une fusion — §6 de la spec phase 8.

Une liste de fichiers, un choix par fichier, et **toujours** un bouton
« Abort » : c'est lui qui rend le reste acceptable, puisqu'il garantit
qu'on ne peut pas rester coincé.
"""

from __future__ import annotations

import pygit2
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tortoisepy.core import operations
from tortoisepy.core.conflicts import (
    Side,
    conclude_merge,
    list_conflicts,
    resolve_with,
)
from tortoisepy.ui.diff_view import DiffView
from tortoisepy.ui.dialogs import show_error

PATH_ROLE = Qt.ItemDataRole.UserRole


class ConflictWindow(QMainWindow):
    """Choisir un camp, fichier par fichier."""

    finished = Signal(object)
    """`OperationResult` — la fenêtre principale rafraîchit le graphe."""

    def __init__(self, repository: pygit2.Repository, parent=None):
        super().__init__(parent)
        self.repository = repository

        self._files = QTreeWidget()
        self._files.setColumnCount(2)
        self._files.setHeaderLabels(("Fichier", "État"))
        self._files.setRootIsDecorated(False)
        self._files.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._files.itemSelectionChanged.connect(self._on_file_selected)

        self.diff_view = DiffView()

        self.mine_button = QPushButton("Keep mine")
        self.mine_button.clicked.connect(self.keep_mine)
        self.theirs_button = QPushButton("Take theirs")
        self.theirs_button.clicked.connect(self.take_theirs)
        self.resolve_button = QPushButton("Resolve")
        self.resolve_button.clicked.connect(self.resolve)
        self.abort_button = QPushButton("Abort")
        self.abort_button.clicked.connect(self.abort)

        buttons = QHBoxLayout()
        buttons.addWidget(self.mine_button)
        buttons.addWidget(self.theirs_button)
        buttons.addStretch(1)
        buttons.addWidget(self.abort_button)
        buttons.addWidget(self.resolve_button)

        bottom = QWidget()
        layout = QVBoxLayout(bottom)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(buttons)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self._files)
        splitter.addWidget(self.diff_view)
        splitter.addWidget(bottom)
        splitter.setStretchFactor(1, 3)

        self.setCentralWidget(splitter)
        self.setWindowTitle("Resolve conflicts")
        self.resize(900, 700)

        self.refresh()

    def refresh(self) -> None:
        self._files.clear()
        self.diff_view.clear()

        for conflict in list_conflicts(self.repository):
            if conflict.is_delete_modify:
                etat = "supprimé d'un côté"
            elif conflict.is_binary:
                etat = "binaire"
            else:
                etat = "modifié des deux côtés"

            item = QTreeWidgetItem([conflict.path, etat])
            item.setData(0, PATH_ROLE, conflict.path)
            self._files.addTopLevelItem(item)

        if self._files.topLevelItemCount():
            self._files.setCurrentItem(self._files.topLevelItem(0))

        self._update_buttons()

    def file_count(self) -> int:
        return self._files.topLevelItemCount()

    def select_file(self, path: str) -> None:
        for index in range(self._files.topLevelItemCount()):
            item = self._files.topLevelItem(index)
            if item.data(0, PATH_ROLE) == path:
                self._files.setCurrentItem(item)
                return

    def keep_mine(self) -> None:
        self._resolve_current(Side.OURS)

    def take_theirs(self) -> None:
        self._resolve_current(Side.THEIRS)

    def resolve(self) -> None:
        """Conclut la fusion une fois tout résolu."""
        result = conclude_merge(self.repository)
        self.finished.emit(result)
        if not result.success:
            show_error(self, result)
            self.refresh()
            return
        self.close()

    def abort(self) -> None:
        """Rend la main : restaure l'état d'avant la fusion.

        La sortie de secours, toujours disponible — c'est elle qui garantit
        qu'un conflit n'est jamais une impasse.
        """
        result = operations.abort_operation(self.repository)
        self.finished.emit(result)
        if not result.success:
            show_error(self, result)
            return
        self.close()

    def _resolve_current(self, side: Side) -> None:
        item = self._files.currentItem()
        if item is None:
            return
        result = resolve_with(self.repository, item.data(0, PATH_ROLE), side)
        if not result.success:
            show_error(self, result)
        self.refresh()

    def _on_file_selected(self) -> None:
        item = self._files.currentItem()
        if item is None:
            self.diff_view.clear()
            return
        self.diff_view.show_diff(
            _conflict_preview(self.repository, item.data(0, PATH_ROLE))
        )

    def _update_buttons(self) -> None:
        remaining = self.file_count()
        # Conclure avec un conflit restant produirait un commit contenant
        # des marqueurs `<<<<<<<` (règle de la phase 6).
        self.resolve_button.setEnabled(remaining == 0)
        self.mine_button.setEnabled(remaining > 0)
        self.theirs_button.setEnabled(remaining > 0)


def _conflict_preview(repo: pygit2.Repository, path: str):
    """Le fichier tel qu'il est, marqueurs compris.

    Montrer le fichier de travail plutôt qu'un diff reconstruit : c'est ce
    que l'utilisateur verra dans son éditeur, donc ce qu'il reconnaît.
    """
    import os

    from tortoisepy.core.changes import DiffHunk, DiffLine, FileDiff

    full = os.path.join(repo.workdir or "", path)
    try:
        with open(full, encoding="utf-8", errors="replace") as handle:
            contenu = handle.read().splitlines()
    except OSError:
        return FileDiff(path=path)

    return FileDiff(
        path=path,
        hunks=(DiffHunk(header=f"@@ {path} @@", lines=_colour(contenu)),),
    )


def _colour(lines: list[str]) -> tuple:
    """Marque le bloc local comme un ajout et le bloc distant comme un retrait.

    `DiffView` colore déjà `+` en vert et `-` en rouge : en réutilisant ces
    origines, l'utilisateur voit d'un coup d'œil quelle moitié vient de chez
    lui. Les lignes de marqueur elles-mêmes restent neutres.
    """
    from tortoisepy.core.changes import DiffLine

    coloured = []
    side = " "
    for line in lines:
        if line.startswith("<<<<<<<"):
            side = "+"          # début de NOTRE version
            coloured.append(DiffLine(origin=" ", content=line))
            continue
        if line.startswith("======="):
            side = "-"          # bascule vers LEUR version
            coloured.append(DiffLine(origin=" ", content=line))
            continue
        if line.startswith(">>>>>>>"):
            side = " "
            coloured.append(DiffLine(origin=" ", content=line))
            continue
        coloured.append(DiffLine(origin=side, content=line))
    return tuple(coloured)
```

- [ ] **Step 4: Brancher dans `main_window.py`**

```python
from tortoisepy.ui.conflict_window import ConflictWindow
```

Dans `__init__` :

```python
        self.conflict_window: ConflictWindow | None = None
```

Puis :

```python
    def open_conflict_window(self) -> None:
        """Ouvre la résolution de conflits, ou ramène celle déjà ouverte.

        Une seule à la fois : deux vues d'un même index se contrediraient.
        """
        if (
            self.conflict_window is not None
            and not self.conflict_window.isHidden()
        ):
            self.conflict_window.raise_()
            self.conflict_window.activateWindow()
            return

        self.conflict_window = ConflictWindow(self.repository, self)
        self.conflict_window.finished.connect(self._on_conflicts_finished)
        self.conflict_window.show()

    def _on_conflicts_finished(self, result) -> None:
        if result.repository_changed:
            self.refresh()
        self.statusBar().showMessage(
            result.summary or (result.git_error or ""), 15000
        )
```

- [ ] **Step 5: Vérifier le succès**

Run: `.venv/bin/pytest tests/ui/ -q`
Expected: PASS.

- [ ] **Step 6: Vérifier la lecture seule**

Run: `.venv/bin/pytest tests/test_read_only.py -v`
Expected: PASS, 7 tests.

- [ ] **Step 7: Suite complète**

Run: `.venv/bin/pytest -q`
Expected: 700 + ~45 tests, tous verts. **Attendre la fin** (environ 5 min).

- [ ] **Step 8: Signaler les fichiers prêts** — ne commite pas. Donner le
décompte exact.

---

## Fin de phase 8

Le cycle complet est là : récupérer, résoudre, commiter, pousser — sans quitter
le graphe, et sans pouvoir rester coincé.

**Hors périmètre**, conformément à la spec §10 :

- **Éditeur de fusion à trois panneaux** — choisir un camp couvre la majorité
  des cas (D12).
- **Résolution ligne à ligne** — même raison.
- **Pull sur une autre branche que la courante** — c'est un checkout d'abord.
- **`pull --force`, `rebase --onto`** — jamais.
