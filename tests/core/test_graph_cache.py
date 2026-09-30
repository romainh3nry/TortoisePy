import os
import subprocess

import pygit2
import pytest

from tortoisepy.core.graph_cache import GraphCache, repo_fingerprint


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
    path = tmp_path / "d"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "f.txt").write_text("a\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "base")
    return pygit2.Repository(str(path))


def test_an_unchanged_repository_is_not_rebuilt(repo):
    cache = GraphCache()
    appels = []
    build = lambda r: appels.append(1) or "GRAPHE"

    assert cache.get(repo, build) == "GRAPHE"
    assert cache.get(repo, build) == "GRAPHE"
    assert len(appels) == 1, "le second appel doit venir du cache"


def test_a_new_branch_invalidates_the_cache(repo):
    cache = GraphCache()
    appels = []
    build = lambda r: appels.append(1) or f"GRAPHE {len(appels)}"

    cache.get(repo, build)
    run_git(repo.workdir, "branch", "nouvelle")

    assert cache.get(pygit2.Repository(repo.path), build) == "GRAPHE 2"


def test_a_new_commit_invalidates_the_cache(repo):
    cache = GraphCache()
    appels = []
    build = lambda r: appels.append(1) or f"GRAPHE {len(appels)}"

    cache.get(repo, build)
    open(os.path.join(repo.workdir, "g.txt"), "w").write("g\n")
    run_git(repo.workdir, "add", ".")
    run_git(repo.workdir, "commit", "-q", "-m", "suivant")

    assert cache.get(pygit2.Repository(repo.path), build) == "GRAPHE 2"


def test_switching_head_invalidates_the_cache(repo):
    """Review Focus 5 : le nœud courant change l'affichage."""
    cache = GraphCache()
    appels = []
    build = lambda r: appels.append(1) or f"GRAPHE {len(appels)}"

    run_git(repo.workdir, "branch", "autre")
    cache.get(repo, build)
    run_git(repo.workdir, "checkout", "-q", "autre")

    assert cache.get(pygit2.Repository(repo.path), build) == "GRAPHE 2"


def test_an_operation_in_progress_invalidates_the_cache(repo):
    """Un merge en cours change ce que l'interface doit montrer."""
    cache = GraphCache()
    appels = []
    build = lambda r: appels.append(1) or f"GRAPHE {len(appels)}"

    run_git(repo.workdir, "checkout", "-q", "-b", "cote")
    open(os.path.join(repo.workdir, "f.txt"), "w").write("cote\n")
    run_git(repo.workdir, "commit", "-q", "-am", "cote")
    run_git(repo.workdir, "checkout", "-q", "main")
    open(os.path.join(repo.workdir, "f.txt"), "w").write("main\n")
    run_git(repo.workdir, "commit", "-q", "-am", "main")

    cache.get(pygit2.Repository(repo.path), build)
    run_git(repo.workdir, "merge", "cote")  # conflit -> état MERGE

    assert cache.get(pygit2.Repository(repo.path), build) == "GRAPHE 2"


def test_the_fingerprint_is_cheap(repo):
    """D24 tient sur cet écart : l'empreinte doit rester négligeable."""
    import time

    repo_fingerprint(repo)  # chauffe
    debut = time.perf_counter()
    for _ in range(50):
        repo_fingerprint(repo)
    moyenne = (time.perf_counter() - debut) / 50
    assert moyenne < 0.02, f"{moyenne * 1000:.1f} ms par empreinte"


def test_the_fingerprint_writes_nothing(repo):
    """§7.0 : lire les refs ne touche pas au dépôt."""
    import hashlib

    def empreinte_disque():
        h = hashlib.sha256()
        for racine, _, fichiers in os.walk(os.path.join(repo.workdir, ".git")):
            for f in sorted(fichiers):
                chemin = os.path.join(racine, f)
                h.update(chemin.encode())
                try:
                    h.update(str(os.stat(chemin).st_mtime_ns).encode())
                except OSError:
                    pass
        return h.hexdigest()

    avant = empreinte_disque()
    repo_fingerprint(repo)
    GraphCache().get(repo, lambda r: "X")
    assert empreinte_disque() == avant
