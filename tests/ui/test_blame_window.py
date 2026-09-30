import os
import subprocess

import pygit2
import pytest

from tortoisepy.ui.blame_window import BlameWindow


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
    path = tmp_path / "d"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "f.txt").write_text("A\nB\nC\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "premier jet")
    (path / "f.txt").write_text("A\nB par Bob\nC\n")
    run_git(path, "commit", "-q", "-am", "Bob modifie B", auteur="Bob")
    return pygit2.Repository(str(path))


def test_the_window_lists_every_line(qtbot, repo):
    fenetre = BlameWindow(repo, "f.txt", str(repo.head.target))
    qtbot.addWidget(fenetre)
    assert fenetre.line_count() == 3


def test_each_row_shows_its_author(qtbot, repo):
    fenetre = BlameWindow(repo, "f.txt", str(repo.head.target))
    qtbot.addWidget(fenetre)
    assert fenetre.author_at(1) == "Alice"
    assert fenetre.author_at(2) == "Bob"


def test_clicking_a_line_emits_its_commit(qtbot, repo):
    """D28 : « qui » puis « pourquoi »."""
    fenetre = BlameWindow(repo, "f.txt", str(repo.head.target))
    qtbot.addWidget(fenetre)

    with qtbot.waitSignal(fenetre.commit_activated, timeout=1000) as bloqueur:
        fenetre.activate_line(2)

    assert bloqueur.args[0] == fenetre.oid_at(2)


def test_a_binary_file_says_so_instead_of_showing_bytes(qtbot, repo):
    chemin = os.path.join(repo.workdir, "bin.dat")
    with open(chemin, "wb") as fichier:
        fichier.write(b"\xff\xfe\x00binaire\n")
    run_git(repo.workdir, "add", "bin.dat")
    run_git(repo.workdir, "commit", "-q", "-m", "binaire")

    fresh = pygit2.Repository(repo.path)
    fenetre = BlameWindow(fresh, "bin.dat", str(fresh.head.target))
    qtbot.addWidget(fenetre)

    assert fenetre.line_count() == 0
    assert "binary" in fenetre.message().lower()


def test_a_missing_file_says_why(qtbot, repo):
    fenetre = BlameWindow(repo, "fantome.txt", str(repo.head.target))
    qtbot.addWidget(fenetre)
    assert fenetre.line_count() == 0
    assert "fantome.txt" in fenetre.message()


def test_the_title_names_the_file_and_the_commit(qtbot, repo):
    fenetre = BlameWindow(repo, "f.txt", str(repo.head.target))
    qtbot.addWidget(fenetre)
    assert "f.txt" in fenetre.windowTitle()
    assert str(repo.head.target)[:8] in fenetre.windowTitle()


def test_an_out_of_range_line_is_harmless(qtbot, repo):
    """Trouvé par sonde : `activate_line` plantait sur un `NoneType`.

    `_item_at` rend `None` hors bornes, et les accesseurs le
    déréférençaient. Une liste vide — fichier binaire ou absent — suffit
    à provoquer le cas.
    """
    fenetre = BlameWindow(repo, "f.txt", str(repo.head.target))
    qtbot.addWidget(fenetre)

    for numero in (0, -1, 99):
        fenetre.activate_line(numero)  # ne doit pas lever
        assert fenetre.author_at(numero) == ""
        assert fenetre.oid_at(numero) == ""


def test_activating_a_line_of_an_unblamable_file_is_harmless(qtbot, repo):
    """La liste est vide : activer quoi que ce soit ne doit rien faire."""
    fenetre = BlameWindow(repo, "fantome.txt", str(repo.head.target))
    qtbot.addWidget(fenetre)

    recus = []
    fenetre.commit_activated.connect(recus.append)
    fenetre.activate_line(1)

    assert recus == []


def test_an_empty_file_says_why_it_is_empty(qtbot, repo):
    """Revue finale : la fenêtre s'ouvrait vide et muette.

    `blame_file` rend `()` pour un fichier vide — ce qui est juste — mais
    seule la branche `BlameError` affichait un message. Six fichiers de ce
    dépôt sont dans ce cas : la fenêtre paraissait cassée.
    """
    import os

    chemin = os.path.join(repo.workdir, "vide.txt")
    open(chemin, "w").close()
    run_git(repo.workdir, "add", "vide.txt")
    run_git(repo.workdir, "commit", "-q", "-m", "vide")

    fresh = pygit2.Repository(repo.path)
    fenetre = BlameWindow(fresh, "vide.txt", str(fresh.head.target))
    qtbot.addWidget(fenetre)

    assert fenetre.line_count() == 0
    assert fenetre.message(), "la fenêtre doit dire pourquoi elle est vide"


def test_the_tints_follow_the_theme(qtbot, repo):
    """Revue finale : teintes claires en dur -> 1,02:1 en thème sombre.

    Le même défaut avait déjà été signalé par l'utilisateur sur l'aperçu
    des conflits ; `theme.is_dark_theme()` existe pour cela.
    """
    from tortoisepy.ui import blame_window as module

    clair = module._TINTS_CLAIR
    sombre = module._TINTS_SOMBRE
    assert clair != sombre

    # Un fond sombre doit l'être vraiment, sinon le texte clair disparaît.
    assert all(c.lightness() < 90 for c in sombre), sombre
    assert all(c.lightness() > 200 for c in clair), clair
