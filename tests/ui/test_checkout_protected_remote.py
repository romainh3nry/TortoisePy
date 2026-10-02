"""On peut se positionner sur `origin/develop`, même si on ne peut pas
la supprimer.

Signalé par l'utilisateur, capture à l'appui : « Switch / Checkout to
revision » restait grisé sur un nœud ne portant que `origin/develop`.

Cause : `_remote_branches` exclut `main`, `master` et `develop` — un
filtre écrit pour la SUPPRESSION de branches distantes (on ne supprime
pas `develop` du serveur). La phase 21 l'a réutilisé pour le checkout,
où il n'a aucun sens : se positionner sur `develop` est le cas le plus
courant.

Deux usages, deux listes : ce qu'on peut viser n'est pas ce qu'on peut
détruire.
"""

from __future__ import annotations

from tortoisepy.core.model import DisplayNode, NodeKind, Ref, RefType
from tortoisepy.core.state import RepositoryState
from tortoisepy.ui.context_menu import build_menu_model


def _noeud(*noms_et_types) -> DisplayNode:
    return DisplayNode(
        oid="a" * 40,
        kind=NodeKind.REF,
        refs=tuple(Ref(n, t, "a" * 40) for n, t in noms_et_types),
    )


def _etat(courante: str | None) -> RepositoryState:
    return RepositoryState(
        head_oid="b" * 40,
        head_branch=courante,
        detached=False,
        has_unstaged_changes=False,
        has_staged_changes=False,
        has_conflicts=False,
        operation_in_progress=None,
        conflicted_paths=(),
    )


def _entree(menu, action: str):
    """L'entrée portant `action`, où qu'elle soit dans l'arborescence.

    On descend dans les sous-menus : rendre le sous-menu parent mesurerait
    son état à lui, pas celui de l'action visée.
    """
    for e in menu:
        if e.action == action:
            return e
        if e.children:
            trouvee = _entree(e.children, action)
            if trouvee is not None:
                return trouvee
    return None


def test_a_protected_remote_branch_can_be_checked_out():
    """L'assertion centrale : c'est le cas que l'utilisateur a rencontré."""
    menu = build_menu_model(
        (_noeud(("origin/develop", RefType.REMOTE_BRANCH)),), _etat("main")
    )
    entree = _entree(menu, "checkout_branch")

    assert entree is not None, "l'entrée de checkout a disparu"
    assert entree.enabled, "« Switch / Checkout » est grisé sur origin/develop"


def test_main_and_master_too():
    """Le filtre les excluait toutes les trois."""
    for nom in ("origin/main", "origin/master", "origin/develop"):
        menu = build_menu_model(
            (_noeud((nom, RefType.REMOTE_BRANCH)),), _etat("autre")
        )
        entree = _entree(menu, "checkout_branch")
        assert entree is not None and entree.enabled, f"grisé sur {nom}"


def test_deleting_a_protected_remote_branch_stays_refused():
    """La protection garde son sens là où elle a été écrite.

    Supprimer `origin/develop` du serveur reste refusé — le cœur le
    refuserait de toute façon, et proposer une entrée vouée à l'échec
    n'apprend rien.
    """
    menu = build_menu_model(
        (_noeud(("origin/develop", RefType.REMOTE_BRANCH)),), _etat("main")
    )
    entree = _entree(menu, "delete_remote_branch")

    assert entree is None or not entree.enabled, (
        "la suppression d'une branche distante protégée devrait rester refusée"
    )


def test_an_ordinary_remote_branch_can_still_be_deleted():
    """La correction ne doit pas désactiver la suppression ailleurs."""
    menu = build_menu_model(
        (_noeud(("origin/fix-truc", RefType.REMOTE_BRANCH)),), _etat("main")
    )
    entree = _entree(menu, "delete_remote_branch")

    assert entree is not None and entree.enabled


def test_the_current_branch_is_not_proposed():
    """On ne bascule pas sur la branche où l'on est déjà."""
    menu = build_menu_model(
        (_noeud(("origin/develop", RefType.REMOTE_BRANCH)),),
        _etat("develop"),
    )
    entree = _entree(menu, "checkout_branch")

    assert entree is None or not entree.enabled, (
        "origin/develop ne doit pas être proposé quand on est sur develop"
    )


def test_origin_head_is_never_proposed():
    """`origin/HEAD` est un alias, pas une branche à viser."""
    menu = build_menu_model(
        (_noeud(("origin/HEAD", RefType.REMOTE_BRANCH)),), _etat("main")
    )
    entree = _entree(menu, "checkout_branch")

    assert entree is None or not entree.enabled
