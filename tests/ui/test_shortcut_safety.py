"""§6.4 : un raccourci ne doit jamais contourner la confirmation.

La phase 11 a coûté cher : « Drop stash » portait `needs_confirmation`,
un test l'affirmait, et le stash était pourtant détruit même sur un refus
— parce que `confirmation_for` n'avait pas de branche `drop_stash`. Poser
un drapeau ne protège rien. Ces tests visent la vraie porte.
"""

from tortoisepy.core.shortcuts import CATALOGUE
from tortoisepy.core.state import RepositoryState
from tortoisepy.ui.dialogs import confirmation_for

DESTRUCTRICES = (
    "drop_stash",
    "delete_branch",
    "delete_remote_branch",
    "reset_to",
    "revert_commit",
)

_RECUPERABLES = ("cherry_pick", "merge_branch")
"""Récupérables : l'absence de confirmation y est correcte (mesuré)."""


def _etat_propre() -> RepositoryState:
    return RepositoryState(
        head_oid="a" * 40,
        head_branch="main",
        detached=False,
        has_unstaged_changes=False,
        has_staged_changes=False,
        has_conflicts=False,
        operation_in_progress=None,
        conflicted_paths=(),
    )


def test_no_destructive_action_is_reachable_by_shortcut():
    """Aucune action destructrice n'est dans le catalogue.

    C'est la garantie la plus simple et la plus solide : ce qui n'a pas de
    raccourci ne peut pas être déclenché par une frappe réflexe.
    """
    ids = {spec.action_id for spec in CATALOGUE}
    assert ids & set(DESTRUCTRICES) == set()


def test_every_destructive_action_still_has_its_confirmation():
    """La porte reste fermée pour chacune d'elles.

    Si une action destructrice entrait un jour dans le catalogue, ce test
    garantit que `confirmation_for` la connaît toujours.

    `reset_to` n'est destructeur qu'en mode « hard » (mesuré) : c'est le
    seul mode passé ici, sous peine d'affirmer le contraire de la réalité
    tout en paraissant vert.
    """
    etat = _etat_propre()
    for action in DESTRUCTRICES:
        mode = "hard" if action == "reset_to" else None
        assert confirmation_for(action, "cible", etat, mode=mode) is not None, (
            f"« {action} » n'a plus de confirmation : "
            "c'est exactement la régression de la phase 11"
        )


def test_recoverable_actions_need_no_confirmation():
    """`cherry_pick` et `merge_branch` sont récupérables (mesuré).

    Exiger une confirmation ici serait une friction sans bénéfice : ni
    l'un ni l'autre ne détruit quoi que ce soit d'irrécupérable.
    """
    etat = _etat_propre()
    for action in _RECUPERABLES:
        assert confirmation_for(action, "cible", etat) is None
