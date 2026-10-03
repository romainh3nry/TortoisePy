"""Catalogue des raccourcis et règles de validation.

Aucun Qt : `test_architecture.py` l'interdit à `core/`. Les séquences sont
donc des chaînes au format portable de Qt (« Ctrl+F »), que `ui/` convertit
en `QKeySequence` pour l'affichage natif (« ⌘F »).

Les dix entrées reprennent `main_window._build_actions`, où elles étaient
codées en dur dans un littéral. `zoom_in`, `zoom_out` et `refresh`
utilisaient des `StandardKey` : leurs équivalents portables sont repris
tels quels pour ne pas changer le comportement existant.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ShortcutSpec:
    """Une action raccourcissable.

    `action_id` est stable et distinct de `label` : renommer un libellé ne
    doit pas faire perdre à l'utilisateur le raccourci qu'il a choisi.
    """

    action_id: str
    label: str
    default: str
    destructive: bool = False
    """Purement indicatif, pour l'affichage.

    **Ce drapeau ne protège rien** — la leçon de la phase 11, où
    `MenuEntry.needs_confirmation` était posé, testé, et pourtant sans
    effet : « Drop stash » détruisait le stash même sur un refus. La
    protection réelle passe par `dialogs.confirmation_for` (§6.4).
    """


CATALOGUE: tuple[ShortcutSpec, ...] = (
    ShortcutSpec("zoom_in", "Zoom in", "Ctrl++"),
    ShortcutSpec("zoom_out", "Zoom out", "Ctrl+-"),
    ShortcutSpec("zoom_reset", "Zoom 100%", "Ctrl+0"),
    ShortcutSpec("fit_to_window", "Fit to window", "Ctrl+9"),
    # F5 même sur macOS, où ce n'est pas une convention : c'est le défaut
    # actuel (QKeySequence.StandardKey.Refresh), conservé pour ne pas
    # changer le comportement sous l'utilisateur. Il devient modifiable,
    # ce qui règle le problème pour qui le souhaite (§6.1).
    ShortcutSpec("refresh", "Refresh", "F5"),
    ShortcutSpec("commit", "Commit…", "Ctrl+K"),
    ShortcutSpec("search", "Find branch", "Ctrl+F"),
    ShortcutSpec("push", "Push", "Ctrl+P"),
    ShortcutSpec("pull", "Pull", "Ctrl+L"),
    ShortcutSpec("fetch", "Fetch", "Ctrl+Shift+F"),
)

RESERVED: frozenset[str] = frozenset({
    "Ctrl+Q",    # quitter — l'app deviendrait impossible à fermer
    "Ctrl+W",    # fermer la fenêtre
    "Ctrl+Tab",  # navigation système
    "Alt+F4",    # fermer sous Windows
})

_PAR_ID = {spec.action_id: spec for spec in CATALOGUE}


def spec_for(action_id: str) -> ShortcutSpec | None:
    return _PAR_ID.get(action_id)


def resolve(overrides: dict[str, str]) -> dict[str, str]:
    """Défauts du catalogue, surchargés par les choix de l'utilisateur.

    Une clé inconnue est ignorée : des préférences écrites par une version
    plus récente ne doivent pas empêcher celle-ci de démarrer.
    """
    resolus = {spec.action_id: spec.default for spec in CATALOGUE}
    for action_id, sequence in overrides.items():
        if action_id in resolus and sequence:
            resolus[action_id] = sequence
    return resolus


def validate(
    action_id: str, sequence: str, assignments: dict[str, str]
) -> str | None:
    """Motif du refus, ou `None` si la séquence est acceptable.

    `assignments` associe chaque action à sa séquence courante. Réassigner
    une action à la séquence qu'elle porte déjà n'est pas un conflit :
    sans cette exception, rouvrir l'éditeur sans rien changer serait refusé.
    """
    nettoyee = sequence.strip()
    if not nettoyee:
        return "Une séquence vide n'est pas un raccourci."

    if nettoyee in RESERVED:
        return f"« {nettoyee} » est réservé par le système."

    for autre_id, autre_sequence in assignments.items():
        if autre_sequence == nettoyee and autre_id != action_id:
            return f"« {nettoyee} » est déjà utilisé par « {autre_id} »."

    return None
