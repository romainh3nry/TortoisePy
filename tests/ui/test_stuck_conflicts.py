"""Ne jamais rester bloqué par un conflit.

Signalé par l'utilisateur, capture à l'appui : sur un dépôt avec des
conflits, le menu ne proposait **ni « Abort » ni « Resolve conflicts… »**,
et le checkout échouait avec « unresolved conflicts exist in the index ».
Aucune sortie depuis l'application.

Cause mesurée : les deux entrées étaient conditionnées à `busy`,
c'est-à-dire `operation_in_progress is not None`. Or un index peut porter
des conflits SANS opération en cours :

    apres merge conflictuel : has_conflicts=True  operation='merge'
    si .git/MERGE_HEAD disparait : has_conflicts=True  operation=None

Ce second état survient après une fermeture brutale, un `state_cleanup`
partiel, ou une manipulation extérieure. Les conflits restent dans
l'index, et plus rien ne permet de s'en sortir.
"""

from __future__ import annotations

from tortoisepy.core.model import DisplayNode, NodeKind, Ref, RefType
from tortoisepy.core.state import RepositoryState
from tortoisepy.ui.context_menu import build_menu_model


def _etat(*, conflits: bool, operation: str | None) -> RepositoryState:
    return RepositoryState(
        head_oid="a" * 40,
        head_branch="main",
        detached=False,
        has_unstaged_changes=False,
        has_staged_changes=False,
        has_conflicts=conflits,
        operation_in_progress=operation,
        conflicted_paths=("f.txt",) if conflits else (),
    )


def _noeud() -> DisplayNode:
    return DisplayNode(
        oid="a" * 40,
        kind=NodeKind.REF,
        refs=(Ref("main", RefType.LOCAL_BRANCH, "a" * 40),),
    )


def _actions(entrees) -> set[str]:
    """Toutes les actions du menu, sous-menus compris."""
    trouvees: set[str] = set()
    for entree in entrees:
        if entree.action:
            trouvees.add(entree.action)
        if entree.children:
            trouvees |= _actions(entree.children)
    return trouvees


def test_conflicts_with_an_operation_offer_a_way_out():
    """Le cas déjà couvert : rien ne doit régresser."""
    menu = build_menu_model(
        (_noeud(),), _etat(conflits=True, operation="merge")
    )
    actions = _actions(menu)
    assert "abort_operation" in actions
    assert "open_conflicts" in actions


def test_conflicts_without_an_operation_still_offer_a_way_out():
    """Le bug signalé : plus aucune sortie depuis l'application.

    C'est l'assertion centrale. Sans elle, l'utilisateur dont l'index
    porte des conflits sans opération en cours reste bloqué : le checkout
    échoue, et le menu ne propose rien pour y remédier.
    """
    menu = build_menu_model(
        (_noeud(),), _etat(conflits=True, operation=None)
    )
    actions = _actions(menu)

    assert "open_conflicts" in actions, (
        "sans cette entrée, les conflits sont invisibles et irrésolubles"
    )
    assert "abort_operation" in actions, (
        "sans cette entrée, aucun moyen de revenir à l'état d'avant"
    )


def test_the_abort_entry_is_named_for_conflicts_alone():
    """« Abort None » serait du charabia.

    Le libellé reprend l'opération quand il y en a une, et parle des
    conflits sinon.
    """
    menu = build_menu_model(
        (_noeud(),), _etat(conflits=True, operation=None)
    )
    libelles = [
        e.label for e in menu if e.action == "abort_operation"
    ]
    assert libelles, "entrée absente"
    assert "None" not in libelles[0], libelles[0]
    assert "conflict" in libelles[0].lower(), libelles[0]


def test_a_clean_repository_offers_neither():
    """Sans conflit ni opération, ces entrées n'ont rien à faire là."""
    menu = build_menu_model(
        (_noeud(),), _etat(conflits=False, operation=None)
    )
    actions = _actions(menu)
    assert "abort_operation" not in actions
    assert "open_conflicts" not in actions


# --- L'abandon est destructeur : il doit être confirmé -------------------


def test_aborting_asks_for_confirmation():
    """`abort_operation` fait un `reset --hard` : rien ne doit partir
    sans accord.

    C'est le piège de la phase 11 : le menu posait `needs_confirmation`,
    mais `confirmation_for` n'avait pas de branche — le drapeau ne
    protégeait rien, et le travail était détruit malgré un refus.
    """
    from tortoisepy.ui.dialogs import confirmation_for

    for operation in ("merge", None):
        demande = confirmation_for(
            "abort_operation", "conflits",
            _etat(conflits=True, operation=operation),
        )
        assert demande is not None, (
            f"aucune confirmation avec operation={operation!r}"
        )
        assert demande.destructive is True


def test_the_confirmation_says_what_is_lost():
    """« Confirmer ? » sans contexte ne permet pas de décider."""
    from tortoisepy.ui.dialogs import confirmation_for

    demande = confirmation_for(
        "abort_operation", "conflits", _etat(conflits=True, operation=None)
    )
    texte = (demande.title + " " + demande.message).lower()
    assert "conflict" in texte or "conflit" in texte, demande.message
