import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QKeySequence

from tortoisepy.core.shortcuts import CATALOGUE, spec_for
from tortoisepy.ui.settings_store import SettingsStore
from tortoisepy.ui.shortcuts_window import ShortcutsWindow


@pytest.fixture
def window(qtbot, tmp_path):
    store = SettingsStore(
        QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    )
    w = ShortcutsWindow(store)
    qtbot.addWidget(w)
    return w


def test_every_action_is_listed(window):
    """§6.2 : la fenêtre rend les raccourcis découvrables."""
    ids = {ligne[0] for ligne in window.rows()}
    assert ids == {spec.action_id for spec in CATALOGUE}


def test_sequences_are_shown_natively(window):
    """⌘F à l'écran, « Ctrl+F » dans le fichier (§6.2)."""
    par_id = {ligne[0]: ligne[2] for ligne in window.rows()}
    attendu = QKeySequence(spec_for("search").default).toString(
        QKeySequence.SequenceFormat.NativeText
    )
    assert par_id["search"] == attendu


def test_assigning_a_free_sequence_succeeds(window):
    assert window.try_assign("commit", "Ctrl+J") is None
    assert window._store.resolved_shortcuts()["commit"] == "Ctrl+J"


def test_a_conflict_is_refused_and_nothing_is_written(window):
    """Le refus doit être total : ni écriture, ni état incohérent."""
    avant = window._store.resolved_shortcuts()["commit"]
    motif = window.try_assign("commit", spec_for("search").default)

    assert motif is not None
    assert "search" in motif
    assert window._store.resolved_shortcuts()["commit"] == avant


def test_a_reserved_sequence_is_refused(window):
    assert window.try_assign("commit", "Ctrl+Q") is not None
    assert window._store.shortcut_overrides() == {}


def test_reset_restores_every_default(window):
    window.try_assign("commit", "Ctrl+J")
    window.reset_all()
    assert window._store.shortcut_overrides() == {}
    par_id = {ligne[0]: ligne[2] for ligne in window.rows()}
    assert par_id["commit"] == QKeySequence(
        spec_for("commit").default
    ).toString(QKeySequence.SequenceFormat.NativeText)


def test_a_successful_assignment_emits_the_signal(qtbot, window):
    """La fenêtre principale doit pouvoir appliquer sans relancer."""
    with qtbot.waitSignal(window.shortcuts_changed, timeout=1000) as bloqueur:
        window.try_assign("commit", "Ctrl+J")
    assert bloqueur.args[0]["commit"] == "Ctrl+J"


def test_a_refused_assignment_emits_nothing(qtbot, window):
    with qtbot.assertNotEmitted(window.shortcuts_changed):
        window.try_assign("commit", "Ctrl+Q")
