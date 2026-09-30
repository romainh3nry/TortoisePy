import os
import subprocess

import pygit2
import pytest

from tortoisepy.core.blame import BlameError, blame_file


def run_git(path, *args, auteur="Alice"):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": auteur, "GIT_AUTHOR_EMAIL": f"{auteur}@x",
        "GIT_COMMITTER_NAME": auteur, "GIT_COMMITTER_EMAIL": f"{auteur}@x",
    }
    return subprocess.run(
        ["git", *args], cwd=path, env=env, capture_output=True, text=True
    )


@pytest.fixture
def repo(tmp_path):
    """Trois lignes d'Alice, dont une réécrite par Bob."""
    path = tmp_path / "d"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "f.txt").write_text("A\nB\nC\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "premier jet")

    (path / "f.txt").write_text("A\nB par Bob\nC\n")
    run_git(path, "commit", "-q", "-am", "Bob modifie B", auteur="Bob")
    return pygit2.Repository(str(path))


def _tete(repo):
    return str(repo.head.target)


def test_each_line_is_attributed_to_its_author(repo):
    """Spec §5 : l'auteur, pas le committer."""
    lignes = blame_file(repo, "f.txt", _tete(repo))
    assert not isinstance(lignes, BlameError)
    assert [l.author for l in lignes] == ["Alice", "Bob", "Alice"]
    assert [l.text for l in lignes] == ["A", "B par Bob", "C"]
    assert [l.number for l in lignes] == [1, 2, 3]


def test_every_line_carries_its_commit(repo):
    lignes = blame_file(repo, "f.txt", _tete(repo))
    assert lignes[1].summary == "Bob modifie B"
    assert lignes[0].summary == "premier jet"
    assert len(lignes[1].short_oid) == 8
    assert lignes[1].oid != lignes[0].oid


def test_blaming_from_an_older_commit_ignores_later_changes(repo):
    """D29, et Review Focus 3 : sans `newest_commit`, on blâmerait HEAD."""
    ancien = [
        c
        for c in repo.walk(repo.head.target, pygit2.GIT_SORT_TOPOLOGICAL)
        if "premier jet" in c.message
    ][0]

    lignes = blame_file(repo, "f.txt", str(ancien.id))
    assert not isinstance(lignes, BlameError)
    assert [l.author for l in lignes] == ["Alice", "Alice", "Alice"]
    assert [l.text for l in lignes] == ["A", "B", "C"], (
        "le contenu doit venir de l'arbre du commit"
    )


def test_the_content_comes_from_the_tree_not_the_disk(repo):
    """Review Focus 1 : le disque peut porter des lignes non commitées."""
    chemin = os.path.join(repo.workdir, "f.txt")
    with open(chemin, "a") as fichier:
        fichier.write("D jamais commitee\n")

    lignes = blame_file(repo, "f.txt", _tete(repo))
    assert len(lignes) == 3, "la ligne non commitée ne doit pas apparaître"


def test_a_file_absent_from_the_commit_is_refused(repo):
    resultat = blame_file(repo, "fantome.txt", _tete(repo))
    assert isinstance(resultat, BlameError)
    assert "fantome.txt" in resultat.reason


def test_a_binary_file_is_refused_with_a_clear_reason(repo):
    """libgit2 ne lève pas : il rend un bloc unique et inutile."""
    chemin = os.path.join(repo.workdir, "bin.dat")
    with open(chemin, "wb") as fichier:
        fichier.write(b"\xff\xfe\x00binaire\n")
    run_git(repo.workdir, "add", "bin.dat")
    run_git(repo.workdir, "commit", "-q", "-m", "binaire")

    fresh = pygit2.Repository(repo.path)
    resultat = blame_file(fresh, "bin.dat", str(fresh.head.target))
    assert isinstance(resultat, BlameError)
    assert "binary" in resultat.reason.lower()


def test_an_empty_file_yields_no_lines(repo):
    chemin = os.path.join(repo.workdir, "vide.txt")
    open(chemin, "w").close()
    run_git(repo.workdir, "add", "vide.txt")
    run_git(repo.workdir, "commit", "-q", "-m", "vide")

    fresh = pygit2.Repository(repo.path)
    resultat = blame_file(fresh, "vide.txt", str(fresh.head.target))
    assert resultat == ()


def test_blaming_writes_nothing(repo):
    """§7.0."""
    import hashlib

    def empreinte():
        h = hashlib.sha256()
        for racine, _, fichiers in os.walk(os.path.join(repo.workdir, ".git")):
            for f in sorted(fichiers):
                p = os.path.join(racine, f)
                h.update(p.encode())
                try:
                    h.update(str(os.stat(p).st_mtime_ns).encode())
                except OSError:
                    pass
        return h.hexdigest()

    avant = empreinte()
    blame_file(repo, "f.txt", _tete(repo))
    assert empreinte() == avant


def test_lines_are_split_like_git_not_like_python(repo):
    """Revue finale, Critical : `splitlines()` décalait l'attribution.

    Python coupe aussi sur `\\x0c`, `\\x0b`, `\\x85`, `\\u2028`… que git ne
    traite pas comme des fins de ligne. Le vecteur de lignes comptait
    alors plus d'entrées que les hunks n'en couvrent, et **chaque ligne
    prenait l'auteur de la précédente** — le texte d'Alice affiché comme
    celui de Bob, et inversement. Reproduit avant correction.
    """
    chemin = os.path.join(repo.workdir, "ff.txt")
    with open(chemin, "w") as fichier:
        fichier.write("entete\x0csuite\nligne2\nligne3\n")
    run_git(repo.workdir, "add", "ff.txt")
    run_git(repo.workdir, "commit", "-q", "-m", "avec saut de page")

    fresh = pygit2.Repository(repo.path)
    lignes = blame_file(fresh, "ff.txt", str(fresh.head.target))

    assert len(lignes) == 3, "le saut de page ne termine pas une ligne"
    assert lignes[0].text == "entete\x0csuite"
    assert all(l.author for l in lignes), "aucune ligne sans auteur"


def test_crlf_endings_do_not_leak_into_the_text(repo):
    chemin = os.path.join(repo.workdir, "crlf.txt")
    with open(chemin, "wb") as fichier:
        fichier.write(b"un\r\ndeux\r\n")
    run_git(repo.workdir, "add", "crlf.txt")
    run_git(repo.workdir, "commit", "-q", "-m", "crlf")

    fresh = pygit2.Repository(repo.path)
    lignes = blame_file(fresh, "crlf.txt", str(fresh.head.target))
    assert [l.text for l in lignes] == ["un", "deux"]


def test_a_file_without_a_trailing_newline(repo):
    chemin = os.path.join(repo.workdir, "sansfin.txt")
    with open(chemin, "w") as fichier:
        fichier.write("un\ndeux")
    run_git(repo.workdir, "add", "sansfin.txt")
    run_git(repo.workdir, "commit", "-q", "-m", "sans fin")

    fresh = pygit2.Repository(repo.path)
    lignes = blame_file(fresh, "sansfin.txt", str(fresh.head.target))
    assert [l.text for l in lignes] == ["un", "deux"]
