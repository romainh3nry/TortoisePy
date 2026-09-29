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


def test_a_rebase_without_a_readable_target_still_names_the_sides(
    qtbot, tmp_path
):
    """Métadonnées illisibles : décrire le camp plutôt que le mal nommer.

    `onto_label` vaut alors `None`. Un bouton « Keep target » n'apprend
    rien à qui doit choisir entre deux versions ; la description, elle,
    reste vraie sans le nom.
    """
    import glob

    repo = _rebase_conflict(tmp_path)
    for dossier in glob.glob(os.path.join(repo.path, "rebase-*")):
        onto = os.path.join(dossier, "onto")
        if os.path.exists(onto):
            open(onto, "w").write("nimportequoi\n")

    fenetre = ConflictWindow(pygit2.Repository(repo.path))
    qtbot.addWidget(fenetre)

    assert fenetre.mine_button.text() == "Keep the branch I rebase onto"
    assert fenetre.theirs_button.text() == "Keep my commit"
    assert fenetre.windowTitle() == "Rebase in progress"
    # Surtout : pas de titre bancal à double espace.
    assert "  " not in fenetre.windowTitle()
