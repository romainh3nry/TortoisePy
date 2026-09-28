import os
import subprocess

import pygit2
import pytest
from PySide6.QtCore import Qt

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
    # Le fichier commité (suivi.txt) disparaît ; nouveau.txt reste (non coché).
    assert window.file_count() == 1


def test_commit_survives_a_locked_index(window, repo, monkeypatch):
    """Finding 2 (revue, tour 1) : l'échec de la resynchronisation ne doit
    jamais faire croire que le commit a échoué ou n'a pas eu lieu.

    Un `.git/index.lock` présent (git concurrent ou planté) fait lever
    `GitError` dans `_sync_index_after_commit`. Avant le correctif, cette
    exception s'échappait du slot Qt : `_after_commit` ne s'exécutait
    jamais, la fenêtre ne se rafraîchissait pas, et rien ne prévenait
    l'utilisateur que son commit — bien réel — avait eu lieu.
    """
    # `show_message` ouvrirait un `QMessageBox.information` bloquant : on le
    # neutralise comme le reste de la suite le fait pour `show_error`
    # (voir `tests/ui/test_main_window.py`), pour ne tester que le flux, pas
    # la boîte de dialogue elle-même.
    monkeypatch.setattr(
        "tortoisepy.ui.commit_window.show_message", lambda *a, **k: None
    )

    lock_path = os.path.join(repo.workdir, ".git", "index.lock")
    with open(lock_path, "w"):
        pass

    try:
        before = len(list(repo.walk(repo.head.target)))
        window.set_message("commit avec index verrouillé")

        window.commit()  # ne doit pas lever

        assert len(list(repo.walk(repo.head.target))) == before + 1
        # La fenêtre s'est bien rafraîchie malgré l'échec de la synchronisation :
        # le message est réinitialisé, preuve que `_after_commit` s'est exécuté.
        assert window.message() == ""
    finally:
        if os.path.exists(lock_path):
            os.remove(lock_path)


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


def test_conflicted_file_cannot_be_forced_via_set_checked(qtbot, tmp_path):
    """Finding 1 (revue, tour 1) : le flag Qt protège la souris, pas l'API.

    `set_checked` doit refuser de cocher un fichier non sélectionnable, et
    `checked_paths()` doit l'exclure même si la coche a quand même été
    posée par un autre chemin — sinon un conflit non résolu peut être
    commité, marqueurs `<<<<<<<` compris.
    """
    path = tmp_path / "conflit-force"
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
    # Un second fichier, sain, à côté du conflit : sans lui, `checked_paths()`
    # serait vide et `commit()` échouerait pour « nothing selected », ce qui
    # ouvrirait un `QMessageBox` bloquant sans rapport avec ce qu'on teste ici.
    (path / "sain.txt").write_text("ajout\n")

    w = CommitWindow(pygit2.Repository(str(path)))
    qtbot.addWidget(w)

    w.set_checked("f.txt", True)
    assert w.is_checked("f.txt") is False
    assert "f.txt" not in w.checked_paths()

    # Même en cochant la case Qt directement, sans passer par `set_checked` :
    # `checked_paths()` doit rester la seconde garde.
    item = w._item_for("f.txt")
    item.setCheckState(0, Qt.CheckState.Checked)
    assert "f.txt" not in w.checked_paths()

    w.set_checked("sain.txt", True)
    w.set_message("tentative sur un conflit")
    w.commit()

    repo = pygit2.Repository(str(path))
    commit = repo.get(repo.head.target)
    content = commit.tree["f.txt"].data.decode()
    assert "<<<<<<<" not in content
    assert "sain.txt" in {entry.name for entry in commit.tree}


def test_empty_repository_opens_without_crashing(qtbot, tmp_path):
    path = tmp_path / "vide"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")

    w = CommitWindow(pygit2.Repository(str(path)))
    qtbot.addWidget(w)
    assert w.file_count() == 0
