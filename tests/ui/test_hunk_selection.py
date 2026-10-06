"""Choisir les blocs à commiter, sans perdre les cases par fichier.

Demandé par l'utilisateur : « on fait ça mais je veux quand même garder
les cases à cocher pour ajouter ou non un fichier au stage ».

Les deux niveaux coexistent donc :

  - la case **par fichier** décide s'il entre dans le commit ; elle garde
    le dernier mot, un fichier décoché n'est jamais commité ;
  - les cases **par hunk** affinent ce qui est pris dans ce fichier.

Tant qu'on ne touche pas aux hunks, tout est coché et le comportement est
identique à avant : le cas courant ne doit rien coûter de plus.
"""

from __future__ import annotations

import subprocess

import pygit2
import pytest

from tortoisepy.ui.commit_window import CommitWindow

ENV = {
    "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
    "PATH": "/usr/bin:/bin:/usr/local/bin",
}


def _git(chemin, *args, check=True):
    return subprocess.run(
        ["git", "-C", str(chemin), *args], check=check,
        capture_output=True, env=ENV, text=True,
    )


@pytest.fixture
def depot(tmp_path):
    """Un fichier modifié à deux endroits éloignés : deux hunks."""
    w = tmp_path / "w"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    cible = w / "module.py"
    cible.write_text("".join(f"ligne {i}\n" for i in range(1, 21)))
    _git(w, "add", ".")
    _git(w, "commit", "-qm", "base")

    lignes = cible.read_text().splitlines(keepends=True)
    lignes[2] = "TROIS MODIFIEE\n"
    lignes[17] = "DIX-HUIT MODIFIEE\n"
    cible.write_text("".join(lignes))

    return pygit2.Repository(str(w))


@pytest.fixture
def fenetre(qtbot, depot):
    f = CommitWindow(depot)
    qtbot.addWidget(f)
    f.set_message("un message")
    f.select_file("module.py")
    return f


# --- les hunks sont proposés ---------------------------------------------


def test_the_hunks_are_listed(fenetre):
    """Sélectionner un fichier doit montrer ses blocs."""
    assert fenetre.hunk_count() == 2


def test_every_hunk_starts_checked(fenetre):
    """Le cas courant ne doit rien coûter : tout est pris par défaut.

    Décocher d'office obligerait à cocher deux fois pour un commit
    ordinaire — exactement l'inverse du service rendu.
    """
    assert fenetre.checked_hunks("module.py") == (0, 1)


def test_a_file_without_hunks_shows_none(qtbot, tmp_path):
    """Un fichier non suivi n'a pas de version HEAD d'où partir.

    Il garde donc le tout-ou-rien, et sa liste de blocs reste vide
    plutôt que d'afficher un choix qui n'en est pas un.
    """
    w = tmp_path / "neuf"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "base.txt").write_text("a\n")
    _git(w, "add", ".")
    _git(w, "commit", "-qm", "base")
    (w / "nouveau.txt").write_text("neuf\n")

    f = CommitWindow(pygit2.Repository(str(w)))
    qtbot.addWidget(f)
    f.select_file("nouveau.txt")

    assert f.hunk_count() == 0


# --- décocher un hunk ----------------------------------------------------


def test_unchecking_a_hunk_is_remembered(fenetre):
    """Le choix doit survivre au changement de fichier et revenir."""
    fenetre.set_hunk_checked("module.py", 1, False)

    assert fenetre.checked_hunks("module.py") == (0,)


def test_the_choice_survives_switching_files(qtbot, depot):
    """Le piège : reconstruire la liste efface les choix.

    Revenir sur un fichier après en avoir consulté un autre ne doit pas
    tout recocher en silence — on commiterait ce qu'on croyait écarté.
    """
    (lambda p: open(p, "w").write("autre\n"))(depot.workdir + "autre.txt")
    _git(depot.workdir, "add", "autre.txt")
    _git(depot.workdir, "commit", "-qm", "ajoute autre")
    (lambda p: open(p, "w").write("AUTRE MODIFIE\n"))(
        depot.workdir + "autre.txt"
    )

    f = CommitWindow(depot)
    qtbot.addWidget(f)
    f.select_file("module.py")
    f.set_hunk_checked("module.py", 1, False)

    f.select_file("autre.txt")
    f.select_file("module.py")

    assert f.checked_hunks("module.py") == (0,), (
        "le choix a été perdu en changeant de fichier"
    )


def test_a_partial_file_is_flagged(fenetre):
    """Un fichier dont une partie seulement est prise doit se voir.

    Sans ce signe, on commite en croyant tout prendre — et la différence
    ne se découvre qu'après coup.
    """
    fenetre.set_hunk_checked("module.py", 1, False)

    assert fenetre.is_partial("module.py")


def test_a_fully_checked_file_is_not_flagged(fenetre):
    """Le signe ne doit apparaître que s'il y a vraiment une différence."""
    assert not fenetre.is_partial("module.py")


# --- ce qui part au commit ----------------------------------------------


def test_committing_sends_only_the_checked_hunks(qtbot, fenetre, depot):
    """L'assertion centrale : le commit ne porte que le bloc retenu."""
    fenetre.set_hunk_checked("module.py", 1, False)
    fenetre.commit()
    qtbot.waitUntil(
        lambda: fenetre._task is None or not fenetre._task.is_running(),
        timeout=5000,
    )

    commite = depot.revparse_single("HEAD").tree["module.py"]
    contenu = depot.get(commite.id).data.decode()
    assert "TROIS MODIFIEE" in contenu
    assert "DIX-HUIT MODIFIEE" not in contenu


def test_the_rest_stays_in_the_working_tree(qtbot, fenetre, depot):
    """Ce qui n'est pas commité reste disponible."""
    fenetre.set_hunk_checked("module.py", 1, False)
    fenetre.commit()
    qtbot.waitUntil(
        lambda: fenetre._task is None or not fenetre._task.is_running(),
        timeout=5000,
    )

    with open(depot.workdir + "module.py") as fichier:
        assert "DIX-HUIT MODIFIEE" in fichier.read()


def test_an_untouched_file_commits_whole(qtbot, fenetre, depot):
    """Sans toucher aux hunks, le commit est celui d'avant.

    Le piège serait que la nouveauté change le cas courant.
    """
    fenetre.commit()
    qtbot.waitUntil(
        lambda: fenetre._task is None or not fenetre._task.is_running(),
        timeout=5000,
    )

    commite = depot.revparse_single("HEAD").tree["module.py"]
    contenu = depot.get(commite.id).data.decode()
    assert "TROIS MODIFIEE" in contenu
    assert "DIX-HUIT MODIFIEE" in contenu


def test_the_file_checkbox_still_wins(qtbot, fenetre, depot):
    """Demandé par l'utilisateur : la case par fichier garde le dernier mot.

    Décocher le fichier l'exclut du commit, quels que soient ses hunks.
    """
    fenetre.set_hunk_checked("module.py", 1, False)
    fenetre.set_checked("module.py", False)

    assert fenetre.checked_paths() == ()


def test_unchecking_every_hunk_excludes_the_file(qtbot, fenetre):
    """Ne retenir aucun bloc revient à ne rien commiter pour ce fichier.

    Le commiter quand même produirait un commit vide pour lui, sans que
    rien ne l'annonce.
    """
    fenetre.set_hunk_checked("module.py", 0, False)
    fenetre.set_hunk_checked("module.py", 1, False)

    assert "module.py" not in fenetre.checked_paths()
