import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QKeySequence

from tortoisepy.core.shortcuts import CATALOGUE, spec_for
from tortoisepy.ui.main_window import MainWindow
from tortoisepy.ui.settings_store import SettingsStore


@pytest.fixture
def window(qtbot, repo_linear, tmp_path):
    store = SettingsStore(
        QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    )
    w = MainWindow(repo_linear.repo, settings=store)
    qtbot.addWidget(w)
    return w


def test_every_catalogue_action_exists(window):
    """Le littéral codé en dur est remplacé par le catalogue (§6.1)."""
    for spec in CATALOGUE:
        assert spec.action_id in window.actions_by_id


def test_defaults_are_applied_when_nothing_is_stored(window):
    action = window.actions_by_id["commit"]
    attendu = QKeySequence(spec_for("commit").default)
    assert action.shortcut() == attendu


def test_a_stored_override_wins_over_the_default(qtbot, repo_linear, tmp_path):
    chemin = str(tmp_path / "prefs.ini")
    store = SettingsStore(QSettings(chemin, QSettings.Format.IniFormat))
    store.set_shortcut("commit", "Ctrl+J")

    w = MainWindow(repo_linear.repo, settings=store)
    qtbot.addWidget(w)
    assert w.actions_by_id["commit"].shortcut() == QKeySequence("Ctrl+J")


def test_applying_shortcuts_updates_live(window):
    """Modifier un raccourci ne doit pas exiger de relancer l'app."""
    window.apply_shortcuts({**window.settings.resolved_shortcuts(),
                            "search": "Ctrl+E"})
    assert window.actions_by_id["search"].shortcut() == QKeySequence("Ctrl+E")


def test_shortcuts_are_displayed_natively(window):
    """§6.2 : ⌘F à l'écran, « Ctrl+F » dans le fichier.

    Le test compare au rendu natif de Qt sur la plateforme courante, ce
    qui le rend valide aussi bien sur macOS que sur Windows.
    """
    action = window.actions_by_id["search"]
    natif = action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
    portable = action.shortcut().toString(
        QKeySequence.SequenceFormat.PortableText
    )
    assert portable == spec_for("search").default
    assert natif == QKeySequence(
        spec_for("search").default
    ).toString(QKeySequence.SequenceFormat.NativeText)


def test_set_zoom_is_exposed(window):
    """La restauration du zoom en a besoin (Task 6)."""
    window.view.set_zoom(1.5)
    assert window.view.current_zoom() == pytest.approx(1.5)


def test_set_zoom_refuses_an_absurd_value(window):
    """Un zoom nul rendrait le graphe invisible sans recours."""
    avant = window.view.current_zoom()
    window.view.set_zoom(0.0)
    assert window.view.current_zoom() == pytest.approx(avant)
