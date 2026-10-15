import pytest

from tortoisepy.core.settings import (
    DEFAULTS,
    SCHEMA_VERSION,
    coerce,
    is_supported_version,
)


def test_defaults_cover_every_persisted_key():
    """Une clé sans défaut planterait au premier démarrage."""
    assert set(DEFAULTS) == {
        "view/zoom",
        "view/panel_width",
        "view/panel_hidden",
        "view/workdir",
        "view/show_tags",
        "recent/repositories",
    }


def test_a_readable_value_is_typed():
    """QSettings rend des chaînes : « 1.5 » doit devenir un float."""
    assert coerce("view/zoom", "1.5") == 1.5
    assert coerce("view/show_tags", "false") is False
    assert coerce("view/show_tags", "true") is True


def test_a_corrupt_value_falls_back_to_the_default():
    """Un plist édité à la main ne doit pas empêcher l'app de démarrer.

    C'est le test qui compte : sans lui, une valeur illisible lèverait au
    lancement, et l'utilisateur n'aurait aucun moyen de s'en sortir sans
    supprimer ses préférences à la main.
    """
    assert coerce("view/zoom", "pas-un-nombre") == DEFAULTS["view/zoom"]
    assert coerce("view/zoom", None) == DEFAULTS["view/zoom"]
    assert coerce("view/panel_width", []) == DEFAULTS["view/panel_width"]


def test_the_hidden_panel_flag_is_a_real_boolean():
    """`QSettings` rend « false », qui est VRAI en Python.

    Sans coercition, un panneau explicitement affiché reviendrait
    masqué au lancement suivant — et la liste des commits
    disparaîtrait pour qui n'a rien demandé. Le défaut le plus
    coûteux de ce réglage, puisqu'il se déclenche tout seul.
    """
    assert coerce("view/panel_hidden", "false") is False
    assert coerce("view/panel_hidden", "0") is False
    assert coerce("view/panel_hidden", "true") is True
    assert coerce("view/panel_hidden", "1") is True
    # Et par défaut la liste s'affiche (demandé par l'utilisateur).
    assert DEFAULTS["view/panel_hidden"] is False
    assert coerce("view/panel_hidden", "abîmé") is False


def test_the_workdir_survives_a_bad_value():
    """Le dossier de projets choisi par l'utilisateur.

    On ne vérifie pas qu'il existe : il peut être sur un disque
    externe débranché, et l'oublier en silence perdrait le réglage.
    C'est à l'affichage de signaler qu'il est introuvable.
    """
    assert coerce("view/workdir", "/Users/x/Projets") == "/Users/x/Projets"
    assert coerce("view/workdir", "/disque/absent") == "/disque/absent"
    # Une valeur d'un autre type ne doit pas se propager comme chemin.
    assert coerce("view/workdir", ["a", "b"]) == DEFAULTS["view/workdir"]
    assert coerce("view/workdir", None) == DEFAULTS["view/workdir"]
    # Aucun dossier choisi : le cas du premier lancement.
    assert DEFAULTS["view/workdir"] == ""


def test_an_absurd_zoom_is_refused():
    """Un zoom nul ou négatif rendrait le graphe invisible."""
    assert coerce("view/zoom", "0") == DEFAULTS["view/zoom"]
    assert coerce("view/zoom", "-2") == DEFAULTS["view/zoom"]


def test_an_unknown_key_is_returned_unchanged():
    assert coerce("inconnue", "valeur") == "valeur"


def test_only_the_current_schema_is_supported():
    """Une version future fait repartir des défauts plutôt que planter."""
    assert is_supported_version(SCHEMA_VERSION)
    assert is_supported_version(str(SCHEMA_VERSION))
    assert not is_supported_version(SCHEMA_VERSION + 1)
    assert not is_supported_version(None)
    assert not is_supported_version("abîmé")
