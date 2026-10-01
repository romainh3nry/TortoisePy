import pytest
from PySide6.QtCore import QSettings

from tortoisepy.core.settings import DEFAULTS, SCHEMA_VERSION
from tortoisepy.core.shortcuts import spec_for
from tortoisepy.ui.settings_store import SettingsStore


@pytest.fixture
def store(tmp_path):
    """Un magasin isolé : un fichier .ini du test, jamais les vraies
    préférences de l'utilisateur."""
    chemin = str(tmp_path / "prefs.ini")
    return SettingsStore(QSettings(chemin, QSettings.Format.IniFormat))


def test_a_round_trip_preserves_each_value(store):
    store.set_value("view/zoom", 1.75)
    store.set_value("view/show_tags", False)
    assert store.value("view/zoom") == 1.75
    assert store.value("view/show_tags") is False


def test_an_unset_key_gives_its_default(store):
    assert store.value("view/zoom") == DEFAULTS["view/zoom"]
    assert store.value("view/show_tags") == DEFAULTS["view/show_tags"]


def test_a_corrupt_stored_value_gives_the_default(store, tmp_path):
    """Écrit à la main dans le fichier, comme le ferait un éditeur."""
    store._settings.setValue("view/zoom", "abîmé")
    assert store.value("view/zoom") == DEFAULTS["view/zoom"]


def test_an_unknown_schema_version_falls_back_to_defaults(tmp_path):
    """§D48 : des préférences d'une version future ne cassent rien."""
    chemin = str(tmp_path / "futur.ini")
    brut = QSettings(chemin, QSettings.Format.IniFormat)
    brut.setValue("settings/version", SCHEMA_VERSION + 99)
    brut.setValue("view/zoom", 3.0)
    brut.sync()

    store = SettingsStore(QSettings(chemin, QSettings.Format.IniFormat))
    assert store.value("view/zoom") == DEFAULTS["view/zoom"]


def test_writing_stamps_the_schema_version(store):
    store.set_value("view/zoom", 1.25)
    assert int(store._settings.value("settings/version")) == SCHEMA_VERSION


def test_only_modified_shortcuts_are_stored(store):
    """§D49 : ne pas figer les défauts dans le fichier de l'utilisateur."""
    assert store.shortcut_overrides() == {}

    store.set_shortcut("commit", "Ctrl+J")
    assert store.shortcut_overrides() == {"commit": "Ctrl+J"}

    store.set_shortcut("commit", None)
    assert store.shortcut_overrides() == {}


def test_a_shortcut_is_stored_portable_not_native(store):
    """Le test qui protège le multiplateforme (§D47).

    Stocker « ⌘F » produirait un fichier illisible sur Windows.
    """
    store.set_shortcut("search", "Ctrl+F")
    brut = store._settings.value("shortcuts/search")
    assert brut == "Ctrl+F"
    assert "⌘" not in str(brut)


def test_resolved_shortcuts_merge_defaults_and_overrides(store):
    store.set_shortcut("commit", "Ctrl+J")
    resolus = store.resolved_shortcuts()
    assert resolus["commit"] == "Ctrl+J"
    assert resolus["search"] == spec_for("search").default


def test_reset_clears_every_override(store):
    store.set_shortcut("commit", "Ctrl+J")
    store.set_shortcut("push", "Ctrl+Y")
    store.reset_shortcuts()
    assert store.shortcut_overrides() == {}
    assert store.resolved_shortcuts()["commit"] == spec_for("commit").default
