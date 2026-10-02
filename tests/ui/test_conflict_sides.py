"""Dire à qui appartient chaque version dans un conflit.

Signalé par l'utilisateur, capture à l'appui : devant deux versions
concurrentes, rien ne disait laquelle était la sienne.

Pire, le code couleur **contredisait** le sens habituel :

    <<<<<<< HEAD
    +v12.11.12-RC3      <- vert, comme un ajout
    =======
    -v20.20.20          <- rouge, comme une suppression
    >>>>>>> 4424f94... TEST

Aucune des deux n'est ajoutée ni supprimée : ce sont deux versions
concurrentes de la même ligne. Le vert et le rouge voulaient dire
« la tienne » et « la leur », convention que rien n'annonçait.

Git fournit pourtant les noms — vérifié : `HEAD` donne la branche
courante, `MERGE_MSG` nomme celle qu'on fusionne.
"""

from __future__ import annotations

import subprocess

import pygit2
import pytest

from tortoisepy.ui.conflict_window import ConflictWindow


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
def depot_en_conflit(tmp_path):
    """`main` et `TEST` modifient la même ligne."""
    w = tmp_path / "w"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "version.txt").write_text("v1.0.0\n")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "base")
    _git(w, "checkout", "-q", "-b", "TEST")
    (w / "version.txt").write_text("v20.20.20\n")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "cote TEST")
    _git(w, "checkout", "-q", "main")
    (w / "version.txt").write_text("v12.11.12-RC3\n")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "cote main")
    _git(w, "merge", "TEST")
    return w


def _lignes(fenetre) -> list[str]:
    """Le texte des lignes affichées dans la zone de diff."""
    from tortoisepy.ui.conflict_window import _conflict_preview

    diff = _conflict_preview(fenetre.repository, "version.txt")
    return [ligne.content for hunk in diff.hunks for ligne in hunk.lines]


def test_each_side_is_named(qtbot, depot_en_conflit):
    """L'assertion centrale : savoir à qui appartient quoi.

    « HEAD » ne dit pas quelle branche c'est, et « 4424f94… » encore
    moins.
    """
    fenetre = ConflictWindow(pygit2.Repository(str(depot_en_conflit)))
    qtbot.addWidget(fenetre)

    texte = "\n".join(_lignes(fenetre))
    assert "main" in texte, f"la branche courante n'est pas nommée :\n{texte}"
    assert "TEST" in texte, f"la branche fusionnée n'est pas nommée :\n{texte}"


def test_the_sides_are_labelled_yours_and_theirs(qtbot, depot_en_conflit):
    """Les mots que portent les boutons, pour qu'on fasse le lien."""
    fenetre = ConflictWindow(pygit2.Repository(str(depot_en_conflit)))
    qtbot.addWidget(fenetre)

    texte = "\n".join(_lignes(fenetre)).lower()
    assert "yours" in texte, texte
    assert "theirs" in texte, texte


def test_the_raw_markers_are_gone(qtbot, depot_en_conflit):
    """`<<<<<<<` et `=======` n'apprennent rien à qui ne les connaît pas."""
    fenetre = ConflictWindow(pygit2.Repository(str(depot_en_conflit)))
    qtbot.addWidget(fenetre)

    texte = "\n".join(_lignes(fenetre))
    assert "<<<<<<<" not in texte, texte
    assert "=======" not in texte, texte
    assert ">>>>>>>" not in texte, texte


def test_both_versions_are_still_shown(qtbot, depot_en_conflit):
    """Remplacer les marqueurs ne doit rien cacher du contenu."""
    fenetre = ConflictWindow(pygit2.Repository(str(depot_en_conflit)))
    qtbot.addWidget(fenetre)

    texte = "\n".join(_lignes(fenetre))
    assert "v12.11.12-RC3" in texte
    assert "v20.20.20" in texte


def test_a_file_without_markers_is_shown_as_is(qtbot, tmp_path):
    """Un conflit « supprimé d'un côté » n'a aucun marqueur.

    Le fichier doit alors s'afficher tel quel, sans en-tête inventé.
    """
    w = tmp_path / "w"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "a.txt").write_text("ligne unique\n")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "base")

    from tortoisepy.ui.conflict_window import _conflict_preview

    diff = _conflict_preview(pygit2.Repository(str(w)), "a.txt")
    lignes = [l.content for h in diff.hunks for l in h.lines]
    assert lignes == ["ligne unique"], lignes
