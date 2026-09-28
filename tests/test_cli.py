import os
import subprocess

import pytest

from tortoisepy.cli import find_repository


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
    path = tmp_path / "cli"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "master")
    (path / "f.txt").write_text("base\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "base")
    return path


def test_finds_a_repository_at_its_root(repo_path):
    assert find_repository(str(repo_path)) is not None


def test_finds_a_repository_from_a_subdirectory(repo_path):
    """§8 : la commande marche depuis n'importe quel sous-dossier."""
    nested = repo_path / "src" / "deep"
    nested.mkdir(parents=True)
    assert find_repository(str(nested)) is not None


def test_returns_none_outside_a_repository(tmp_path):
    """Vérifié : discover_repository retourne None, elle ne lève pas."""
    outside = tmp_path / "rien"
    outside.mkdir()
    assert find_repository(str(outside)) is None


def test_returns_none_for_a_missing_path(tmp_path):
    assert find_repository(str(tmp_path / "inexistant")) is None


def test_finding_a_repository_writes_nothing(repo_path):
    """§7.0 : même la découverte ne touche pas au dépôt."""
    import hashlib

    def fingerprint():
        digest = hashlib.sha256()
        for path in sorted((repo_path / ".git").rglob("*")):
            if path.is_file():
                stat = path.stat()
                digest.update(f"{path}:{stat.st_mtime_ns}".encode())
        return digest.hexdigest()

    before = fingerprint()
    find_repository(str(repo_path))
    assert fingerprint() == before
