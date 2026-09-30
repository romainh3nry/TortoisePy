import os
import subprocess

import pygit2
import pytest

from tortoisepy.core.search import search_commits


def run_git(path, *args, auteur="Alice"):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": auteur, "GIT_AUTHOR_EMAIL": "a@a",
        "GIT_COMMITTER_NAME": auteur, "GIT_COMMITTER_EMAIL": "a@a",
    }
    return subprocess.run(
        ["git", *args], cwd=path, env=env, capture_output=True, text=True
    )


@pytest.fixture
def repo(tmp_path):
    """Trois commits, deux auteurs."""
    path = tmp_path / "d"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    for nom, message, auteur in (
        ("a.txt", "ajoute l'authentification", "Alice"),
        ("b.txt", "corrige le cache", "Bob"),
        ("c.txt", "AUTHENTIFICATION en majuscules", "Alice"),
    ):
        (path / nom).write_text("x\n")
        run_git(path, "add", ".", auteur=auteur)
        run_git(path, "commit", "-q", "-m", message, auteur=auteur)
    return pygit2.Repository(str(path))


def test_searching_by_message(repo):
    trouves = search_commits(repo, "cache")
    assert len(trouves) == 1
    assert "cache" in repo.get(trouves[0]).message


def test_searching_ignores_case(repo):
    """« authentification » doit trouver aussi la version en majuscules."""
    assert len(search_commits(repo, "authentification")) == 2


def test_searching_by_author(repo):
    assert len(search_commits(repo, "bob")) == 1
    assert len(search_commits(repo, "alice")) == 2


def test_searching_by_sha_prefix(repo):
    cible = str(repo.head.target)
    assert search_commits(repo, cible[:8]) == (cible,)


def test_an_empty_pattern_finds_nothing(repo):
    """Un motif vide efface le surlignage : il ne surligne pas tout."""
    assert search_commits(repo, "") == ()
    assert search_commits(repo, "   ") == ()


def test_an_unknown_pattern_finds_nothing(repo):
    assert search_commits(repo, "nimportequoi") == ()


def test_results_come_newest_first(repo):
    """L'ordre du graphe : le plus récent en tête."""
    trouves = search_commits(repo, "alice")
    messages = [repo.get(o).message.strip() for o in trouves]
    assert messages[0].startswith("AUTHENTIFICATION")


def test_searching_covers_commits_behind_nodes(tmp_path):
    """Review Focus 2 : le piège de la phase.

    Mesuré : 3 000 commits se réduisent à 10 nœuds. Une recherche qui
    n'examinerait que les nœuds raterait 99,7 % des commits.
    """
    path = tmp_path / "chaine"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    for i in range(30):
        (path / "f.txt").write_text(f"{i}\n")
        run_git(path, "add", ".")
        run_git(path, "commit", "-q", "-m", f"etape {i}")

    repo = pygit2.Repository(str(path))
    from tortoisepy.core.graph import build_graph

    assert len(build_graph(repo).nodes) < 5, "le graphe compresse bien"
    assert len(search_commits(repo, "etape")) == 30, (
        "la recherche doit voir les commits, pas seulement les nœuds"
    )


def test_searching_an_empty_repository(tmp_path):
    path = tmp_path / "vide"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    assert search_commits(pygit2.Repository(str(path)), "x") == ()
