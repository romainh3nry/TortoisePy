"""Les écritures aussi passent en arrière-plan, avec le loader.

Demandé par l'utilisateur : « sur un gros repo, le checkout peut prendre
quelques secondes ».

**La décision D61 de la phase 24 disait l'inverse**, sur deux arguments
tous deux mauvais :

  - « deux écritures concurrentes » — FAUX : `run_in_background` refuse
    déjà une seconde opération tant que la première tourne, et ce verrou
    ne distingue pas lecture et écriture ;
  - « elles sont par ailleurs rapides » — JAMAIS MESURÉ.

Deux précautions que les lectures n'exigeaient pas :

  - les actions sont DÉSACTIVÉES pendant l'écriture — lancer un commit
    pendant qu'un checkout change de branche produirait un résultat
    imprévisible ;
  - aucun rafraîchissement avant la fin — le graphe lu à mi-checkout
    montrerait un état transitoire.
"""

from __future__ import annotations

import subprocess

import pygit2
import pytest

from tortoisepy.core.model import DisplayNode, NodeKind, Ref, RefType
from tortoisepy.ui.main_window import MainWindow


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
    """`main` (courante) et `autre`, sur deux commits distincts."""
    w = tmp_path / "w"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "a.txt").write_text("a\n")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "base")
    _git(w, "checkout", "-q", "-b", "autre")
    (w / "b.txt").write_text("b\n")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "sur autre")
    _git(w, "checkout", "-q", "main")

    fenetre = MainWindow(pygit2.Repository(str(w)))
    qtbot.addWidget(fenetre)
    fenetre.show()
    return fenetre


def _noeud(fenetre, branche: str) -> DisplayNode:
    oid = str(fenetre.repository.branches.local[branche].target)
    return DisplayNode(
        oid=oid,
        kind=NodeKind.REF,
        refs=(Ref(branche, RefType.LOCAL_BRANCH, oid),),
    )


def test_a_checkout_does_not_block_the_interface(qtbot, fenetre):
    """L'assertion centrale : la main est rendue aussitôt."""
    fenetre._run_action("checkout_branch", _noeud(fenetre, "autre"), "autre")

    # L'appel est revenu sans attendre la fin de l'écriture.
    assert fenetre.progress.isVisible(), "aucun indicateur de chargement"

    qtbot.waitUntil(
        lambda: fenetre.repository.head.shorthand == "autre", timeout=5000
    )


def test_the_actions_are_disabled_during_a_write(qtbot, fenetre):
    """Une écriture ne laisse PAS l'interface utilisable.

    C'est la différence avec une lecture : lancer un commit pendant qu'un
    checkout change de branche sous nos pieds produirait un résultat
    imprévisible.
    """
    fenetre._run_action("checkout_branch", _noeud(fenetre, "autre"), "autre")

    assert not fenetre.view.isEnabled(), (
        "le graphe reste cliquable pendant une écriture"
    )

    qtbot.waitUntil(lambda: fenetre.view.isEnabled(), timeout=5000)


def test_the_interface_comes_back_afterwards(qtbot, fenetre):
    """Le verrou doit se relâcher, sinon l'app reste figée."""
    fenetre._run_action("checkout_branch", _noeud(fenetre, "autre"), "autre")
    qtbot.waitUntil(lambda: fenetre.view.isEnabled(), timeout=5000)

    assert not fenetre.progress.isVisible()
    assert fenetre.repository.head.shorthand == "autre"


def test_the_interface_comes_back_on_failure(qtbot, fenetre, monkeypatch):
    """Surtout en cas d'échec : sinon l'app reste figée pour de bon."""
    from tortoisepy.ui import main_window as module

    monkeypatch.setattr(module, "show_error", lambda *a, **k: None)

    def casse(*a, **k):
        raise RuntimeError("écriture impossible")

    monkeypatch.setattr(module.actions, "execute_action", casse)
    fenetre._run_action("checkout_branch", _noeud(fenetre, "autre"), "autre")

    qtbot.waitUntil(lambda: fenetre.view.isEnabled(), timeout=5000)
    assert not fenetre.progress.isVisible()


def test_the_graph_refreshes_only_once_finished(qtbot, fenetre):
    """Rafraîchir à mi-checkout montrerait un état transitoire."""
    rafraichissements = []
    vrai = fenetre.refresh
    fenetre.refresh = lambda: (rafraichissements.append(
        fenetre.repository.head.shorthand), vrai())[1]

    fenetre._run_action("checkout_branch", _noeud(fenetre, "autre"), "autre")
    qtbot.waitUntil(lambda: bool(rafraichissements), timeout=5000)

    assert rafraichissements[0] == "autre", (
        f"rafraîchi alors que HEAD valait encore {rafraichissements[0]!r}"
    )


def test_a_second_action_is_refused_while_writing(qtbot, fenetre):
    """Deux écritures concurrentes resteraient interdites."""
    fenetre._run_action("checkout_branch", _noeud(fenetre, "autre"), "autre")
    avant = fenetre.repository.head.shorthand

    # Une seconde demande pendant l'écriture ne doit rien déclencher.
    fenetre._run_action("checkout_branch", _noeud(fenetre, "main"), "main")

    qtbot.waitUntil(lambda: fenetre.view.isEnabled(), timeout=5000)
    qtbot.waitUntil(
        lambda: fenetre.repository.head.shorthand == "autre", timeout=5000
    )
    assert fenetre.repository.head.shorthand == "autre", (
        "la seconde action a été exécutée malgré le verrou"
    )
