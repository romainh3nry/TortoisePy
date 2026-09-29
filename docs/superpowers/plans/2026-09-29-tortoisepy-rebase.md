# tortoisePy — Plan d'implémentation, phase 9 : rebaser sur une branche choisie

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebaser la branche courante sur une branche choisie, avec
autocomplétion, et résoudre les conflits sans jamais rester coincé.

**Architecture:** `core/rebase.py` démarre, poursuit et abandonne un rebase,
sans Qt. `ui/dialogs.py` gagne un champ avec autocomplétion.
`ui/conflict_window.py` apprend à servir les deux opérations : ses libellés et
ses boutons changent selon qu'il s'agit d'un merge ou d'un rebase.

**Tech Stack:** Python 3.13, pygit2 1.20, PySide6 6.11, pytest-qt.

**Spec:** `docs/superpowers/specs/2026-09-29-tortoisepy-rebase-design.md`

**Prérequis:** phases 1 à 8 terminées, 783 tests passent.

## Global Constraints

- **Aucune commande `git` sur le dépôt tortoisePy.** Les étapes « commit » du
  modèle de plan sont remplacées par « signaler les fichiers prêts ». Les
  fixtures peuvent invoquer `git` via `subprocess` sur des dépôts temporaires.
- **On ne doit jamais rester coincé.** Tout chemin menant à un conflit expose
  un « Abort » qui restaure l'état d'avant. Pour un rebase, c'est
  **`Rebase.abort()`**, jamais `abort_operation` — ce dernier fait
  `state_cleanup()` + `reset(HARD)`, ce qui sur une HEAD détachée la remet sur
  elle-même sans rattacher la branche (défaut trouvé en phase 8).
- **Ne jamais commiter un conflit non résolu** : le commit contiendrait des
  marqueurs `<<<<<<<`.
- **`core/` n'importe jamais PySide6.** Vérifié par `tests/test_architecture.py`.
- **`tests/test_read_only.py` doit rester vert** (7 tests) : lister les
  branches n'écrit rien.
- **Le rendu visuel validé ne doit pas être dégradé** : aucune tâche ne touche
  `layout/`, `ui/graph_items.py`, ni une couleur existante de `theme.py`.
- **Libellés d'interface en anglais**, commentaires et docstrings **en français**.
- **Jamais de `rebase --onto` ni de rebase interactif.**
- **API vérifiées le 2026-09-29** sur pygit2 1.20.1 :
  - `repo.rebase_init(branch=…, upstream=None, onto=…)` démarre le rebase.
    `init_rebase` **n'existe pas**.
  - **`repo.rebase_open()` reprend un rebase interrompu, y compris depuis un
    autre processus** — c'est ce qui rend la fenêtre de conflits possible.
    Il expose `onto_id` et `orig_head_name`.
  - `Rebase.commit(committer=…)` — et `Rebase.finish(signature)` : les deux
    méthodes n'ont **pas** le même nom de paramètre.
  - `Rebase.commit()` rend **`None`** quand le commit devient vide : ce n'est
    pas une erreur, c'est le patch déjà appliqué en amont.
  - `Rebase.abort()` depuis un autre processus restaure tout : état `NONE`,
    HEAD rattachée, commit d'origine intact. **Vérifié.**
  - `repo.branches.local` et `repo.branches.remote` listent les cibles.
  - `QCompleter` avec `MatchContains` : saisir « main » propose `main` **et**
    `origin/main`.

## Review Focus

Cas que la spec implique et qu'aucune tâche n'exercerait sans y penser.

1. **`ours` et `theirs` sont INVERSÉS en rebase.** Vérifié : rebaser `feature`
   sur `main` donne `ours = MAIN` (la cible) et `theirs = FEATURE` (le commit
   rejoué) — l'inverse du merge. Des libellés « Keep mine / Take theirs » non
   adaptés feraient **perdre son travail à qui croit le garder**. *(tâches 1 et 3)*
2. **Commit devenu vide** — `Rebase.commit()` rend `None`. Le traiter comme une
   erreur bloquerait un rebase parfaitement valide. *(tâche 1)*
3. **Fermer la fenêtre pendant un conflit** — le rebase reste en cours, comme
   au terminal. L'application doit savoir le reprendre, pas laisser un état
   mort. *(tâches 1 et 4)*
4. **Cible inconnue ou identique à la branche courante** — refuser avant de
   toucher au dépôt, plutôt que de laisser libgit2 lever un message obscur.
   *(tâches 1 et 2)*
5. **Arbre de travail sale** — un rebase écraserait le travail en cours. Doit
   refuser d'abord. *(tâche 1)*

---

### Task 1: Le moteur de rebase

**Files:**
- Create: `src/tortoisepy/core/rebase.py`
- Test: `tests/core/test_rebase.py`

**Interfaces:**
- Consumes: `OperationResult`, `guarded`, `succeeded`, `failed`,
  `list_conflicts` (phase 8)
- Produces: `RebaseState`, `rebase_targets(repo)`, `rebase_state(repo)`,
  `start_rebase(repo, onto)`, `continue_rebase(repo)`, `abort_rebase(repo)`

- [ ] **Step 1: Écrire les tests**

```python
# tests/core/test_rebase.py
import os
import subprocess

import pygit2
import pytest

from tortoisepy.core.conflicts import Side, list_conflicts, resolve_with
from tortoisepy.core.rebase import (
    abort_rebase,
    continue_rebase,
    rebase_state,
    rebase_targets,
    start_rebase,
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


def diverged(tmp_path, meme_fichier=True):
    """`feature` et `main` ont chacune un commit ; conflit si même fichier."""
    path = tmp_path / "depot"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "f.txt").write_text("a\nb\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "base")

    run_git(path, "checkout", "-q", "-b", "feature")
    cible = "f.txt" if meme_fichier else "cote-feature.txt"
    (path / cible).write_text("a\nFEATURE\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "cote feature")

    run_git(path, "checkout", "-q", "main")
    autre = "f.txt" if meme_fichier else "cote-main.txt"
    (path / autre).write_text("a\nMAIN\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "cote main")

    run_git(path, "checkout", "-q", "feature")
    return path


def test_lists_local_and_remote_targets(tmp_path):
    """D14 : rebaser sur une distante sans la sortir localement d'abord."""
    bare = tmp_path / "s.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], capture_output=True)
    work = tmp_path / "w"
    subprocess.run(["git", "clone", "-q", str(bare), str(work)], capture_output=True)
    (work / "f.txt").write_text("a\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "base")
    run_git(work, "push", "-q", "origin", "HEAD")
    run_git(work, "branch", "develop")

    cibles = rebase_targets(pygit2.Repository(str(work)))
    assert "develop" in cibles
    assert "origin/main" in cibles


def test_the_current_branch_is_not_a_target(tmp_path):
    """Se rebaser sur soi-même n'a pas de sens."""
    path = diverged(tmp_path)
    assert "feature" not in rebase_targets(pygit2.Repository(str(path)))


def test_a_clean_rebase_replays_the_commit(tmp_path):
    path = diverged(tmp_path, meme_fichier=False)
    repo = pygit2.Repository(str(path))

    result = start_rebase(repo, "main")
    assert result.success is True, result.git_error

    fresh = pygit2.Repository(str(path))
    assert fresh.state() == pygit2.enums.RepositoryState.NONE
    assert fresh.head_is_detached is False
    assert fresh.head.shorthand == "feature"

    messages = [c.message.strip() for c in fresh.walk(fresh.head.target)]
    assert "cote feature" in messages
    assert "cote main" in messages


def test_a_conflict_is_reported_not_rolled_back(tmp_path):
    """D13 : le rebase reste en cours, pour être résolu (phase 8 l'annulait)."""
    path = diverged(tmp_path)
    repo = pygit2.Repository(str(path))

    result = start_rebase(repo, "main")
    assert result.success is False
    assert "conflict" in (result.git_error or "").lower()

    fresh = pygit2.Repository(str(path))
    assert fresh.state() != pygit2.enums.RepositoryState.NONE
    assert fresh.index.conflicts is not None


def test_ours_is_the_target_and_theirs_is_my_commit(tmp_path):
    """Review Focus 1 : l'inversion qui ferait perdre son travail.

    En rebase, `ours` est la branche CIBLE et `theirs` le commit rejoué —
    l'inverse du merge. Vérifié sur pygit2 1.20.
    """
    path = diverged(tmp_path)
    repo = pygit2.Repository(str(path))
    start_rebase(repo, "main")

    _, ours, theirs = repo.index.conflicts["f.txt"]
    assert b"MAIN" in repo.get(ours.id).data
    assert b"FEATURE" in repo.get(theirs.id).data

    etat = rebase_state(repo)
    assert etat.in_progress is True
    # L'interface doit pouvoir nommer les deux camps sans se tromper.
    assert etat.onto_label == "main"


def test_keeping_my_commit_keeps_the_replayed_version(tmp_path):
    """Le corollaire : « garder mon commit » retient bien THEIRS."""
    path = diverged(tmp_path)
    repo = pygit2.Repository(str(path))
    start_rebase(repo, "main")

    resolve_with(repo, "f.txt", Side.THEIRS)
    assert "FEATURE" in (path / "f.txt").read_text()


def test_continue_finishes_the_rebase(tmp_path):
    path = diverged(tmp_path)
    repo = pygit2.Repository(str(path))
    start_rebase(repo, "main")
    resolve_with(repo, "f.txt", Side.THEIRS)

    result = continue_rebase(pygit2.Repository(str(path)))
    assert result.success is True, result.git_error

    fresh = pygit2.Repository(str(path))
    assert fresh.state() == pygit2.enums.RepositoryState.NONE
    assert fresh.head_is_detached is False
    assert "FEATURE" in (path / "f.txt").read_text()


def test_continue_refuses_while_a_conflict_remains(tmp_path):
    """Poursuivre sans résoudre commiterait des marqueurs `<<<<<<<`."""
    path = diverged(tmp_path)
    repo = pygit2.Repository(str(path))
    start_rebase(repo, "main")

    result = continue_rebase(pygit2.Repository(str(path)))
    assert result.success is False
    assert "conflict" in (result.git_error or "").lower()


def test_an_emptied_commit_is_skipped(tmp_path):
    """Review Focus 2 : `Rebase.commit()` rend `None`, ce n'est pas une erreur.

    Les deux branches apportent le même contenu : le commit rejoué
    n'ajoute plus rien, comme le fait `git rebase`.
    """
    path = tmp_path / "vide"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "f.txt").write_text("a\nb\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "base")

    run_git(path, "checkout", "-q", "-b", "feature")
    (path / "f.txt").write_text("a\nPAREIL\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "cote feature")

    run_git(path, "checkout", "-q", "main")
    (path / "f.txt").write_text("a\nPAREIL\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "meme contenu")
    run_git(path, "checkout", "-q", "feature")

    result = start_rebase(pygit2.Repository(str(path)), "main")
    assert result.success is True, result.git_error

    fresh = pygit2.Repository(str(path))
    assert fresh.state() == pygit2.enums.RepositoryState.NONE


def test_abort_restores_everything(tmp_path):
    """La garantie qui rend D13 acceptable : on ne reste jamais coincé."""
    path = diverged(tmp_path)
    repo = pygit2.Repository(str(path))
    avant = str(repo.head.target)

    start_rebase(repo, "main")
    result = abort_rebase(pygit2.Repository(str(path)))
    assert result.success is True, result.git_error

    fresh = pygit2.Repository(str(path))
    assert fresh.state() == pygit2.enums.RepositoryState.NONE
    assert fresh.head_is_detached is False
    assert str(fresh.head.target) == avant
    assert fresh.head.shorthand == "feature"
    assert "FEATURE" in (path / "f.txt").read_text()


def test_a_rebase_survives_a_new_process(tmp_path):
    """Review Focus 3 : la fenêtre de conflits vit dans un autre contexte."""
    path = diverged(tmp_path)
    start_rebase(pygit2.Repository(str(path)), "main")

    # Dépôt rechargé : c'est ce que fait l'interface entre deux gestes.
    etat = rebase_state(pygit2.Repository(str(path)))
    assert etat.in_progress is True
    assert etat.onto_label == "main"
    assert etat.branch == "feature"


def test_an_unknown_target_is_refused(tmp_path):
    """Review Focus 4 : refuser avant de toucher au dépôt."""
    path = diverged(tmp_path)
    repo = pygit2.Repository(str(path))

    result = start_rebase(repo, "n-existe-pas")
    assert result.success is False
    assert "n-existe-pas" in (result.git_error or "")
    assert pygit2.Repository(str(path)).state() == (
        pygit2.enums.RepositoryState.NONE
    )


def test_rebasing_onto_itself_is_refused(tmp_path):
    path = diverged(tmp_path)
    result = start_rebase(pygit2.Repository(str(path)), "feature")
    assert result.success is False


def test_a_dirty_tree_is_refused(tmp_path):
    """Review Focus 5 : un rebase écraserait le travail en cours."""
    path = diverged(tmp_path, meme_fichier=False)
    (path / "f.txt").write_text("MON TRAVAIL EN COURS\n")

    result = start_rebase(pygit2.Repository(str(path)), "main")
    assert result.success is False
    assert "uncommitted" in (result.git_error or "").lower()
    assert (path / "f.txt").read_text() == "MON TRAVAIL EN COURS\n"


def test_no_rebase_in_progress_by_default(tmp_path):
    path = diverged(tmp_path)
    etat = rebase_state(pygit2.Repository(str(path)))
    assert etat.in_progress is False


def test_listing_targets_writes_nothing(tmp_path):
    """§7.0 : lister les branches ne modifie pas le dépôt."""
    import hashlib
    from pathlib import Path as P

    path = diverged(tmp_path)
    repo = pygit2.Repository(str(path))
    git_dir = P(repo.path)

    def empreinte():
        digest = hashlib.sha256()
        for item in sorted(git_dir.rglob("*")):
            if item.is_file():
                digest.update(f"{item}:{item.stat().st_mtime_ns}".encode())
        return digest.hexdigest()

    avant = empreinte()
    rebase_targets(repo)
    rebase_state(repo)
    assert empreinte() == avant
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/core/test_rebase.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tortoisepy.core.rebase'`

- [ ] **Step 3: Implémenter**

```python
# src/tortoisepy/core/rebase.py
"""Rebaser la branche courante sur une autre — phase 9.

Un rebase rejoue les commits un par un : il peut s'interrompre sur un
conflit, être repris, ou abandonné. Contrairement au merge, l'opération
survit entre deux processus — c'est ce qui permet à la fenêtre de
conflits de la piloter.

Sans Qt : `ui/` décide comment présenter tout cela.
"""

from __future__ import annotations

from dataclasses import dataclass

import pygit2
from pygit2.enums import FileStatus, RepositoryState

from tortoisepy.core.results import OperationResult, failed, guarded, succeeded


@dataclass(frozen=True)
class RebaseState:
    in_progress: bool = False
    branch: str | None = None
    """Branche rebasée, telle qu'elle s'appelait au départ."""

    onto_label: str | None = None
    """Nom lisible de la cible — ce que l'interface doit afficher.

    Indispensable : pendant un rebase, `ours` désigne la **cible** et
    `theirs` le commit rejoué, l'inverse du merge. Sans ce nom, les
    boutons ne peuvent pas dire la vérité à l'utilisateur.
    """

    conflicted: tuple[str, ...] = ()


def rebase_targets(repo: pygit2.Repository) -> tuple[str, ...]:
    """Branches sur lesquelles on peut rebaser, triées.

    Locales **et** distantes (D14) : `git rebase origin/main` est courant,
    et imposer un checkout préalable serait une gêne inutile.
    """
    courante = _current_branch_name(repo)

    noms: set[str] = set()
    try:
        noms.update(repo.branches.local)
        noms.update(repo.branches.remote)
    except pygit2.GitError:
        return ()

    # Se rebaser sur soi-même n'a pas de sens.
    noms.discard(courante)
    # `origin/HEAD` est un alias symbolique, pas une cible utile.
    noms = {n for n in noms if not n.endswith("/HEAD")}
    return tuple(sorted(noms))


def rebase_state(repo: pygit2.Repository) -> RebaseState:
    """Y a-t-il un rebase en cours, et sur quoi ?

    Relu depuis le disque à chaque appel : l'interface vit dans un autre
    contexte que celui qui a démarré le rebase (vérifié).
    """
    if repo.state() not in _REBASE_STATES:
        return RebaseState()

    try:
        rebase = repo.rebase_open()
    except (pygit2.GitError, KeyError, ValueError):
        return RebaseState(in_progress=True)

    conflits: tuple[str, ...] = ()
    if repo.index.conflicts is not None:
        conflits = tuple(
            sorted(
                (ours or theirs).path
                for _, ours, theirs in repo.index.conflicts
                if (ours or theirs) is not None
            )
        )

    return RebaseState(
        in_progress=True,
        branch=_short(rebase.orig_head_name),
        onto_label=_label_for(repo, rebase.onto_id),
        conflicted=conflits,
    )


@guarded("Rebase", changed_on_error=True)
def start_rebase(repo: pygit2.Repository, onto: str) -> OperationResult:
    """Rejoue la branche courante par-dessus `onto`.

    Un conflit n'est **pas** annulé (D13, qui révise la phase 8) : le
    rebase reste en cours pour être résolu, et `abort_rebase` offre la
    sortie de secours.
    """
    courante = _current_branch_name(repo)
    if courante is None:
        return failed(
            "Rebase", "no branch checked out", repository_changed=False
        )
    if onto == courante:
        return failed(
            "Rebase", f"'{onto}' is the current branch",
            repository_changed=False,
        )

    reference = _reference_for(repo, onto)
    if reference is None:
        return failed(
            "Rebase", f"branch '{onto}' not found", repository_changed=False
        )

    sale = _uncommitted(repo)
    if sale:
        # Refuser AVANT de toucher au dépôt : un rebase écrase l'arbre.
        return failed(
            "Rebase",
            f"uncommitted changes would be overwritten ({sale})",
            repository_changed=False,
        )

    rebase = repo.rebase_init(
        branch=repo.lookup_reference(repo.head.name),
        upstream=None,
        onto=reference,
    )
    return _run(repo, rebase, onto)


@guarded("Rebase", changed_on_error=True)
def continue_rebase(repo: pygit2.Repository) -> OperationResult:
    """Poursuit après résolution. Refuse s'il reste un conflit."""
    if repo.state() not in _REBASE_STATES:
        return failed(
            "Rebase", "no rebase in progress", repository_changed=False
        )

    if repo.index.conflicts is not None:
        noms = ", ".join(
            sorted(
                (ours or theirs).path
                for _, ours, theirs in repo.index.conflicts
                if (ours or theirs) is not None
            )
        )
        return failed("Rebase", f"unresolved conflicts remain: {noms}")

    rebase = repo.rebase_open()
    etiquette = _label_for(repo, rebase.onto_id)

    # L'étape courante est résolue : la valider avant de poursuivre.
    signature = _signature(repo)
    try:
        rebase.commit(committer=signature)
    except pygit2.GitError:
        # Rien à commiter : le patch était déjà appliqué en amont.
        pass

    return _run(repo, rebase, etiquette)


@guarded("Rebase", changed_on_error=True)
def abort_rebase(repo: pygit2.Repository) -> OperationResult:
    """Restaure la branche dans son état d'avant le rebase.

    **`Rebase.abort()`, pas `abort_operation`** : ce dernier fait
    `state_cleanup()` + `reset(HARD)`, ce qui sur la HEAD détachée d'un
    rebase la remet sur elle-même sans rattacher la branche. Le défaut
    avait été trouvé en phase 8 ; vérifié ici que `Rebase.abort()`
    restaure l'état, la branche et le commit d'origine.
    """
    if repo.state() not in _REBASE_STATES:
        return failed(
            "Rebase", "no rebase in progress", repository_changed=False
        )

    repo.rebase_open().abort()
    return succeeded("Rebase aborted, branch restored")


def _run(repo, rebase, etiquette) -> OperationResult:
    """Déroule les opérations restantes jusqu'au conflit ou à la fin."""
    signature = _signature(repo)
    rejoues = 0

    try:
        for _ in rebase:
            if repo.index.conflicts is not None:
                noms = ", ".join(
                    sorted(
                        (ours or theirs).path
                        for _, ours, theirs in repo.index.conflicts
                        if (ours or theirs) is not None
                    )
                )
                # Laissé EN COURS, exprès : c'est ce qui permet de le
                # résoudre puis de reprendre (D13).
                return failed("Rebase", f"conflicts in: {noms}")

            # `None` signale un commit devenu vide — le patch est déjà
            # en amont. `git rebase` le saute aussi ; ce n'est pas une
            # erreur (vérifié).
            if rebase.commit(committer=signature) is not None:
                rejoues += 1

        rebase.finish(signature)
    except Exception:
        # Ne jamais laisser un rebase à moitié fait sans issue : on le
        # défait avant de laisser l'erreur remonter à `guarded`.
        try:
            rebase.abort()
        except (pygit2.GitError, ValueError):
            pass
        raise

    pluriel = "" if rejoues == 1 else "s"
    return succeeded(f"Rebased {rejoues} commit{pluriel} onto {etiquette}")


_REBASE_STATES = frozenset(
    {
        RepositoryState.REBASE,
        RepositoryState.REBASE_INTERACTIVE,
        RepositoryState.REBASE_MERGE,
    }
)


def _reference_for(repo: pygit2.Repository, nom: str):
    """Référence correspondant à un nom de branche, locale ou distante."""
    for gabarit in ("refs/heads/{}", "refs/remotes/{}"):
        try:
            return repo.lookup_reference(gabarit.format(nom))
        except (KeyError, pygit2.GitError, ValueError):
            continue
    return None


def _label_for(repo: pygit2.Repository, oid) -> str | None:
    """Nom lisible de la cible, à partir de son commit."""
    for nom in list(repo.branches.local) + list(repo.branches.remote):
        try:
            if repo.branches[nom].target == oid:
                return nom
        except (KeyError, pygit2.GitError):
            continue
    return str(oid)[:8]


def _short(refname: str | None) -> str | None:
    if not refname:
        return None
    for prefixe in ("refs/heads/", "refs/remotes/"):
        if refname.startswith(prefixe):
            return refname[len(prefixe):]
    return refname


def _current_branch_name(repo: pygit2.Repository) -> str | None:
    if repo.head_is_unborn or repo.head_is_detached:
        return None
    try:
        return repo.head.shorthand
    except (pygit2.GitError, KeyError):
        return None


def _uncommitted(repo: pygit2.Repository) -> str:
    """Modifications qui empêchent un rebase. Vide s'il n'y en a pas."""
    bloquant = FileStatus.WT_MODIFIED | FileStatus.WT_DELETED
    bloquant |= FileStatus.INDEX_MODIFIED | FileStatus.INDEX_NEW
    bloquant |= FileStatus.INDEX_DELETED | FileStatus.CONFLICTED

    try:
        touches = [p for p, code in repo.status().items() if code & bloquant]
    except pygit2.GitError:
        return ""
    return ", ".join(sorted(touches)[:3])


def _signature(repo: pygit2.Repository) -> pygit2.Signature:
    try:
        return repo.default_signature
    except (KeyError, ValueError):
        return pygit2.Signature("tortoisePy", "tortoisepy@localhost")
```

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/core/test_rebase.py tests/test_read_only.py tests/test_architecture.py -v`
Expected: PASS — 16 + 7 + 5 tests.

- [ ] **Step 5: Signaler les fichiers prêts** — ne commite pas.

---

### Task 2: Le champ avec autocomplétion

**Files:**
- Modify: `src/tortoisepy/ui/dialogs.py`
- Test: `tests/ui/test_dialogs.py` (existe déjà — ajouts)

**Interfaces:**
- Consumes: rien
- Produces: `ask_branch(parent, title, label, choices, default="")`

**Vérifié :** `QCompleter` avec `MatchContains` fait ce qu'il faut — saisir
« main » propose `main` **et** `origin/main`.

- [ ] **Step 1: Écrire les tests**

```python
# à ajouter dans tests/ui/test_dialogs.py


def test_the_completer_offers_every_branch(qtbot):
    from tortoisepy.ui.dialogs import _branch_completer

    completer = _branch_completer(["main", "develop", "origin/main"])
    completer.setCompletionPrefix("")
    propositions = {
        completer.completionModel().index(i, 0).data()
        for i in range(completer.completionCount())
    }
    assert {"main", "develop", "origin/main"} <= propositions


def test_the_completer_matches_anywhere_in_the_name(qtbot):
    """Saisir « main » doit aussi proposer « origin/main »."""
    from tortoisepy.ui.dialogs import _branch_completer

    completer = _branch_completer(["main", "develop", "origin/main"])
    completer.setCompletionPrefix("main")
    propositions = {
        completer.completionModel().index(i, 0).data()
        for i in range(completer.completionCount())
    }
    assert propositions == {"main", "origin/main"}


def test_the_completer_ignores_case(qtbot):
    from tortoisepy.ui.dialogs import _branch_completer

    completer = _branch_completer(["Develop"])
    completer.setCompletionPrefix("dev")
    assert completer.completionCount() == 1
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/ui/test_dialogs.py -v -k completer`
Expected: FAIL — `_branch_completer` n'existe pas.

- [ ] **Step 3: Implémenter**

Ajouter aux imports de `dialogs.py` :

```python
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCompleter
```

**Vérifié :** `dialogs.py` importe déjà `QLineEdit` et `QInputDialog`, mais
**pas `Qt`** — sans cet ajout, `_branch_completer` lèverait un `NameError`
sur `Qt.CaseSensitivity`. `QCompleter` s'ajoute à l'import `QtWidgets`
existant.

Puis :

```python
def _branch_completer(choices) -> QCompleter:
    """Complète sur n'importe quelle partie du nom.

    `MatchContains` plutôt que le préfixe : saisir « main » doit proposer
    `origin/main` autant que `main`, sinon les branches distantes sont
    introuvables sans taper « origin/ » d'abord.
    """
    completer = QCompleter(list(choices))
    completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    completer.setFilterMode(Qt.MatchFlag.MatchContains)
    completer.setCompletionMode(
        QCompleter.CompletionMode.PopupCompletion
    )
    return completer


def ask_branch(
    parent, title: str, label: str, choices, default: str = ""
) -> str | None:
    """Demande une branche, avec autocomplétion. `None` si annulé.

    Refuse une saisie qui ne correspond à aucune branche connue : laisser
    passer un nom libre produirait une erreur de libgit2 que l'utilisateur
    ne saurait pas interpréter.
    """
    dialogue = QInputDialog(parent)
    dialogue.setWindowTitle(title)
    dialogue.setLabelText(label)
    dialogue.setTextValue(default)
    dialogue.setInputMode(QInputDialog.InputMode.TextInput)

    champ = dialogue.findChild(QLineEdit)
    if champ is not None:
        champ.setCompleter(_branch_completer(choices))

    if dialogue.exec() != QInputDialog.DialogCode.Accepted:
        return None

    saisie = dialogue.textValue().strip()
    if saisie not in set(choices):
        return None
    return saisie
```

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/ui/test_dialogs.py -v`
Expected: PASS.

- [ ] **Step 5: Signaler les fichiers prêts** — ne commite pas.

---

### Task 3: La fenêtre de conflits, côté rebase

**Files:**
- Modify: `src/tortoisepy/ui/conflict_window.py`
- Test: `tests/ui/test_conflict_window.py` (ajouts)

**Interfaces:**
- Consumes: `rebase_state`, `continue_rebase`, `abort_rebase` (tâche 1)
- Produces: `ConflictWindow` qui sert les deux opérations

**Le point délicat de cette phase.** En rebase, `ours` est la **cible** et
`theirs` le **commit rejoué** — l'inverse du merge. Garder « Keep mine » ferait
perdre son travail à qui croit le garder.

- [ ] **Step 1: Écrire les tests**

```python
# à ajouter dans tests/ui/test_conflict_window.py


def _rebase_conflict(tmp_path):
    """Un dépôt en plein rebase conflictuel, `feature` sur `main`."""
    from tortoisepy.core.rebase import start_rebase

    path = tmp_path / "reb"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "f.txt").write_text("a\nb\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "base")

    run_git(path, "checkout", "-q", "-b", "feature")
    (path / "f.txt").write_text("a\nFEATURE\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "cote feature")

    run_git(path, "checkout", "-q", "main")
    (path / "f.txt").write_text("a\nMAIN\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "cote main")
    run_git(path, "checkout", "-q", "feature")

    repo = pygit2.Repository(str(path))
    start_rebase(repo, "main")
    return repo


def test_a_rebase_window_says_continue(qtbot, tmp_path):
    """Résoudre ne termine pas un rebase : il reste des commits à rejouer."""
    fenetre = ConflictWindow(_rebase_conflict(tmp_path))
    qtbot.addWidget(fenetre)
    assert fenetre.resolve_button.text() == "Continue"


def test_a_merge_window_still_says_resolve(qtbot, conflicted):
    fenetre = ConflictWindow(conflicted)
    qtbot.addWidget(fenetre)
    assert fenetre.resolve_button.text() == "Resolve"


def test_the_rebase_buttons_name_the_real_sides(qtbot, tmp_path):
    """Review Focus 1 : « Keep mine » serait un mensonge en rebase.

    `ours` y désigne la cible, `theirs` le commit rejoué.
    """
    fenetre = ConflictWindow(_rebase_conflict(tmp_path))
    qtbot.addWidget(fenetre)

    assert "main" in fenetre.mine_button.text()
    assert "commit" in fenetre.theirs_button.text().lower()


def test_keeping_my_commit_during_a_rebase(qtbot, tmp_path):
    """Le bouton « mon commit » doit retenir la version rejouée."""
    repo = _rebase_conflict(tmp_path)
    fenetre = ConflictWindow(repo)
    qtbot.addWidget(fenetre)

    fenetre.select_file("f.txt")
    fenetre.take_theirs()

    chemin = os.path.join(repo.workdir, "f.txt")
    assert "FEATURE" in open(chemin).read()


def test_continue_completes_the_rebase(qtbot, tmp_path):
    repo = _rebase_conflict(tmp_path)
    fenetre = ConflictWindow(repo)
    qtbot.addWidget(fenetre)
    fenetre.show()

    fenetre.select_file("f.txt")
    fenetre.take_theirs()
    fenetre.resolve()

    fresh = pygit2.Repository(repo.path)
    assert fresh.state() == pygit2.enums.RepositoryState.NONE
    assert fresh.head_is_detached is False
    assert fenetre.isHidden() is True


def test_aborting_a_rebase_restores_the_branch(qtbot, tmp_path):
    """Review Focus 3 : `abort_operation` ne saurait pas le faire."""
    repo = _rebase_conflict(tmp_path)
    avant_oid = str(pygit2.Repository(repo.path).head.target)

    fenetre = ConflictWindow(repo)
    qtbot.addWidget(fenetre)
    fenetre.show()
    fenetre.abort()

    fresh = pygit2.Repository(repo.path)
    assert fresh.state() == pygit2.enums.RepositoryState.NONE
    assert fresh.head_is_detached is False
    assert fresh.head.shorthand == "feature"
    assert fenetre.isHidden() is True
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/ui/test_conflict_window.py -v -k rebase`
Expected: FAIL — la fenêtre ne connaît pas encore le rebase.

- [ ] **Step 3: Implémenter**

Dans `__init__`, après la création des boutons, détecter l'opération :

```python
        from tortoisepy.core.rebase import rebase_state

        self.rebase = rebase_state(repository)
        self._apply_labels()
```

Puis la méthode qui nomme les camps :

```python
    def _apply_labels(self) -> None:
        """Nomme les deux camps selon l'opération en cours.

        En **rebase**, `ours` désigne la branche cible et `theirs` le
        commit rejoué — l'inverse du merge (vérifié). Garder « Keep
        mine » ferait perdre son travail à qui croit le garder.

        « Continue » plutôt que « Resolve » : résoudre un conflit de
        rebase ne termine pas l'opération, il reste des commits à rejouer.
        """
        if not self.rebase.in_progress:
            self.mine_button.setText("Keep mine")
            self.theirs_button.setText("Take theirs")
            self.resolve_button.setText("Resolve")
            self.setWindowTitle("Resolve conflicts")
            return

        cible = self.rebase.onto_label or "target"
        self.mine_button.setText(f"Keep {cible}")
        self.theirs_button.setText("Keep my commit")
        self.resolve_button.setText("Continue")
        self.setWindowTitle(
            f"Rebase {self.rebase.branch or ''} onto {cible}".strip()
        )
```

`resolve()` route selon l'opération :

```python
    def resolve(self) -> None:
        """Conclut la fusion, ou poursuit le rebase."""
        if self.rebase.in_progress:
            from tortoisepy.core.rebase import continue_rebase

            result = continue_rebase(self.repository)
        else:
            result = conclude_merge(self.repository)

        self.finished.emit(result)
        if not result.success:
            show_error(self, result)
            self.refresh()
            return
        self.close()
```

`abort()` de même — et c'est le point critique :

```python
    def abort(self) -> None:
        """Rend la main : restaure l'état d'avant l'opération.

        Pour un rebase, **`abort_rebase` et non `abort_operation`** :
        celui-ci fait `state_cleanup()` + `reset(HARD)`, ce qui sur la
        HEAD détachée d'un rebase la remet sur elle-même sans rattacher
        la branche (défaut trouvé en phase 8).
        """
        if self.rebase.in_progress:
            from tortoisepy.core.rebase import abort_rebase

            result = abort_rebase(self.repository)
        else:
            result = operations.abort_operation(self.repository)

        self.finished.emit(result)
        if not result.success:
            show_error(self, result)
            return
        self.close()
```

Enfin, `refresh()` doit relire l'état : un rebase avance d'un commit à
l'autre, et la cible peut changer d'étiquette.

```python
        from tortoisepy.core.rebase import rebase_state

        self.rebase = rebase_state(self.repository)
        self._apply_labels()
```

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/ui/test_conflict_window.py -v`
Expected: PASS.

- [ ] **Step 5: Signaler les fichiers prêts** — ne commite pas.

---

### Task 4: Le menu et le lancement

**Files:**
- Modify: `src/tortoisepy/ui/context_menu.py`
- Modify: `src/tortoisepy/ui/actions.py`
- Modify: `src/tortoisepy/ui/main_window.py`
- Test: `tests/ui/test_context_menu.py`, `tests/ui/test_main_window.py`

**Interfaces:**
- Consumes: `rebase_targets`, `start_rebase`, `rebase_state` (tâche 1),
  `ask_branch` (tâche 2), `ConflictWindow` (tâche 3)
- Produces: entrée « Rebase… », `MainWindow.start_rebase_onto()`

- [ ] **Step 1: Écrire les tests**

```python
# à ajouter dans tests/ui/test_context_menu.py


def test_rebase_is_in_the_menu():
    from tortoisepy.ui.context_menu import build_menu_model

    entries = build_menu_model((_multi_branch_node(),), _on_main())

    def actions(es):
        for e in es:
            if e.action:
                yield e.action
            yield from actions(e.children)

    assert "rebase_branch" in set(actions(entries))


def test_rebase_is_offered_on_the_current_branch():
    """C'est la branche courante qu'on rebase ; ailleurs, il faut un checkout."""
    from tortoisepy.ui.context_menu import build_menu_model

    entries = build_menu_model((_multi_branch_node(),), _on_main())
    rebase = _find(entries, "Rebase…")
    assert rebase is not None
    assert rebase.enabled is True
```

```python
# à ajouter dans tests/ui/test_main_window.py


def test_rebase_asks_for_a_target(window, monkeypatch):
    from tortoisepy.ui import main_window as module

    demandes = []
    monkeypatch.setattr(
        module, "ask_branch",
        lambda parent, titre, label, choix, default="": demandes.append(choix),
    )
    window.start_rebase_onto()
    assert demandes, "la cible doit être demandée"


def test_cancelling_the_target_does_nothing(window, monkeypatch):
    """§7.0 : annuler n'écrit rien."""
    from tortoisepy.ui import main_window as module

    monkeypatch.setattr(
        module, "ask_branch", lambda *a, **k: None
    )
    avant = window.repository.head.target
    window.start_rebase_onto()
    assert window.repository.head.target == avant


def test_a_rebase_conflict_opens_the_window(window, monkeypatch):
    from tortoisepy.core.results import failed
    from tortoisepy.ui import main_window as module

    ouvertes = []
    monkeypatch.setattr(
        module.MainWindow, "open_conflict_window",
        lambda self: ouvertes.append(True),
    )
    monkeypatch.setattr(module, "show_error", lambda *a, **k: None)
    monkeypatch.setattr(module, "ask_branch", lambda *a, **k: "main")
    monkeypatch.setattr(
        module, "start_rebase",
        lambda repo, onto: failed("Rebase", "conflicts in: f.txt"),
    )

    window.start_rebase_onto()
    assert ouvertes, "un conflit doit ouvrir la fenêtre de résolution"
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/ui/test_context_menu.py tests/ui/test_main_window.py -q -k rebase`
Expected: FAIL — l'entrée et la méthode n'existent pas.

- [ ] **Step 3: Menu et action**

Dans `context_menu.py`, sous « Integrate », à côté de « Merge… » :

```python
                MenuEntry(
                    "Rebase…",
                    "rebase_branch",
                    # C'est la branche COURANTE qu'on rebase : l'entrée
                    # vaut pour elle, où que l'on ait cliqué.
                    enabled=not busy and state.head_branch is not None,
                    needs_confirmation=dirty,
                ),
```

Dans `actions.py`, sur le modèle de `_push_branch` :

```python
def _rebase_branch(ctx: ActionContext) -> OperationResult | None:
    """La fenêtre principale s'en charge : elle doit demander la cible."""
    return None
```

et l'enregistrer : `"rebase_branch": _rebase_branch,`

- [ ] **Step 4: Lancement (`main_window.py`)**

Imports :

```python
from tortoisepy.core.rebase import rebase_state, rebase_targets, start_rebase
from tortoisepy.ui.dialogs import ask_branch
```

Interception dans `_run_action`, à côté des autres :

```python
        if action == "rebase_branch":
            self.start_rebase_onto()
            return
```

Et la méthode :

```python
    def start_rebase_onto(self) -> None:
        """Demande la cible, puis rebase la branche courante dessus.

        Le rebase reste au premier plan : il ne passe pas par le réseau,
        et laisser l'utilisateur agir pendant qu'on réécrit ses commits
        inviterait les ennuis.
        """
        cibles = rebase_targets(self.repository)
        if not cibles:
            self.statusBar().showMessage("No branch to rebase onto", 8000)
            return

        courante = self.state.head_branch if self.state else None
        cible = ask_branch(
            self,
            "Rebase",
            f"Replay {courante} on top of:",
            cibles,
        )
        if cible is None:
            return

        result = start_rebase(self.repository, cible)
        self.refresh()
        self.statusBar().showMessage(
            result.summary or (result.git_error or ""), 15000
        )

        if result.success:
            return

        if "conflict" in (result.git_error or "").lower():
            self.open_conflict_window()
            return

        show_error(self, result)
```

**Reprise d'un rebase interrompu** — à appeler à la fin de `refresh()` :

```python
    def _offer_to_resume_rebase(self) -> None:
        """Un rebase laissé en cours doit rester visible.

        Fermer la fenêtre de conflits ne l'annule pas, exprès (§6) : on
        rappelle donc qu'il attend, plutôt que de laisser un état muet.
        """
        etat = rebase_state(self.repository)
        if not etat.in_progress:
            return
        self.statusBar().showMessage(
            f"Rebase in progress onto {etat.onto_label} — "
            f"{len(etat.conflicted)} conflict(s) to resolve",
            0,  # sans expiration : la situation dure
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
Expected: 783 + ~35 tests. **Deux échecs connus et sans rapport** :
`test_fetch_hides_the_bar_when_done` et `test_worker_reports_its_result`
expirent sous la charge de la suite complète (instabilité de fils
d'exécution, établie par comparaison avec et sans modification).

- [ ] **Step 8: Signaler les fichiers prêts** — ne commite pas. Donner le
décompte exact.

---

## Fin de phase 9

Le rebase est accessible depuis le graphe, sur n'importe quelle branche locale
ou distante, avec ses conflits résolubles sur place.

**Hors périmètre**, conformément à la spec §9 :

- **Rebase interactif** (`-i`) — une application à soi seule.
- **`rebase --onto`** — trois arguments, usage rare et piégeux.
- **Rebaser une autre branche que la courante** — c'est un checkout d'abord.
- **Résolution ligne à ligne** — on choisit un camp par fichier (D12).
