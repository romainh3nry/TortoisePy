# tortoisePy — Plan d'implémentation, phase 7 : pousser depuis le graphe

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fermer la fenêtre de commit quand c'est fait, dire si ça a marché,
pouvoir pousser depuis le graphe, et voir d'un coup d'œil ce qui n'est pas
encore sur le serveur.

**Architecture:** `core/push_state.py` répond « quels commits ne sont pas
encore poussés », sans Qt et sans rien écrire. La fenêtre de commit se ferme et
délègue l'annonce du résultat à la fenêtre principale, qui gagne un bouton Push
exécuté en arrière-plan comme le fetch. Le panneau et le graphe reçoivent une
marque — **ajoutée**, jamais substituée au rendu existant.

**Tech Stack:** Python 3.13, pygit2 1.20, PySide6 6.11, pytest-qt.

**Spec:** `docs/superpowers/specs/2026-09-28-tortoisepy-push-design.md`

**Prérequis:** phases 1 à 6 terminées, 639 tests passent.

## Global Constraints

- **Aucune commande `git` sur le dépôt tortoisePy.** Les étapes « commit » du
  modèle de plan sont remplacées par « signaler les fichiers prêts ». Les
  fixtures de test peuvent invoquer `git` via `subprocess` sur des dépôts
  temporaires.
- **Le rendu visuel validé ne doit pas être dégradé** (règle permanente de
  l'utilisateur). La pastille de la tâche 5 est un **ajout** : aucune couleur,
  forme, taille ou position existante n'est modifiée. Un nœud sans commit à
  pousser doit être dessiné **exactement** comme aujourd'hui, et un test le
  vérifie.
- **Rien ne s'écrit sans clic explicite (§7.0).** `tests/test_read_only.py`
  doit rester vert : calculer l'état de poussée ne touche pas au dépôt.
- **`core/` n'importe jamais PySide6.** Vérifié par `tests/test_architecture.py`.
- **Jamais de push forcé.** Aucune interface ne l'expose.
- **Les libellés de menu et de bouton sont en anglais** (« Push »), les
  commentaires et docstrings **en français**.
- **Toutes les structures retournées sont `frozen=True`.**
- **API vérifiées le 2026-09-28** sur pygit2 1.20 : `branch.upstream` vaut
  `None` quand aucun suivi n'est configuré ; `repo.branches[shorthand]` lève
  `KeyError` sur une HEAD détachée ; parcourir `repo.walk(upstream.target)`
  donne l'ensemble des commits déjà sur le serveur ;
  `upstream.remote_name` rend `'origin'`.
- **`FetchWorker` accepte n'importe quel appelable prenant `on_progress`** — il
  sert donc au push sans modification (vérifié).

## Review Focus

Cas que la spec implique et qu'aucune tâche n'exercerait sans y penser.

1. **Dépôt sans remote** — marquer tous les commits « non poussés » serait du
   bruit permanent. Rien ne doit être marqué. *(tâche 1)*
2. **HEAD détachée** — `repo.branches[shorthand]` lève `KeyError`. Ni calcul,
   ni marque, ni bouton actif. *(tâches 1 et 4)*
3. **Commit réussi mais push échoué** — la fenêtre se ferme quand même (le
   commit est acquis), le message le dit, et le dialogue d'erreur s'ouvre.
   *(tâches 2 et 3)*
4. **Échec du commit** — la fenêtre reste ouverte **et le message saisi est
   conservé** : le fermer ferait perdre la rédaction. *(tâche 2)*
5. **Nœud sans rien à pousser** — doit être peint exactement comme avant la
   phase 7, pastille comprise (c'est-à-dire sans pastille). *(tâche 5)*

---

### Task 1: Savoir ce qui n'est pas poussé

**Files:**
- Create: `src/tortoisepy/core/push_state.py`
- Test: `tests/core/test_push_state.py`

**Interfaces:**
- Consumes: rien de l'application
- Produces: `PushState`, `push_state(repo) -> PushState`,
  `unpushed_oids(repo) -> frozenset[str]`

Module en **lecture seule**, sans Qt.

- [ ] **Step 1: Écrire les tests**

```python
# tests/core/test_push_state.py
import os
import subprocess

import pygit2
import pytest

from tortoisepy.core.push_state import push_state, unpushed_oids


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
    """Un serveur nu, un clone, un commit poussé et deux commits locaux."""
    bare = tmp_path / "serveur.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", str(bare)], capture_output=True
    )
    work = tmp_path / "travail"
    subprocess.run(
        ["git", "clone", "-q", str(bare), str(work)], capture_output=True
    )
    (work / "f.txt").write_text("a\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "pousse")
    run_git(work, "push", "-q", "origin", "HEAD")

    (work / "f.txt").write_text("b\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "local 1")
    (work / "f.txt").write_text("c\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "local 2")
    return pygit2.Repository(str(work))


def summaries(repo, oids):
    return {repo.get(o).message.strip() for o in oids}


def test_local_commits_are_unpushed(pair):
    assert summaries(pair, unpushed_oids(pair)) == {"local 1", "local 2"}


def test_pushed_commit_is_not_listed(pair):
    assert "pousse" not in summaries(pair, unpushed_oids(pair))


def test_counts_them(pair):
    assert push_state(pair).unpushed_count == 2


def test_can_push(pair):
    assert push_state(pair).can_push is True


def test_names_the_remote(pair):
    assert push_state(pair).remote_name == "origin"


def test_names_the_branch(pair):
    assert push_state(pair).branch == "main"


def test_nothing_to_push_after_pushing(pair):
    run_git(pair.workdir, "push", "-q")
    fresh = pygit2.Repository(pair.path)
    assert unpushed_oids(fresh) == frozenset()
    assert push_state(fresh).can_push is False


def test_branch_without_upstream_has_everything_unpushed(tmp_path):
    """Une branche jamais poussée est justement celle qu'il faut publier."""
    bare = tmp_path / "s.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], capture_output=True)
    work = tmp_path / "w"
    subprocess.run(["git", "clone", "-q", str(bare), str(work)], capture_output=True)
    (work / "f.txt").write_text("a\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "base")
    run_git(work, "push", "-q", "origin", "HEAD")
    run_git(work, "checkout", "-q", "-b", "jamais-poussee")
    (work / "g.txt").write_text("neuf\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "sur la nouvelle branche")

    repo = pygit2.Repository(str(work))
    assert "sur la nouvelle branche" in summaries(repo, unpushed_oids(repo))
    assert push_state(repo).can_push is True


def test_repository_without_remote_marks_nothing(tmp_path):
    """Review Focus 1 : tout marquer en rouge serait du bruit permanent."""
    path = tmp_path / "solo"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "f.txt").write_text("a\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "seul")

    repo = pygit2.Repository(str(path))
    assert unpushed_oids(repo) == frozenset()

    state = push_state(repo)
    assert state.can_push is False
    assert state.reason  # explique pourquoi le bouton sera grisé


def test_detached_head_marks_nothing(pair):
    """Review Focus 2 : `branches[shorthand]` lève KeyError (vérifié)."""
    run_git(pair.workdir, "checkout", "-q", "--detach")
    fresh = pygit2.Repository(pair.path)

    assert unpushed_oids(fresh) == frozenset()
    state = push_state(fresh)
    assert state.can_push is False
    assert state.reason


def test_empty_repository_is_safe(tmp_path):
    path = tmp_path / "vide"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    repo = pygit2.Repository(str(path))
    assert unpushed_oids(repo) == frozenset()
    assert push_state(repo).can_push is False


def test_state_is_frozen(pair):
    import dataclasses

    state = push_state(pair)
    assert dataclasses.is_dataclass(state)
    with pytest.raises(dataclasses.FrozenInstanceError):
        state.can_push = True


def test_reading_state_writes_nothing(pair):
    """§7.0 : calculer l'état de poussée ne modifie pas le dépôt."""
    import hashlib
    from pathlib import Path

    git_dir = Path(pair.path)

    def fingerprint():
        digest = hashlib.sha256()
        for item in sorted(git_dir.rglob("*")):
            if item.is_file():
                digest.update(f"{item}:{item.stat().st_mtime_ns}".encode())
        return digest.hexdigest()

    before = fingerprint()
    unpushed_oids(pair)
    push_state(pair)
    assert fingerprint() == before
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/core/test_push_state.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tortoisepy.core.push_state'`

- [ ] **Step 3: Implémenter**

```python
# src/tortoisepy/core/push_state.py
"""Ce qui n'est pas encore sur le serveur — §5 de la spec phase 7.

Lecture seule, sans Qt : `ui/` décide comment le montrer.
"""

from __future__ import annotations

from dataclasses import dataclass

import pygit2

from tortoisepy.core.model import Oid


@dataclass(frozen=True)
class PushState:
    """De quoi griser un bouton et l'expliquer."""

    branch: str | None = None
    remote_name: str | None = None
    unpushed_count: int = 0
    can_push: bool = False
    reason: str = ""
    """Pourquoi on ne peut pas pousser — vide quand on peut."""


def unpushed_oids(repo: pygit2.Repository) -> frozenset[Oid]:
    """Commits présents localement mais pas sur la branche de suivi.

    Sans remote, l'ensemble est vide : marquer tous les commits d'un dépôt
    purement local serait du bruit permanent, jamais une information.
    """
    branch = _current_branch(repo)
    if branch is None or not list(repo.remotes.names()):
        return frozenset()

    try:
        local = {str(c.id) for c in repo.walk(branch.target)}
    except (pygit2.GitError, ValueError):
        return frozenset()

    upstream = branch.upstream
    if upstream is None:
        # Branche jamais poussée : tout est à publier, ce qui est exact.
        return frozenset(local)

    try:
        remote_side = {str(c.id) for c in repo.walk(upstream.target)}
    except (pygit2.GitError, ValueError):
        return frozenset()

    return frozenset(local - remote_side)


def push_state(repo: pygit2.Repository) -> PushState:
    """État de poussée de la branche courante."""
    branch = _current_branch(repo)
    if branch is None:
        return PushState(reason="no branch checked out")

    remotes = list(repo.remotes.names())
    if not remotes:
        return PushState(branch=branch.branch_name, reason="no remote configured")

    upstream = branch.upstream
    remote_name = upstream.remote_name if upstream is not None else remotes[0]

    count = len(unpushed_oids(repo))
    if count == 0:
        return PushState(
            branch=branch.branch_name,
            remote_name=remote_name,
            reason="nothing to push",
        )

    return PushState(
        branch=branch.branch_name,
        remote_name=remote_name,
        unpushed_count=count,
        can_push=True,
    )


def _current_branch(repo: pygit2.Repository):
    """Branche courante, ou `None` si HEAD est détachée ou non née.

    Vérifié : sur une HEAD détachée, `repo.branches[shorthand]` lève
    `KeyError` — d'où la garde explicite plutôt qu'un `try` autour de tout.
    """
    if repo.head_is_unborn or repo.head_is_detached:
        return None
    try:
        return repo.branches[repo.head.shorthand]
    except (KeyError, pygit2.GitError):
        return None
```

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/core/test_push_state.py tests/test_read_only.py tests/test_architecture.py -v`
Expected: PASS, 14 + 7 + 5 tests.

- [ ] **Step 5: Signaler les fichiers prêts** — ne commite pas.

---

### Task 2: Fermer la fenêtre et rapporter le résultat

**Files:**
- Modify: `src/tortoisepy/ui/commit_window.py`
- Test: `tests/ui/test_commit_window.py` (ajouts)

**Interfaces:**
- Consumes: `committed = Signal(object)` (déjà présent)
- Produces: comportement de fermeture ; le signal porte désormais aussi le
  résultat du push

**Le point délicat :** la fenêtre se ferme après un **succès**, reste ouverte
après un **échec**, et se ferme aussi quand le commit réussit mais que le push
échoue — le commit est acquis (§3 de la spec).

- [ ] **Step 1: Écrire les tests**

```python
# à ajouter dans tests/ui/test_commit_window.py


def test_window_closes_after_a_successful_commit(window, repo):
    window.set_message("un message")
    window.commit()
    assert window.isHidden() is True


def test_window_stays_open_after_a_failed_commit(window, repo, monkeypatch):
    """Review Focus 4 : fermer ferait perdre la rédaction."""
    from tortoisepy.core.results import failed
    from tortoisepy.ui import commit_window as module

    monkeypatch.setattr(module, "show_error", lambda *a, **k: None)
    monkeypatch.setattr(
        module.operations,
        "commit_selection",
        lambda *a, **k: failed("Commit", "refus simulé"),
    )

    window.set_message("un message que je ne veux pas perdre")
    window.commit()

    assert window.isHidden() is False
    assert window.message() == "un message que je ne veux pas perdre"


def test_window_closes_when_commit_succeeds_but_push_fails(
    window, repo, monkeypatch
):
    """Review Focus 3 : le commit est acquis, donc on rend la main."""
    from tortoisepy.core.results import failed
    from tortoisepy.ui import commit_window as module

    monkeypatch.setattr(module, "confirm", lambda *a, **k: True)
    monkeypatch.setattr(module, "show_error", lambda *a, **k: None)
    monkeypatch.setattr(
        module.operations,
        "push_branch",
        lambda *a, **k: failed("Push", "rejeté par le serveur"),
    )

    window.set_message("un message")
    window.commit_and_push()

    assert window.isHidden() is True


def test_committed_signal_carries_the_push_result(window, repo, monkeypatch):
    """La fenêtre principale doit pouvoir dire « poussé » ou « non poussé »."""
    from tortoisepy.core.results import succeeded
    from tortoisepy.ui import commit_window as module

    monkeypatch.setattr(module, "confirm", lambda *a, **k: True)
    monkeypatch.setattr(
        module.operations,
        "push_branch",
        lambda *a, **k: succeeded("Pushed main to origin"),
    )

    recus = []
    window.committed.connect(lambda *args: recus.append(args))
    window.set_message("un message")
    window.commit_and_push()

    assert recus, "le signal doit être émis"
    commit_result, push_result = recus[0]
    assert commit_result.success is True
    assert push_result is not None and push_result.success is True


def test_committed_signal_has_no_push_result_for_a_plain_commit(window, repo):
    recus = []
    window.committed.connect(lambda *args: recus.append(args))
    window.set_message("un message")
    window.commit()

    assert recus
    commit_result, push_result = recus[0]
    assert commit_result.success is True
    assert push_result is None
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/ui/test_commit_window.py -q -k "closes or stays_open or signal_carries or no_push_result"`
Expected: FAIL — la fenêtre ne se ferme pas, et le signal ne porte qu'un argument.

- [ ] **Step 3: Implémenter**

Changer la déclaration du signal :

```python
    committed = Signal(object, object)
    """(`OperationResult` du commit, `OperationResult` du push ou `None`).

    Deux arguments plutôt qu'un : la fenêtre principale doit distinguer
    « commité » de « commité et poussé », et annoncer un push échoué sans
    laisser croire que le commit l'a été aussi (§4 de la spec).
    """
```

`commit()` devient :

```python
    def commit(self) -> None:
        paths = self.checked_paths()
        result = operations.commit_selection(
            self.repository, paths, self.message()
        )
        if result.success:
            self._try_sync_index_after_commit(paths)
        self._after_commit(result, None)
```

`commit_and_push()` : remplacer sa fin par

```python
        pushed = operations.push_branch(self.repository)
        if not pushed.success:
            # Le commit est fait : le dire explicitement, sinon on croit
            # avoir tout perdu (§8 phase 6).
            show_error(self, pushed)

        self._after_commit(result, pushed)
```

et son chemin d'échec du commit par `self._after_commit(result, None)`.

Enfin `_after_commit` :

```python
    def _after_commit(self, result, pushed) -> None:
        """Annonce le résultat, puis rend la main au graphe si c'est fait.

        Sur un échec de commit la fenêtre reste ouverte **avec son message**
        : le refermer ferait perdre la rédaction alors qu'il y a justement
        une correction à faire (§3 de la spec).
        """
        self.committed.emit(result, pushed)

        if not result.success:
            show_error(self, result)
            return

        # Le commit est acquis — même si le push a échoué, il n'y a plus
        # rien à faire dans cette fenêtre.
        self.set_message("")
        self.refresh()
        self.close()
```

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/ui/test_commit_window.py -v`
Expected: PASS, 20 tests (15 existants + 5 nouveaux).

- [ ] **Step 5: Signaler les fichiers prêts** — ne commite pas.

---

### Task 3: Annoncer le résultat dans la barre d'état

**Files:**
- Modify: `src/tortoisepy/ui/main_window.py`
- Test: `tests/ui/test_main_window.py` (ajouts)

**Interfaces:**
- Consumes: `CommitWindow.committed(commit_result, push_result)` (tâche 2)
- Produces: `_on_committed(result, pushed)` mis à jour

Les quatre messages de §4 de la spec.

- [ ] **Step 1: Écrire les tests**

```python
# à ajouter dans tests/ui/test_main_window.py


def test_status_bar_reports_a_commit(window):
    from tortoisepy.core.results import succeeded

    window._on_committed(succeeded("Committed 2 files — a1b2c3d4"), None)
    assert "Committed 2 files" in window.statusBar().currentMessage()


def test_status_bar_reports_a_commit_and_push(window):
    from tortoisepy.core.results import succeeded

    window._on_committed(
        succeeded("Committed 2 files — a1b2c3d4"),
        succeeded("Pushed main to origin"),
    )
    message = window.statusBar().currentMessage()
    assert "Committed 2 files" in message
    assert "push" in message.lower()


def test_status_bar_says_when_the_push_failed(window):
    """Review Focus 3 : le commit est fait, l'utilisateur doit le savoir."""
    from tortoisepy.core.results import failed, succeeded

    window._on_committed(
        succeeded("Committed 2 files — a1b2c3d4"),
        failed("Push", "rejeté par le serveur"),
    )
    message = window.statusBar().currentMessage()
    assert "Committed 2 files" in message
    assert "fail" in message.lower() or "échou" in message.lower()


def test_a_failed_commit_does_not_claim_success(window, monkeypatch):
    from tortoisepy.core.results import failed
    from tortoisepy.ui import main_window as module

    monkeypatch.setattr(module, "show_error", lambda *a, **k: None)
    window._on_committed(failed("Commit", "rien de coché"), None)
    assert "Committed" not in window.statusBar().currentMessage()
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/ui/test_main_window.py -q -k "status_bar or failed_commit_does_not"`
Expected: FAIL — `_on_committed()` ne prend qu'un argument.

- [ ] **Step 3: Implémenter**

```python
    def _on_committed(self, result, pushed=None) -> None:
        """Un commit change l'historique : le graphe doit le refléter.

        Le résultat va dans la barre d'état, là où le fetch annonce déjà les
        siens : c'est le même genre d'information, au même endroit (§4).
        """
        if result.repository_changed:
            self.refresh()

        if not result.success:
            return  # la fenêtre de commit a déjà ouvert son dialogue

        message = result.summary
        if pushed is not None:
            message += (
                f", {pushed.summary.lower()}"
                if pushed.success
                else " (push failed)"
            )

        self.statusBar().showMessage(message, 15000)
```

**Attention à l'ordre :** `refresh()` appelle `_update_status()`, qui écrit
dans la barre d'état. Le `showMessage` doit donc venir **après** le
rafraîchissement, sinon il est écrasé — le même piège qu'au fetch en phase 5.

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/ui/test_main_window.py -v`
Expected: PASS.

- [ ] **Step 5: Signaler les fichiers prêts** — ne commite pas.

---

### Task 4: Le bouton Push

**Files:**
- Modify: `src/tortoisepy/ui/main_window.py`
- Modify: `src/tortoisepy/ui/context_menu.py`
- Modify: `src/tortoisepy/ui/actions.py`
- Test: `tests/ui/test_main_window.py`, `tests/ui/test_context_menu.py` (ajouts)

**Interfaces:**
- Consumes: `push_state()` (tâche 1), `push_branch()` (phase 6),
  `FetchWorker` / `BackgroundTask` (phase 5)
- Produces: `MainWindow.push_action`, `_start_push()`, `_on_push_finished()`

**Le patron existe déjà :** `_start_fetch` fait exactement cela pour le fetch.
Suivre sa structure plutôt qu'en inventer une autre. **Vérifié :**
`FetchWorker` accepte n'importe quel appelable prenant `on_progress`, donc il
sert au push sans modification.

- [ ] **Step 1: Écrire les tests**

```python
# à ajouter dans tests/ui/test_main_window.py


def test_push_action_exists(window):
    assert window.push_action is not None
    assert window.push_action.text() == "Push"


def test_push_is_disabled_without_a_remote(window):
    """Le dépôt de test n'a pas de remote."""
    window._update_push_action()
    assert window.push_action.isEnabled() is False


def test_disabled_push_explains_why(window):
    window._update_push_action()
    assert window.push_action.toolTip()


def test_push_is_enabled_when_there_is_something_to_push(window, monkeypatch):
    from tortoisepy.core.push_state import PushState
    from tortoisepy.ui import main_window as module

    monkeypatch.setattr(
        module,
        "push_state",
        lambda repo: PushState(
            branch="main", remote_name="origin", unpushed_count=2, can_push=True
        ),
    )
    window._update_push_action()
    assert window.push_action.isEnabled() is True


def test_push_refuses_when_already_running(window, monkeypatch):
    from tortoisepy.ui import main_window as module

    monkeypatch.setattr(module, "confirm", lambda *a, **k: True)

    class Busy:
        def is_running(self):
            return True

    window._task = Busy()
    window._start_push()
    assert "running" in window.statusBar().currentMessage().lower()


def test_push_asks_for_confirmation(window, monkeypatch):
    """§6.3 : pousser sort de la machine, donc on confirme."""
    from tortoisepy.ui import main_window as module

    demandes = []
    monkeypatch.setattr(
        module, "confirm", lambda *a, **k: demandes.append(a) or False
    )
    window._task = None
    window._start_push()
    assert demandes, "aucune confirmation demandée"
```

```python
# à ajouter dans tests/ui/test_context_menu.py


def test_push_is_in_the_menu():
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

    assert "push_branch" in set(actions(build_menu_model((node,), state)))
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/ui/test_main_window.py tests/ui/test_context_menu.py -q -k push`
Expected: FAIL — `push_action` n'existe pas, `push_branch` absent du menu.

- [ ] **Step 3: Menu et action**

Dans `context_menu.py`, ajouter auprès de « Fetch » :

```python
    entries.append(
        MenuEntry(
            "Push",
            "push_branch",
            # Grisé hors de la branche courante : pousser une autre branche
            # demanderait un checkout, qui existe déjà (§9).
            enabled=_is_current_branch(node, state),
        )
    )
```

Si `_is_current_branch` n'existe pas, l'écrire à côté des autres aides du
module, sur le modèle des entrées déjà conditionnées par `state`.

Dans `actions.py` :

```python
def _push_branch(ctx: ActionContext) -> OperationResult | None:
    """La fenêtre principale s'en charge : le push part en arrière-plan."""
    return None
```

et l'enregistrer : `"push_branch": _push_branch,`

- [ ] **Step 4: Bouton et exécution**

Dans `main_window.py`, importer :

```python
from tortoisepy.core.push_state import push_state
```

**Vérifié :** `main_window.py` importe déjà `confirm` et `show_error` depuis
`ui.dialogs`, mais **pas** `ConfirmationRequest`. L'ajouter à cet import
existant :

```python
from tortoisepy.ui.dialogs import (
    ConfirmationRequest,
    ask_name,
    ask_reset_mode,
    confirm,
    show_error,
)
```

Ajouter à `specs` dans `_build_actions` :

```python
            ("Push", QKeySequence("Ctrl+P"), self._start_push),
```

Puis, en gardant une référence pour pouvoir la griser :

```python
            if label == "Push":
                self.push_action = action
```

Intercepter l'action dans `_run_action`, comme `fetch_remote` et
`open_commit` le sont déjà :

```python
        if action == "push_branch":
            self._start_push()
            return
```

Et les méthodes :

```python
    def _update_push_action(self) -> None:
        """Grise le bouton quand il n'y a rien à pousser.

        Un bouton actif qui ne fait rien apprend à ignorer l'interface ;
        l'infobulle dit pourquoi il est grisé (§6.2).
        """
        state = push_state(self.repository)
        self.push_action.setEnabled(state.can_push)
        if state.can_push:
            self.push_action.setToolTip(
                f"Push {state.unpushed_count} commit(s) to {state.remote_name}"
            )
        else:
            self.push_action.setToolTip(state.reason or "nothing to push")

    def _start_push(self) -> None:
        """Pousse en arrière-plan, comme le fetch (§6.3)."""
        if self._task is not None and self._task.is_running():
            self.statusBar().showMessage("A background task is running", 3000)
            return

        state = push_state(self.repository)
        request = ConfirmationRequest(
            title="Push",
            message=(
                f"git push {state.remote_name} {state.branch}\n\n"
                f"{state.unpushed_count} commit(s) will be sent to the shared "
                "server. This cannot be undone on your own."
            ),
            destructive=False,
        )
        if not confirm(self, request):
            return

        from tortoisepy.core import operations

        self.progress.setRange(0, 0)
        self.progress.setFormat("Pushing…")
        self.progress.show()
        self.statusBar().showMessage("Pushing…")

        worker = FetchWorker(
            lambda on_progress: operations.push_branch(
                self.repository, on_progress=on_progress
            )
        )
        self._task = BackgroundTask(worker, self)
        self._task.progress.connect(self._on_fetch_progress)
        self._task.finished.connect(self._on_push_finished)
        self._task.start()

    def _on_push_finished(self, result) -> None:
        """Le graphe change : la branche de suivi a avancé."""
        self.progress.hide()
        self.refresh()          # d'abord : `refresh` réécrit la barre d'état
        self.statusBar().showMessage(result.summary, 15000)
        if not result.success:
            show_error(self, result)
```

Appeler `self._update_push_action()` à la fin de `refresh()`, pour que le
bouton suive l'état réel après chaque changement.

- [ ] **Step 5: Vérifier le succès**

Run: `.venv/bin/pytest tests/ui/ -q`
Expected: PASS.

- [ ] **Step 6: Signaler les fichiers prêts** — ne commite pas.

---

### Task 5: Montrer ce qui n'est pas poussé

**Files:**
- Modify: `src/tortoisepy/ui/theme.py` (ajout d'une couleur, sans en changer)
- Modify: `src/tortoisepy/ui/graph_items.py`
- Modify: `src/tortoisepy/ui/graph_view.py`
- Modify: `src/tortoisepy/ui/commit_panel.py`
- Modify: `src/tortoisepy/ui/main_window.py`
- Test: `tests/ui/test_graph_items.py`, `tests/ui/test_commit_panel.py`

**Interfaces:**
- Consumes: `unpushed_oids()` (tâche 1)
- Produces: `build_scene(graph, layout, unpushed=frozenset())`,
  `NodeItem(node, placement, scene_y, unpushed=False)`,
  `GraphView.show_graph(graph, layout, unpushed=frozenset())`

**Contrainte la plus forte du plan.** L'utilisateur a validé le rendu et
interdit de le dégrader. La pastille est un **ajout par-dessus** : le brush, le
pen, les étiquettes et les dimensions ne changent pas. Les paramètres sont
**optionnels**, donc tous les appels existants restent valides.

- [ ] **Step 1: Écrire les tests**

**Vérifié :** `tests/ui/test_graph_items.py` possède déjà les aides
`node(oid, *names)`, `edge(a, d, skipped)` et `simple_graph()`, et importe
déjà `layout_graph` et `QtMeasurer`, et construit
ses scènes via `build_scene(...)`. **Réutiliser celles-là**, ne pas en créer.
Il n'y a pas d'aide produisant un `Placement` isolé : passer par
`build_scene` puis récupérer les `NodeItem` de la scène, comme le font les
tests existants (`test_node_item_carries_its_model`).

```python
# à ajouter dans tests/ui/test_graph_items.py


def _node_items(scene):
    from tortoisepy.ui.graph_items import NodeItem

    return {
        item.node.oid: item
        for item in scene.items()
        if isinstance(item, NodeItem)
    }


def test_node_without_unpushed_commits_is_unchanged(qtbot):
    """Review Focus 5 : le rendu validé ne doit pas bouger d'un pixel."""
    from tortoisepy.layout.engine import layout_graph
    from tortoisepy.ui.graph_items import build_scene

    graph = simple_graph()
    layout = layout_graph(graph, QtMeasurer())

    avant = _node_items(build_scene(graph, layout))
    apres = _node_items(build_scene(graph, layout, unpushed=frozenset()))

    for oid, item in apres.items():
        assert item.brush().color() == avant[oid].brush().color()
        assert item.pen().color() == avant[oid].pen().color()
        assert item.rect() == avant[oid].rect()
        assert item.has_unpushed_marker() is False


def test_node_with_unpushed_commits_gets_a_marker(qtbot):
    from tortoisepy.layout.engine import layout_graph
    from tortoisepy.ui.graph_items import build_scene

    graph = simple_graph()
    layout = layout_graph(graph, QtMeasurer())
    cible = layout.placements[0].oid

    items = _node_items(build_scene(graph, layout, unpushed=frozenset({cible})))
    assert items[cible].has_unpushed_marker() is True

    # La pastille ne déplace ni n'agrandit le nœud.
    sans = _node_items(build_scene(graph, layout))
    assert items[cible].rect() == sans[cible].rect()
    # …ni ne change sa couleur : le remplissage dit le type de ref.
    assert items[cible].brush().color() == sans[cible].brush().color()


def test_build_scene_stays_compatible_without_the_argument(qtbot):
    """Les appels existants, sans le paramètre, doivent continuer à marcher."""
    from tortoisepy.layout.engine import layout_graph
    from tortoisepy.ui.graph_items import build_scene

    graph = simple_graph()
    layout = layout_graph(graph, QtMeasurer())
    assert build_scene(graph, layout) is not None
```

```python
# à ajouter dans tests/ui/test_commit_panel.py


def test_unpushed_commits_are_marked(qtbot, panel):
    from datetime import datetime

    from tortoisepy.core.commits import CommitInfo

    commits = (
        CommitInfo(
            oid="a" * 40, summary="pas encore poussé", message="m",
            author_name="A", author_email="a@a",
            when=datetime(2026, 9, 28), parent_count=1,
        ),
        CommitInfo(
            oid="b" * 40, summary="déjà poussé", message="m",
            author_name="A", author_email="a@a",
            when=datetime(2026, 9, 28), parent_count=1,
        ),
    )
    panel.show_commits("main", commits, unpushed=frozenset({"a" * 40}))

    assert panel.is_unpushed("a" * 40) is True
    assert panel.is_unpushed("b" * 40) is False


def test_title_counts_unpushed_commits(qtbot, panel):
    from datetime import datetime

    from tortoisepy.core.commits import CommitInfo

    commits = tuple(
        CommitInfo(
            oid=chr(97 + i) * 40, summary=f"c{i}", message="m",
            author_name="A", author_email="a@a",
            when=datetime(2026, 9, 28), parent_count=1,
        )
        for i in range(3)
    )
    panel.show_commits(
        "main", commits, unpushed=frozenset({"a" * 40, "b" * 40})
    )
    assert "2" in panel.title()


def test_show_commits_without_unpushed_still_works(qtbot, panel):
    """Compatibilité : l'argument est optionnel."""
    from datetime import datetime

    from tortoisepy.core.commits import CommitInfo

    panel.show_commits(
        "main",
        (
            CommitInfo(
                oid="a" * 40, summary="c", message="m",
                author_name="A", author_email="a@a",
                when=datetime(2026, 9, 28), parent_count=1,
            ),
        ),
    )
    assert panel.count() == 1
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/ui/test_graph_items.py tests/ui/test_commit_panel.py -q -k "unpushed or marker or compatible"`
Expected: FAIL — paramètres et méthodes absents.

- [ ] **Step 3: La couleur (ajout à `theme.py`)**

```python
UNPUSHED_MARKER = QColor(230, 140, 30)
"""Pastille des branches ayant des commits non poussés.

Orange : ni le vert de HEAD, ni le jaune des branches locales, ni le rouge
de la sélection — la marque doit se lire comme une information nouvelle,
pas comme un changement d'état du nœud."""

UNPUSHED_MARKER_RADIUS = 4.0
```

**Ne modifier aucune valeur existante de ce fichier.**

- [ ] **Step 4: La pastille (`graph_items.py`)**

`NodeItem.__init__` prend `unpushed: bool = False` et le mémorise :

```python
        self.unpushed = unpushed
```

`has_unpushed_marker()` :

```python
    def has_unpushed_marker(self) -> bool:
        return self.unpushed
```

Et à la **fin** de `paint`, après le rectangle — sans rien changer avant :

```python
        if self.unpushed:
            # Dessinée par-dessus, après coup : le rectangle, sa couleur et
            # ses étiquettes restent exactement ce qu'ils étaient (règle
            # utilisateur : ne pas dégrader le rendu validé).
            radius = theme.UNPUSHED_MARKER_RADIUS
            centre = self.rect().topRight() + QPointF(-radius - 2.0, radius + 2.0)
            painter.setBrush(QBrush(theme.UNPUSHED_MARKER))
            painter.setPen(QPen(theme.PALETTE.border, 1.0))
            painter.drawEllipse(centre, radius, radius)
```

Importer `QPointF` depuis `PySide6.QtCore` s'il ne l'est pas déjà.

`build_scene` prend `unpushed: frozenset[str] = frozenset()` et le passe :

```python
        item = NodeItem(
            node,
            placement,
            _to_scene_y(placement, layout.height),
            unpushed=_node_has_unpushed(node, unpushed),
        )
```

avec :

```python
def _node_has_unpushed(node, unpushed: frozenset[str]) -> bool:
    """Le nœud porte-t-il un commit non poussé ?

    Un nœud représente une ref, pas un commit isolé : la pastille dit
    « cette branche a des choses à pousser ». Le détail par commit est dans
    le panneau latéral.
    """
    if not unpushed:
        return False
    return node.oid in unpushed
```

- [ ] **Step 5: Faire suivre depuis la vue et la fenêtre**

`GraphView.show_graph` prend `unpushed: frozenset[str] = frozenset()` et le
transmet à `build_scene`.

Dans `main_window.refresh()`, calculer une fois et passer :

```python
        unpushed = unpushed_oids(self.repository)
        self.view.show_graph(
            self.graph, layout_graph(self.graph, self.measurer), unpushed
        )
```

- [ ] **Step 6: Le panneau**

`show_commits` prend `unpushed: frozenset[str] = frozenset()`. Pour chaque
ligne :

```python
            if commit.oid in unpushed:
                item.setText(0, f"↑ {commit.short_oid}")
                item.setData(0, UNPUSHED_ROLE, True)
```

et le titre gagne le compte quand il y en a :

```python
        non_pousses = sum(1 for c in commits if c.oid in unpushed)
        if non_pousses:
            titre += f" — {non_pousses} non poussé{'s' if non_pousses > 1 else ''}"
```

Ajouter les accesseurs `is_unpushed(oid)` et `title()` utilisés par les tests.
Dans `main_window`, passer `unpushed_oids(self.repository)` à l'appel existant
de `show_commits`.

- [ ] **Step 7: Vérifier le succès**

Run: `.venv/bin/pytest tests/ui/ -q`
Expected: PASS.

- [ ] **Step 8: Vérifier la non-régression du rendu**

Run: `.venv/bin/pytest tests/ui/test_graph_items.py -v`
Expected: PASS — en particulier
`test_node_without_unpushed_commits_is_unchanged`.

- [ ] **Step 9: Suite complète**

Run: `.venv/bin/pytest -q`
Expected: 639 + ~30 tests, tous verts. **Attendre la fin** (environ 6 min).

- [ ] **Step 10: Signaler les fichiers prêts** — ne commite pas. Donner le
décompte exact.

---

## Fin de phase 7

Le cycle est complet : voir, commiter, pousser, et savoir ce qui reste à
pousser — sans quitter le graphe.

**Hors périmètre**, conformément à la spec §9 :

- **Pull** — il fusionne, avec ses conflits.
- **Push forcé** — jamais.
- **Pousser une autre branche que la courante** — c'est un checkout d'abord.
- **Staging par hunk** — toujours reporté (D5, phase 6).
