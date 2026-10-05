"""Un loader pendant le commit et le commit + push.

Demandé par l'utilisateur : « quand je valide le commit ou commit + push,
il faut aussi mettre un loader le temps qu'il le fasse ».

Le push traverse le réseau — plusieurs secondes selon le dépôt et la
liaison — et le commit lui-même écrit l'index et l'arbre. Sans retour
visuel, la fenêtre paraît figée.

Les boutons sont DÉSACTIVÉS pendant l'opération : un second clic
lancerait un commit concurrent sur le même index.
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
    w = tmp_path / "w"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "a.txt").write_text("origine\n")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "base")
    (w / "a.txt").write_text("modifie\n")

    fenetre = CommitWindow(pygit2.Repository(str(w)))
    qtbot.addWidget(fenetre)
    fenetre.show()
    fenetre.set_message("un message")
    return fenetre


def test_the_window_has_a_progress_bar(fenetre):
    """Elle n'en avait aucune."""
    assert hasattr(fenetre, "progress")
    assert not fenetre.progress.isVisible(), "cachée au repos"


def test_committing_shows_the_loader(qtbot, fenetre, attendre_la_fenetre):
    """L'assertion centrale : un retour visuel pendant l'écriture.

    Observé DEPUIS LE FIL PRINCIPAL, après le retour de `commit()`.

    La version précédente interceptait `_write_commit` et relevait
    `isVisible()` depuis l'intérieur du travail : elle passait alors que
    tout tournait sur le fil principal, donc que Qt ne pouvait jamais
    peindre la barre et que la fenêtre gelait (signalé par
    l'utilisateur : « il n'y avait pas le loader »). Elle prouvait
    l'appel à `show()`, pas la visibilité.
    """
    fenetre.commit()

    assert fenetre.progress.isVisible(), (
        "le loader n'est pas visible après le retour de commit()"
    )
    attendre_la_fenetre(qtbot, fenetre)


def test_committing_does_not_block_the_interface(qtbot, fenetre, attendre_la_fenetre):
    """Le vrai défaut signalé : « pas de loader + processus en fond ».

    Le loader était posé, mais le commit tournait sur le fil principal :
    Qt n'avait pas la main pour le peindre, et la fenêtre restait figée
    jusqu'à la fin du push. On vérifie donc le fil, pas la barre.
    """
    import threading

    principal = threading.get_ident()
    fils = []
    vrai = fenetre._write_commit

    def observe(paths):
        fils.append(threading.get_ident())
        return vrai(paths)

    fenetre._write_commit = observe
    fenetre.commit()

    qtbot.waitUntil(lambda: bool(fils), timeout=5000)
    assert fils[0] != principal, "le commit gèle l'interface"
    attendre_la_fenetre(qtbot, fenetre)


def test_the_loader_disappears_afterwards(qtbot, fenetre):
    """Une barre qui resterait ferait croire à un travail en cours."""
    fenetre.commit()
    qtbot.waitUntil(lambda: not fenetre.progress.isVisible(), timeout=5000)


def test_the_buttons_are_disabled_during_the_commit(
    qtbot, fenetre, attendre_la_fenetre
):
    """Un second clic lancerait un commit concurrent sur le même index.

    Relevé depuis le fil principal : c'est là que l'utilisateur clique,
    et donc le seul endroit où la protection compte.
    """
    fenetre.commit()

    assert (
        fenetre.commit_button.isEnabled(),
        fenetre.push_button.isEnabled(),
    ) == (False, False), "les boutons restent actifs pendant le commit"

    attendre_la_fenetre(qtbot, fenetre)


def test_the_buttons_come_back_on_failure(qtbot, fenetre, monkeypatch):
    """Sinon la fenêtre reste inutilisable après une erreur."""
    from tortoisepy.ui import commit_window as module
    from tortoisepy.core.results import failed

    monkeypatch.setattr(module, "show_error", lambda *a, **k: None)
    fenetre._write_commit = lambda paths: failed("Commit", "échec simulé")

    fenetre.commit()

    qtbot.waitUntil(lambda: fenetre.commit_button.isEnabled(), timeout=5000)
    assert not fenetre.progress.isVisible()


def test_a_commit_still_creates_the_commit(qtbot, fenetre):
    """Le loader ne doit rien changer au résultat."""
    avant = str(fenetre.repository.head.target)
    fenetre.commit()

    qtbot.waitUntil(
        lambda: str(pygit2.Repository(fenetre.repository.path).head.target)
        != avant,
        timeout=5000,
    )
