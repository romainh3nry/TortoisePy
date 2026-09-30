from tortoisepy.core.shortcuts import (
    CATALOGUE,
    RESERVED,
    resolve,
    spec_for,
    validate,
)


def test_the_catalogue_covers_the_current_shortcuts():
    """Les dix actions de `main_window._build_actions` (§6.1)."""
    ids = {spec.action_id for spec in CATALOGUE}
    assert ids == {
        "zoom_in", "zoom_out", "zoom_reset", "fit_to_window",
        "refresh", "commit", "search", "push", "pull", "fetch",
    }


def test_action_ids_are_stable_and_distinct_from_labels():
    """Renommer un libellé ne doit pas perdre le choix de l'utilisateur."""
    for spec in CATALOGUE:
        assert spec.action_id.islower()
        assert " " not in spec.action_id
        assert spec.action_id != spec.label


def test_defaults_are_stored_portable_not_native():
    """§D47 : « Ctrl+F », jamais « ⌘F ».

    Un fichier de préférences contenant du texte natif serait illisible
    en changeant de plateforme.
    """
    for spec in CATALOGUE:
        assert "⌘" not in spec.default
        assert "⇧" not in spec.default


def test_a_free_sequence_is_accepted():
    assert validate("commit", "Ctrl+J", {}) is None


def test_a_conflict_names_the_other_action():
    """Le message doit dire à QUI la touche est prise (§6.3)."""
    motif = validate("commit", "Ctrl+F", {"search": "Ctrl+F"})
    assert motif is not None
    assert "search" in motif


def test_reassigning_an_action_to_its_own_sequence_is_allowed():
    """Rouvrir l'éditeur sans rien changer ne doit pas crier au conflit."""
    assert validate("search", "Ctrl+F", {"search": "Ctrl+F"}) is None


def test_a_reserved_sequence_is_refused():
    """Réassigner ⌘Q rendrait l'application impossible à quitter."""
    for sequence in ("Ctrl+Q", "Ctrl+W"):
        assert sequence in RESERVED
        assert validate("commit", sequence, {}) is not None


def test_an_empty_sequence_is_refused():
    assert validate("commit", "", {}) is not None
    assert validate("commit", "   ", {}) is not None


def test_resolve_applies_overrides_over_defaults():
    resolus = resolve({"commit": "Ctrl+J"})
    assert resolus["commit"] == "Ctrl+J"
    assert resolus["search"] == spec_for("search").default


def test_resolve_ignores_an_unknown_action():
    """Une préférence d'une version future ne doit pas planter."""
    assert "inconnue" not in resolve({"inconnue": "Ctrl+Z"})


def test_destructive_actions_are_flagged():
    """Le drapeau sert à PRÉVENIR l'utilisateur, pas à protéger.

    La protection réelle est `dialogs.confirmation_for` (§6.4). Ce
    drapeau ne pilote que l'affichage.
    """
    assert any(spec.destructive for spec in CATALOGUE) is False
