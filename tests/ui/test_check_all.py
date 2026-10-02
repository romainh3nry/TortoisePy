"""Un bouton pour cocher tous les fichiers d'un coup.

Demandé par l'utilisateur après avoir constaté que les fichiers NON
SUIVIS arrivent décochés (décision D8) : ils sont souvent du bruit —
build, cache, `.env` — mais parfois le fichier qu'on vient d'écrire.

Le bouton doit respecter la garde existante : **un conflit non résolu ne
doit jamais être coché**, sous peine de produire un commit contenant des
marqueurs `<<<<<<<` (§4.1).
"""

from __future__ import annotations

import subprocess

import pygit2
import pytest

from tortoisepy.ui.commit_window import CommitWindow


def _git(chemin, *args):
    subprocess.run(
        ["git", "-C", str(chemin), *args], check=False, capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
            "PATH": "/usr/bin:/bin:/usr/local/bin",
        },
    )


@pytest.fixture
def fenetre(qtbot, tmp_path):
    """Un fichier modifié (coché) et deux non suivis (décochés)."""
    w = tmp_path / "w"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "suivi.txt").write_text("origine\n")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "base")

    (w / "suivi.txt").write_text("modifie\n")
    (w / "nouveau.txt").write_text("jamais commité\n")
    (w / "autre.txt").write_text("non suivi aussi\n")

    fenetre = CommitWindow(pygit2.Repository(str(w)))
    qtbot.addWidget(fenetre)
    return fenetre


def test_the_button_exists(fenetre):
    """Demandé par l'utilisateur."""
    assert hasattr(fenetre, "check_all_button")
    assert fenetre.check_all_button.isEnabled()


def test_untracked_files_start_unchecked(fenetre):
    """La règle D8, qui motive le bouton : rien n'est ajouté par accident."""
    assert fenetre.is_checked("suivi.txt"), "un fichier modifié est coché"
    assert not fenetre.is_checked("nouveau.txt")
    assert not fenetre.is_checked("autre.txt")


def test_the_button_checks_everything(fenetre):
    """L'assertion centrale : un geste au lieu de N clics."""
    fenetre.check_all_button.click()

    assert fenetre.is_checked("suivi.txt")
    assert fenetre.is_checked("nouveau.txt")
    assert fenetre.is_checked("autre.txt")
    assert len(fenetre.checked_paths()) == 3


def test_a_conflicted_file_is_never_checked(qtbot, tmp_path):
    """La garde de la phase 6 doit tenir : un conflit coché produirait un
    commit contenant des marqueurs `<<<<<<<`.

    C'est l'assertion qui compte — un bouton « tout cocher » est
    exactement le chemin par lequel cette garantie pourrait tomber.
    """
    w = tmp_path / "w"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "f.txt").write_text("base\n")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "base")
    _git(w, "checkout", "-q", "-b", "cote")
    (w / "f.txt").write_text("cote\n")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "cote")
    _git(w, "checkout", "-q", "main")
    (w / "f.txt").write_text("main\n")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "main")
    _git(w, "merge", "cote")

    fenetre = CommitWindow(pygit2.Repository(str(w)))
    qtbot.addWidget(fenetre)
    assert not fenetre.is_checkable("f.txt"), "le fichier devrait être en conflit"

    fenetre.check_all_button.click()

    assert not fenetre.is_checked("f.txt"), (
        "un conflit non résolu a été coché par « tout cocher »"
    )
    assert "f.txt" not in fenetre.checked_paths()


def test_clicking_twice_is_harmless(fenetre):
    """Idempotent : le bouton coche, il ne bascule pas."""
    fenetre.check_all_button.click()
    premier = fenetre.checked_paths()
    fenetre.check_all_button.click()
    assert fenetre.checked_paths() == premier


def test_an_empty_window_is_handled(qtbot, tmp_path):
    """Aucun fichier à cocher : pas de plantage."""
    w = tmp_path / "propre"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "a.txt").write_text("a\n")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "base")

    fenetre = CommitWindow(pygit2.Repository(str(w)))
    qtbot.addWidget(fenetre)
    fenetre.check_all_button.click()      # ne doit pas lever
    assert fenetre.checked_paths() == ()
