import os
import subprocess
from pathlib import Path

import pygit2
import pytest

from tortoisepy.core.operations import abort_operation
from tortoisepy.core.pull import (
    PullKind,
    analyse_pull,
    pull_fast_forward,
    pull_merge,
    pull_rebase,
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

    # Le dépôt reste réellement récupérable : abort_operation doit tout
    # remettre comme avant la tentative de fusion (§ règle « jamais coincé »).
    abort_result = abort_operation(fresh)
    assert abort_result.success is True, abort_result.git_error
    assert fresh.index.conflicts is None
    assert fresh.state() == pygit2.enums.RepositoryState.NONE
    assert (work / "f.txt").read_text() == "ligne1\nLOCAL\n"


def test_rebase_replays_local_commit_on_top(tmp_path):
    """Le cas courant : rejouer le commit local par-dessus l'amont, sans conflit.

    Deux fichiers différents (g.txt distant, h.txt local) pour que le rejeu
    ne puisse pas entrer en conflit — on teste ici le chemin heureux, pas la
    résolution.
    """
    bare, work = make_pair(tmp_path)
    other = tmp_path / "autre"
    subprocess.run(
        ["git", "clone", "-q", str(bare), str(other)], capture_output=True
    )
    (other / "g.txt").write_text("distant\n")
    run_git(other, "add", ".")
    run_git(other, "commit", "-q", "-m", "distant")
    run_git(other, "push", "-q")

    (work / "h.txt").write_text("local\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "local")
    run_git(work, "fetch", "-q")

    repo = pygit2.Repository(str(work))
    result = pull_rebase(repo)
    assert result.success is True, result.git_error

    fresh = pygit2.Repository(str(work))
    assert fresh.state() == pygit2.enums.RepositoryState.NONE
    assert fresh.head_is_detached is False
    assert (work / "g.txt").exists()
    assert (work / "h.txt").exists()

    messages = [c.message.strip() for c in fresh.walk(fresh.head.target)]
    assert "local" in messages
    assert "distant" in messages


def test_rebase_with_conflict_rolls_back(tmp_path):
    """Un conflit en rebase ne doit pas laisser l'utilisateur coincé.

    `abort_operation` ne sait pas rattacher une HEAD détachée par un rebase :
    `pull_rebase` doit donc abandonner lui-même le rebase et rendre la main
    dans un état propre.
    """
    bare, work = make_pair(tmp_path)
    advance_remote(tmp_path, bare)
    (work / "f.txt").write_text("ligne1\nLOCAL\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "local")
    run_git(work, "fetch", "-q")

    repo = pygit2.Repository(str(work))
    result = pull_rebase(repo)

    assert result.success is False
    assert "conflict" in (result.git_error or "").lower()

    fresh = pygit2.Repository(str(work))
    assert fresh.state() == pygit2.enums.RepositoryState.NONE
    assert fresh.head_is_detached is False
    assert (work / "f.txt").read_text() == "ligne1\nLOCAL\n"

    messages = [c.message.strip() for c in fresh.walk(fresh.head.target)]
    assert "local" in messages


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


def test_rebase_rolls_back_on_any_failure(tmp_path, monkeypatch):
    """Une panne autre qu'un conflit ne doit pas laisser la HEAD détachée.

    Signalé par la re-revue du tour 1 : le `rebase.abort()` ne couvrait que
    le chemin « conflit ». Vérifié qu'une exception pendant `commit()`
    laissait `## HEAD (no branch)`, état 9 — la même impasse que le défaut
    d'origine, par un autre chemin.
    """
    bare, work = make_pair(tmp_path, "panne")

    other = tmp_path / "autre-panne"
    subprocess.run(
        ["git", "clone", "-q", str(bare), str(other)], capture_output=True
    )
    (other / "distant.txt").write_text("distant\n")
    run_git(other, "add", ".")
    run_git(other, "commit", "-q", "-m", "cote distant")
    run_git(other, "push", "-q")

    (work / "local.txt").write_text("local\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "cote local")
    run_git(work, "fetch", "-q")

    repo = pygit2.Repository(str(work))
    before = str(repo.head.target)

    def panne(self, *args, **kwargs):
        raise pygit2.GitError("panne simulée pendant le rejeu")

    monkeypatch.setattr(pygit2.Rebase, "commit", panne)
    result = pull_rebase(repo)
    monkeypatch.undo()

    assert result.success is False

    fresh = pygit2.Repository(str(work))
    assert fresh.state() == pygit2.enums.RepositoryState.NONE
    assert fresh.head_is_detached is False
    assert str(fresh.head.target) == before


def test_a_second_pull_during_a_conflict_is_refused(tmp_path):
    """Régression trouvée par la revue finale de la phase 8.

    Relancer un pull pendant un conflit est le geste le plus naturel. Or
    `repo.status()` rend `CONFLICTED`, que le masque de
    `_uncommitted_changes` ignorait : l'arbre se lisait « propre », la
    garde passait, et libgit2 effaçait `MERGE_HEAD` avant de rejeter la
    fusion. Les conflits restaient sans `MERGE_HEAD`, donc
    `conclude_merge` ne pouvait plus conclure et `abort_operation`
    répondait « no operation in progress » : **plus aucune sortie**.
    """
    bare, work = make_pair(tmp_path, "double")
    advance_remote(tmp_path, bare)
    (work / "f.txt").write_text("ligne1\nLOCAL\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "local")
    run_git(work, "fetch", "-q")

    repo = pygit2.Repository(str(work))
    assert pull_merge(repo).success is False  # conflit attendu
    assert repo.index.conflicts is not None

    merge_head = Path(repo.path) / "MERGE_HEAD"
    assert merge_head.exists()

    second = pull_merge(pygit2.Repository(str(work)))
    assert second.success is False
    assert "conflict" in (second.git_error or "").lower()

    # L'essentiel : la fusion en cours est intacte, donc récupérable.
    assert merge_head.exists(), "MERGE_HEAD doit survivre au second pull"

    fresh = pygit2.Repository(str(work))
    assert fresh.index.conflicts is not None
    assert abort_operation(fresh).success is True


def test_pull_is_refused_while_an_operation_is_in_progress(tmp_path):
    """Un revert inachevé bloque aussi le pull, pour la même raison."""
    bare, work = make_pair(tmp_path, "revert")
    advance_remote(tmp_path, bare)
    run_git(work, "fetch", "-q")
    run_git(work, "revert", "--no-commit", "HEAD")

    result = pull_fast_forward(pygit2.Repository(str(work)))
    assert result.success is False
    assert "operation in progress" in (result.git_error or "").lower()
