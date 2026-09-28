import os
import subprocess

import pytest

from tortoisepy.ui.watcher import RepositoryWatcher


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
def repo_path(tmp_path):
    path = tmp_path / "watched"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "master")
    (path / "f.txt").write_text("base\n")
    run_git(path, "add", "f.txt")
    run_git(path, "commit", "-q", "-m", "base")
    return path


def test_watcher_starts_and_stops(qtbot, repo_path):
    watcher = RepositoryWatcher(str(repo_path / ".git"))
    watcher.start()
    assert watcher.is_watching()
    watcher.stop()
    assert not watcher.is_watching()


def test_watcher_watches_the_expected_paths(qtbot, repo_path):
    """§7.9 : HEAD, refs/, packed-refs et index."""
    watcher = RepositoryWatcher(str(repo_path / ".git"))
    watcher.start()
    watched = " ".join(watcher.watched_paths())
    assert "HEAD" in watched
    assert "refs" in watched
    watcher.stop()


def test_ref_change_triggers_graph_refresh(qtbot, repo_path):
    """Un commit externe doit demander la reconstruction du graphe."""
    watcher = RepositoryWatcher(str(repo_path / ".git"), debounce_ms=50)
    watcher.start()

    with qtbot.waitSignal(watcher.graph_changed, timeout=3000):
        (repo_path / "f.txt").write_text("modifié\n")
        run_git(repo_path, "add", "f.txt")
        run_git(repo_path, "commit", "-q", "-m", "externe")

    watcher.stop()


def test_debounce_collapses_a_burst(qtbot, repo_path):
    """§7.9 : un seul `git commit` produit plusieurs événements fichier.

    Sans anti-rebond, le graphe serait reconstruit trois fois.
    """
    watcher = RepositoryWatcher(str(repo_path / ".git"), debounce_ms=200)
    watcher.start()

    calls = []
    watcher.graph_changed.connect(lambda: calls.append(1))

    for index in range(5):
        (repo_path / "f.txt").write_text(f"v{index}\n")
        run_git(repo_path, "add", "f.txt")
        run_git(repo_path, "commit", "-q", "-m", f"c{index}")

    qtbot.wait(800)
    watcher.stop()

    assert len(calls) < 5, f"anti-rebond inopérant : {len(calls)} émissions"


def test_suspend_blocks_notifications(qtbot, repo_path):
    """§7.9 : la surveillance est suspendue pendant nos propres opérations."""
    watcher = RepositoryWatcher(str(repo_path / ".git"), debounce_ms=50)
    watcher.start()

    calls = []
    watcher.graph_changed.connect(lambda: calls.append(1))

    with watcher.suspended():
        (repo_path / "f.txt").write_text("interne\n")
        run_git(repo_path, "add", "f.txt")
        run_git(repo_path, "commit", "-q", "-m", "interne")
        qtbot.wait(300)

    assert calls == []
    watcher.stop()


def test_stop_is_idempotent(qtbot, repo_path):
    watcher = RepositoryWatcher(str(repo_path / ".git"))
    watcher.start()
    watcher.stop()
    watcher.stop()  # ne doit pas lever
    assert not watcher.is_watching()


def test_missing_git_directory_does_not_crash(qtbot, tmp_path):
    watcher = RepositoryWatcher(str(tmp_path / "inexistant" / ".git"))
    watcher.start()  # ne doit pas lever
    watcher.stop()


def test_suspension_covers_events_arriving_after_the_block(qtbot, repo_path):
    """Les événements du système de fichiers arrivent APRÈS la sortie du bloc.

    Mesuré : sans période de grâce, une opération interne provoquait une
    notification parasite, car le drapeau était déjà levé quand les
    événements parvenaient à Qt. Le test qui attend À L'INTÉRIEUR du bloc
    ne voit pas ce défaut.
    """
    watcher = RepositoryWatcher(str(repo_path / ".git"), debounce_ms=50)
    watcher.start()

    calls = []
    watcher.graph_changed.connect(lambda: calls.append(1))

    with watcher.suspended():
        (repo_path / "f.txt").write_text("interne\n")
        run_git(repo_path, "add", "f.txt")
        run_git(repo_path, "commit", "-q", "-m", "interne")
    # on sort du bloc IMMÉDIATEMENT, puis on attend

    qtbot.wait(500)
    watcher.stop()

    assert calls == [], f"{len(calls)} notification(s) parasite(s)"


def test_external_change_is_still_detected_after_a_suspension(qtbot, repo_path):
    """La grâce ne doit pas rendre le watcher sourd durablement."""
    watcher = RepositoryWatcher(str(repo_path / ".git"), debounce_ms=50)
    watcher.start()

    with watcher.suspended():
        (repo_path / "f.txt").write_text("interne\n")
        run_git(repo_path, "add", "f.txt")
        run_git(repo_path, "commit", "-q", "-m", "interne")

    qtbot.wait(1500)  # laisser la grâce expirer

    with qtbot.waitSignal(watcher.graph_changed, timeout=3000):
        (repo_path / "f.txt").write_text("externe\n")
        run_git(repo_path, "add", "f.txt")
        run_git(repo_path, "commit", "-q", "-m", "externe")

    watcher.stop()
