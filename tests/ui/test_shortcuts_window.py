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


def test_double_clicking_a_row_captures_the_right_action(window, monkeypatch):
    """Le double-clic doit viser la ligne cliquée, pas toujours la première."""
    demandes = []

    def _fausse_demande(action_id):
        demandes.append(action_id)
        return None

    monkeypatch.setattr(window, "_demander_sequence", _fausse_demande)

    ids = [ligne[0] for ligne in window.rows()]
    index_push = ids.index("push")
    window._on_row_double_clicked(index_push, 1)

    assert demandes == ["push"]


def test_cancelling_the_capture_writes_and_emits_nothing(
    window, qtbot, monkeypatch
):
    monkeypatch.setattr(window, "_demander_sequence", lambda action_id: None)
    avant = window._store.resolved_shortcuts()["commit"]

    with qtbot.assertNotEmitted(window.shortcuts_changed):
        window._on_row_double_clicked(
            [ligne[0] for ligne in window.rows()].index("commit"), 1
        )

    assert window._store.resolved_shortcuts()["commit"] == avant


def test_a_refused_capture_shows_the_reason_and_writes_nothing(
    window, monkeypatch
):
    monkeypatch.setattr(
        window, "_demander_sequence", lambda action_id: "Ctrl+Q"
    )

    boites = []

    def _fausse_boite(parent, titre, texte):
        boites.append(texte)

    monkeypatch.setattr(
        "tortoisepy.ui.shortcuts_window.QMessageBox.warning", _fausse_boite
    )

    avant = window._store.resolved_shortcuts()["commit"]
    window._on_row_double_clicked(
        [ligne[0] for ligne in window.rows()].index("commit"), 1
    )

    assert len(boites) == 1
    assert window._store.resolved_shortcuts()["commit"] == avant


def test_an_accepted_capture_stores_and_emits(window, qtbot, monkeypatch):
    monkeypatch.setattr(
        window, "_demander_sequence", lambda action_id: "Ctrl+J"
    )

    with qtbot.waitSignal(window.shortcuts_changed, timeout=1000) as bloqueur:
        window._on_row_double_clicked(
            [ligne[0] for ligne in window.rows()].index("commit"), 1
        )

    assert bloqueur.args[0]["commit"] == "Ctrl+J"
    assert window._store.resolved_shortcuts()["commit"] == "Ctrl+J"
