"""Aucun dialogue ne doit s'ouvrir depuis un fil de fond.

Signalé par l'utilisateur : « j'ai tenté de supprimer la branche CRM-3912
et l'app crash et se ferme ». Le crash est **sec** — pas de boîte
d'erreur, l'application disparaît — et il survient AVANT que la
confirmation s'affiche.

Cause : le passage des écritures en arrière-plan a emporté
`execute_action` dans le fil de fond, or celui-ci demande la confirmation
(`ctx.confirm`) et les saisies (`ctx.ask_name`, `ctx.ask_mode`). Qt
interdit de créer un widget hors du fil principal et abandonne le
processus :

    QObject::setParent: Cannot set parent, new parent is in a different thread

Cela touchait **toute** action interactive : supprimer une branche ou un
tag, en créer une, renommer, reset, stash.

Les essais de reproduction qui remplaçaient `confirm` par un double
masquaient le défaut : c'est la VRAIE boîte de dialogue qui plante, donc
ces tests vérifient le FIL d'exécution, jamais le résultat seul.
"""

from __future__ import annotations

import threading

import pygit2
import pytest

from tortoisepy.ui.actions import ActionContext, needs_interaction, prepare_action


@pytest.fixture
def depot(tmp_path):
    repo = pygit2.init_repository(str(tmp_path / "d"), initial_head="main")
    sig = pygit2.Signature("T", "t@e", 0, 0)
    builder = repo.TreeBuilder()
    builder.insert("a.txt", repo.create_blob(b"v1"), pygit2.GIT_FILEMODE_BLOB)
    oid = repo.create_commit(
        "refs/heads/main", sig, sig, "base", builder.write(), []
    )
    repo.create_branch("CRM-3912", repo.get(oid))
    return repo


@pytest.fixture
def fenetre(qtbot, depot):
    from tortoisepy.ui.main_window import MainWindow

    w = MainWindow(depot)
    qtbot.addWidget(w)
    return w


def _noeud(fenetre, branche: str):
    return next(
        n for n in fenetre.graph.nodes
        if any(r.name == branche for r in n.refs)
    )


# --- le crash signalé ----------------------------------------------------


def test_deleting_a_branch_confirms_on_the_main_thread(
    qtbot, fenetre, attendre_le_fond
):
    """L'assertion centrale : la confirmation ne doit pas quitter le fil.

    C'est le crash signalé par l'utilisateur. On relève le fil dans
    laquelle la boîte serait construite — pas le résultat, qui serait
    identique dans les deux cas tant que Qt ne décide pas d'abandonner.
    """
    principal = threading.get_ident()
    fils = []

    from tortoisepy.ui import main_window as module

    module.confirm = lambda *a, **k: (fils.append(threading.get_ident()), True)[1]
    try:
        fenetre._run_action("delete_branch", _noeud(fenetre, "CRM-3912"),
                            "CRM-3912")
        attendre_le_fond(qtbot, fenetre)
    finally:
        from tortoisepy.ui.dialogs import confirm as vrai
        module.confirm = vrai

    assert fils, "la confirmation n'a pas été demandée"
    assert fils[0] == principal, (
        "la confirmation s'ouvre dans un fil de fond : Qt abandonne le "
        "processus (« Cannot set parent, new parent is in a different "
        "thread »)"
    )


def test_the_branch_is_still_deleted(qtbot, fenetre, depot, attendre_le_fond):
    """Déplacer la confirmation ne doit rien changer au résultat."""
    from tortoisepy.ui import main_window as module

    module.confirm = lambda *a, **k: True
    try:
        fenetre._run_action("delete_branch", _noeud(fenetre, "CRM-3912"),
                            "CRM-3912")
        attendre_le_fond(qtbot, fenetre)
    finally:
        from tortoisepy.ui.dialogs import confirm as vrai
        module.confirm = vrai

    assert "CRM-3912" not in list(depot.branches.local)


def test_refusing_the_confirmation_deletes_nothing(
    qtbot, fenetre, depot, attendre_le_fond
):
    """Un refus doit rester un refus : c'est la porte de §6.4."""
    from tortoisepy.ui import main_window as module

    module.confirm = lambda *a, **k: False
    try:
        fenetre._run_action("delete_branch", _noeud(fenetre, "CRM-3912"),
                            "CRM-3912")
        attendre_le_fond(qtbot, fenetre)
    finally:
        from tortoisepy.ui.dialogs import confirm as vrai
        module.confirm = vrai

    assert "CRM-3912" in list(depot.branches.local), (
        "la branche a été supprimée malgré le refus"
    )


# --- les saisies, mêmes contraintes --------------------------------------


def test_creating_a_branch_asks_on_the_main_thread(
    qtbot, fenetre, attendre_le_fond
):
    """`ask_name` construit un `QInputDialog` : même interdit que `confirm`."""
    principal = threading.get_ident()
    fils = []

    from tortoisepy.ui import main_window as module

    module.ask_name = lambda *a, **k: (
        fils.append(threading.get_ident()), "nouvelle"
    )[1]
    try:
        fenetre._run_action("create_branch", _noeud(fenetre, "CRM-3912"))
        attendre_le_fond(qtbot, fenetre)
    finally:
        from tortoisepy.ui.dialogs import ask_name as vrai
        module.ask_name = vrai

    assert fils and fils[0] == principal, (
        f"la saisie s'ouvre hors du fil principal : {fils}"
    )


def test_cancelling_a_name_does_nothing(qtbot, fenetre, depot, attendre_le_fond):
    """Annuler la saisie ne doit rien écrire."""
    from tortoisepy.ui import main_window as module

    avant = set(depot.branches.local)
    module.ask_name = lambda *a, **k: None
    try:
        fenetre._run_action("create_branch", _noeud(fenetre, "CRM-3912"))
        attendre_le_fond(qtbot, fenetre)
    finally:
        from tortoisepy.ui.dialogs import ask_name as vrai
        module.ask_name = vrai

    assert set(depot.branches.local) == avant


# --- la règle, exprimée une fois pour toutes -----------------------------


def test_every_interactive_action_is_declared(depot):
    """Le garde-fou : toute action ouvrant un dialogue doit être déclarée.

    Sans cette liste, une action interactive ajoutée plus tard repartirait
    silencieusement dans le fil de fond — et crasherait l'application,
    exactement comme `delete_branch`.

    La liste est confrontée au CODE des gestionnaires : ce qui appelle
    `ctx.confirm`, `ctx.ask_name` ou `ctx.ask_mode` est interactif, qu'on
    l'ait déclaré ou non.
    """
    import inspect

    from tortoisepy.ui.actions import ACTION_HANDLERS

    interactifs = set()
    for nom, handler in ACTION_HANDLERS.items():
        try:
            source = inspect.getsource(handler)
        except (OSError, TypeError):
            continue
        if any(
            appel in source
            for appel in ("ctx.confirm", "ctx.ask_name", "ctx.ask_mode")
        ):
            interactifs.add(nom)

    manquants = {nom for nom in interactifs if not needs_interaction(nom)}
    assert not manquants, (
        f"actions ouvrant un dialogue mais non déclarées : {manquants} — "
        "elles s'exécuteraient dans un fil de fond et feraient planter Qt"
    )


def test_actions_needing_confirmation_are_declared():
    """Une action confirmée par `confirmation_for` est interactive aussi.

    La confirmation vit hors des gestionnaires, dans `execute_action` :
    une action peut donc être interactive sans qu'aucun `ctx.confirm`
    apparaisse dans son propre code.
    """
    from tortoisepy.core.state import RepositoryState
    from tortoisepy.ui.actions import ACTION_HANDLERS
    from tortoisepy.ui.dialogs import confirmation_for

    etat = RepositoryState(
        head_oid="a" * 40, head_branch="main", detached=False,
        has_unstaged_changes=False, has_staged_changes=False,
        has_conflicts=False, operation_in_progress=None, conflicted_paths=(),
    )

    for nom in ACTION_HANDLERS:
        mode = "hard" if nom == "reset_to" else None
        if confirmation_for(nom, "cible", etat, mode=mode) is not None:
            assert needs_interaction(nom), (
                f"« {nom} » demande une confirmation mais n'est pas "
                "déclarée interactive"
            )


def test_prepare_returns_none_when_cancelled(depot):
    """La phase d'interaction doit pouvoir annuler avant toute écriture."""
    from tortoisepy.core.state import read_state
    from tortoisepy.core.graph import build_graph

    graphe = build_graph(depot)
    noeud = next(
        n for n in graphe.nodes if any(r.name == "CRM-3912" for r in n.refs)
    )
    ctx = ActionContext(
        repository=depot,
        node=noeud,
        state=read_state(depot),
        confirm=lambda *a, **k: False,
        chosen_branch="CRM-3912",
    )

    assert prepare_action("delete_branch", ctx) is None
    assert "CRM-3912" in list(depot.branches.local)
