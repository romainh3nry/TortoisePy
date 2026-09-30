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


def test_a_local_branch_named_like_a_remote_head_is_still_offered(tmp_path):
    """Fix round 1, finding 2 : seul `<remote>/HEAD` doit sauter.

    `n.endswith("/HEAD")` seul avalait aussi une vraie branche locale
    finissant par `/HEAD` — une branche invisible est une branche sur
    laquelle on ne peut pas se rebaser.
    """
    bare = tmp_path / "s.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], capture_output=True)
    work = tmp_path / "w"
    subprocess.run(["git", "clone", "-q", str(bare), str(work)], capture_output=True)
    (work / "f.txt").write_text("a\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "base")
    run_git(work, "push", "-q", "origin", "HEAD")
    run_git(work, "branch", "feature/HEAD")

    cibles = rebase_targets(pygit2.Repository(str(work)))
    assert "feature/HEAD" in cibles
    assert "origin/HEAD" not in cibles


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


def test_continue_reports_the_resolved_commit_in_its_count(tmp_path):
    """Fix round 1, finding 3 : `continue_rebase` commite l'étape résolue
    lui-même, avant que `_run` ne reprenne le compte — ce commit doit
    être annoncé, pas donner « Rebased 0 commits »."""
    path = diverged(tmp_path)
    repo = pygit2.Repository(str(path))
    start_rebase(repo, "main")
    resolve_with(repo, "f.txt", Side.THEIRS)

    result = continue_rebase(pygit2.Repository(str(path)))
    assert result.success is True, result.git_error
    assert "1 commit" in result.summary
    assert "0 commit" not in result.summary


def test_starting_while_a_rebase_is_in_progress_says_so(tmp_path):
    """Fix round 1, finding 3 (bis) : HEAD détachée ne doit pas se lire
    comme « no branch checked out », message qui n'oriente vers rien."""
    path = diverged(tmp_path)
    repo = pygit2.Repository(str(path))
    start_rebase(repo, "main")

    result = start_rebase(pygit2.Repository(str(path)), "main")
    assert result.success is False
    assert "already in progress" in (result.git_error or "").lower()


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


def test_a_damaged_rebase_directory_points_at_the_terminal(tmp_path):
    """Fix round 1, finding 1 : recouvrer d'un `.git` corrompu est hors
    périmée — même `git rebase --abort` échoue dans ce cas et laisse une
    HEAD détachée (vérifié par le coordinateur). Ce qui est exigé ici,
    c'est un message exploitable, pas une récupération miraculeuse.
    """
    path = diverged(tmp_path)
    repo = pygit2.Repository(str(path))
    start_rebase(repo, "main")

    onto_file = path / ".git" / "rebase-merge" / "onto"
    assert onto_file.exists()
    onto_file.unlink()

    result = abort_rebase(pygit2.Repository(str(path)))
    assert result.success is False
    assert "terminal" in (result.git_error or "").lower()


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


def test_a_rebase_started_by_git_is_not_called_damaged(tmp_path):
    """Revue finale, Important 2 : ne pas accuser un dépôt sain.

    Depuis git 2.26 le backend par défaut est « merge/interactive » :
    `.git/rebase-merge` porte un fichier `interactive` que libgit2 refuse
    d'ouvrir. C'est le cas **normal** d'un rebase lancé au terminal, et
    rien n'est abîmé — vérifié, `git rebase --abort` s'en sort très bien.
    Répondre « metadata is damaged » serait une fausse accusation, qui
    pousserait à des réparations destructrices.
    """
    path = diverged(tmp_path)
    run_git(path, "rebase", "main")  # c'est git, pas nous, qui démarre

    repo = pygit2.Repository(str(path))
    assert repo.state() in (
        pygit2.enums.RepositoryState.REBASE,
        pygit2.enums.RepositoryState.REBASE_MERGE,
        pygit2.enums.RepositoryState.REBASE_INTERACTIVE,
    )

    for resultat in (
        continue_rebase(pygit2.Repository(str(path))),
        abort_rebase(pygit2.Repository(str(path))),
    ):
        assert resultat.success is False
        detail = resultat.git_error or ""
        assert "damaged" not in detail, detail
        assert "started by git" in detail, detail
        assert "git rebase --abort" in detail, detail


def test_truly_damaged_metadata_is_still_reported_as_damaged(tmp_path):
    """L'inverse : ne pas excuser un vrai dégât par le cas précédent."""
    import glob

    path = diverged(tmp_path)
    start_rebase(pygit2.Repository(str(path)), "main")

    repo = pygit2.Repository(str(path))
    for dossier in glob.glob(os.path.join(repo.path, "rebase-*")):
        onto = os.path.join(dossier, "onto")
        if os.path.exists(onto):
            open(onto, "w").write("nimportequoi\n")

    resultat = abort_rebase(pygit2.Repository(str(path)))
    assert resultat.success is False
    assert "damaged" in (resultat.git_error or "")


def test_rebasing_another_branch_than_the_current_one(tmp_path):
    """Demandé par l'utilisateur : la phase 9 ne rejouait que la courante.

    Cliquer droit sur une branche et choisir « Rebase… » laissait croire
    qu'on rebasait celle-là, alors que c'était la courante — le piège que
    cette phase corrige.
    """
    # `meme_fichier=False` : sans conflit, le rebase doit aboutir.
    path = diverged(tmp_path, meme_fichier=False)
    run_git(path, "checkout", "-q", "main")

    repo = pygit2.Repository(str(path))
    assert repo.head.shorthand == "main"

    resultat = start_rebase(repo, "main", branch="feature")
    assert resultat.success is True, resultat.git_error

    fresh = pygit2.Repository(str(path))
    messages = [c.message.strip() for c in fresh.walk(fresh.branches["feature"].target)]
    assert "cote main" in messages, "feature doit être rejouée par-dessus main"


def test_rebasing_another_branch_switches_onto_it(tmp_path):
    """D46 : vérifié, `git rebase main feature` bascule aussi sur feature.

    La fenêtre le dit à l'avance plutôt que de le contredire : revenir
    sur la branche de départ s'écarterait de git et ajouterait une
    écriture dans le dépôt.
    """
    # `meme_fichier=False` : sans conflit, le rebase doit aboutir.
    path = diverged(tmp_path, meme_fichier=False)
    run_git(path, "checkout", "-q", "main")

    start_rebase(pygit2.Repository(str(path)), "main", branch="feature")

    fresh = pygit2.Repository(str(path))
    assert fresh.head_is_detached is False
    assert fresh.head.shorthand == "feature"


def test_without_a_branch_the_current_one_is_replayed(tmp_path):
    """Le comportement de la phase 9 reste le défaut."""
    # `meme_fichier=False` : sans conflit, le rebase doit aboutir.
    path = diverged(tmp_path, meme_fichier=False)
    repo = pygit2.Repository(str(path))
    courante = repo.head.shorthand

    assert start_rebase(repo, "main").success is True

    fresh = pygit2.Repository(str(path))
    assert fresh.head.shorthand == courante


def test_rebasing_a_branch_onto_itself_is_refused(tmp_path):
    # `meme_fichier=False` : sans conflit, le rebase doit aboutir.
    path = diverged(tmp_path, meme_fichier=False)
    run_git(path, "checkout", "-q", "main")

    resultat = start_rebase(
        pygit2.Repository(str(path)), "feature", branch="feature"
    )
    assert resultat.success is False
    assert "feature" in (resultat.git_error or "")


def test_rebasing_an_unknown_branch_is_refused(tmp_path):
    # `meme_fichier=False` : sans conflit, le rebase doit aboutir.
    path = diverged(tmp_path, meme_fichier=False)
    resultat = start_rebase(
        pygit2.Repository(str(path)), "main", branch="nexiste-pas"
    )
    assert resultat.success is False
    assert "nexiste-pas" in (resultat.git_error or "")


def test_a_dirty_tree_blocks_rebasing_another_branch(tmp_path):
    """Vérifié : libgit2 refuse déjà (« unstaged changes exist in workdir »).

    L'assertion qui compte n'est pas le refus mais que **rien n'a
    changé** — la branche visée doit rester intacte.
    """
    # `meme_fichier=False` : sans conflit, le rebase doit aboutir.
    path = diverged(tmp_path, meme_fichier=False)
    run_git(path, "checkout", "-q", "main")
    (path / "f.txt").write_text("modification non commitée\n")

    avant = str(pygit2.Repository(str(path)).branches["feature"].target)
    resultat = start_rebase(
        pygit2.Repository(str(path)), "main", branch="feature"
    )

    assert resultat.success is False
    fresh = pygit2.Repository(str(path))
    assert str(fresh.branches["feature"].target) == avant, (
        "la branche visée ne doit pas bouger"
    )
    assert fresh.head.shorthand == "main", "on ne doit pas avoir basculé"
