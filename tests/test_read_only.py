"""Garantie de lecture seule.

Ouvrir, afficher, naviguer et rafraîchir ne doivent RIEN écrire dans le
dépôt. Seule une action explicite de l'utilisateur dans l'interface a le
droit de modifier quoi que ce soit.

Ces tests prennent une empreinte de `.git` (chemins, tailles, dates de
modification à la nanoseconde) avant et après chaque opération. Toute
écriture, même dans l'index ou le reflog, la fait changer.
"""

import hashlib
import os
import subprocess
from pathlib import Path

import pygit2
import pytest

from tortoisepy.core.commits import commits_for_node
from tortoisepy.core.graph import build_graph
from tortoisepy.core.state import read_state


def run_git(path, *args):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
    }
    return subprocess.run(
        ["git", *args], cwd=path, env=env, capture_output=True, text=True
    )


def fingerprint(git_dir: Path) -> str:
    """Empreinte de tout le contenu de `.git`."""
    digest = hashlib.sha256()
    for path in sorted(git_dir.rglob("*")):
        if path.is_file():
            stat = path.stat()
            digest.update(f"{path}:{stat.st_mtime_ns}:{stat.st_size}".encode())
    return digest.hexdigest()


@pytest.fixture
def repo_path(tmp_path):
    """Dépôt avec branches, tag, stash et modification non indexée.

    Un dépôt trivial ne prouverait rien : il faut que les lectures aient
    vraiment du travail.
    """
    path = tmp_path / "readonly"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "master")

    for index in range(3):
        (path / f"f{index}.txt").write_text(f"contenu {index}\n")
        run_git(path, "add", ".")
        run_git(path, "commit", "-q", "-m", f"commit {index}")

    run_git(path, "branch", "feature")
    run_git(path, "tag", "v1.0")

    (path / "f0.txt").write_text("à stasher\n")
    run_git(path, "stash", "-q")

    # modification non indexée : status() a du travail
    (path / "f1.txt").write_text("modifié\n")
    return path


def assert_unchanged(repo_path: Path, action) -> None:
    git_dir = repo_path / ".git"
    before = fingerprint(git_dir)
    action(pygit2.Repository(str(repo_path)))
    assert fingerprint(git_dir) == before, "le dépôt a été modifié"


def test_opening_a_repository_writes_nothing(repo_path):
    assert_unchanged(repo_path, lambda repo: None)


def test_reading_state_writes_nothing(repo_path):
    """`status()` peut rafraîchir le cache de l'index selon les versions."""
    assert_unchanged(repo_path, read_state)


def test_building_the_graph_writes_nothing(repo_path):
    assert_unchanged(repo_path, build_graph)


def test_reading_commits_writes_nothing(repo_path):
    def action(repo):
        graph = build_graph(repo)
        for node in graph.nodes:
            commits_for_node(repo, graph, node.oid)

    assert_unchanged(repo_path, action)


def test_listing_references_writes_nothing(repo_path):
    assert_unchanged(repo_path, lambda repo: list(repo.references))


def test_repeated_reads_write_nothing(repo_path):
    """Une écriture paresseuse n'apparaîtrait qu'au bout de plusieurs lectures."""
    def action(repo):
        for _ in range(5):
            read_state(repo)
            build_graph(repo)

    assert_unchanged(repo_path, action)


def test_opening_the_window_writes_nothing(repo_path, qapp):
    """Le test de bout en bout : la fenêtre entière, y compris le watcher."""
    from tortoisepy.ui.main_window import MainWindow

    git_dir = repo_path / ".git"
    before = fingerprint(git_dir)

    repository = pygit2.Repository(str(repo_path))
    window = MainWindow(repository)
    window.show()
    window.refresh()

    graph = window.graph
    if graph is not None and graph.nodes:
        window._show_commits(graph.nodes[0].oid)

    window.close()

    assert fingerprint(git_dir) == before, (
        "ouvrir la fenêtre a modifié le dépôt"
    )
