"""`abort_operation` doit aussi sortir d'un index en conflit « orphelin ».

Un index peut porter des conflits sans opération en cours — vérifié, il
suffit que `.git/MERGE_HEAD` disparaisse (fermeture brutale, nettoyage
partiel). L'utilisateur est alors bloqué :

    checkout -> « unresolved conflicts exist in the index »
    abort_operation -> « no operation in progress »

Les deux refusent, et plus rien ne débloque la situation.
"""

from __future__ import annotations

import pathlib
import subprocess

import pygit2
import pytest

from tortoisepy.core.operations import abort_operation, checkout_branch
from tortoisepy.core.state import read_state


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
def depot_bloque(tmp_path):
    """Des conflits dans l'index, sans opération en cours."""
    w = tmp_path / "w"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "f.txt").write_text("base\n")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "base")
    _git(w, "checkout", "-q", "-b", "feature")
    (w / "f.txt").write_text("feature\n")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "cote feature")
    _git(w, "checkout", "-q", "main")
    (w / "f.txt").write_text("main\n")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "cote main")
    _git(w, "merge", "feature")

    # L'état se perd : les conflits restent, l'opération disparaît.
    (pathlib.Path(w) / ".git" / "MERGE_HEAD").unlink()
    return w


def test_the_repository_is_genuinely_stuck(depot_bloque):
    """La situation que l'utilisateur a rencontrée."""
    etat = read_state(pygit2.Repository(str(depot_bloque)))
    assert etat.has_conflicts
    assert etat.operation_in_progress is None

    echec = checkout_branch(pygit2.Repository(str(depot_bloque)), "feature")
    assert not echec.success, "le checkout devrait refuser"


def test_aborting_clears_orphan_conflicts(depot_bloque):
    """L'assertion centrale : il doit toujours exister une sortie."""
    resultat = abort_operation(pygit2.Repository(str(depot_bloque)))

    assert resultat.success, resultat.git_error
    etat = read_state(pygit2.Repository(str(depot_bloque)))
    assert not etat.has_conflicts, "les conflits survivent à l'abandon"


def test_the_branch_can_be_changed_afterwards(depot_bloque):
    """Le but réel : ne plus être bloqué."""
    abort_operation(pygit2.Repository(str(depot_bloque)))
    resultat = checkout_branch(
        pygit2.Repository(str(depot_bloque)), "feature"
    )
    assert resultat.success, resultat.git_error


def test_aborting_a_clean_repository_still_refuses(tmp_path):
    """Sans rien à abandonner, le refus reste la bonne réponse.

    Nettoyer un dépôt sain reviendrait à faire un `reset --hard` que
    personne n'a demandé — exactement ce qu'il ne faut pas.
    """
    w = tmp_path / "propre"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "a.txt").write_text("a")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "base")

    resultat = abort_operation(pygit2.Repository(str(w)))
    assert not resultat.success
    assert not resultat.repository_changed


def test_aborting_does_not_touch_uncommitted_work_elsewhere(depot_bloque):
    """Un fichier non suivi, étranger au conflit, doit survivre.

    L'abandon fait un `reset --hard` : il ne doit pas emporter ce que
    l'utilisateur n'a jamais mis dans le conflit.
    """
    temoin = pathlib.Path(depot_bloque) / "mes-notes.txt"
    temoin.write_text("travail en cours\n")

    abort_operation(pygit2.Repository(str(depot_bloque)))

    assert temoin.exists(), "un fichier non suivi a été supprimé"
    assert temoin.read_text() == "travail en cours\n"
