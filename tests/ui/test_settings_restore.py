import pytest
from PySide6.QtCore import QRect, QSettings

from tortoisepy.ui.main_window import MainWindow
from tortoisepy.ui.settings_store import SettingsStore


@pytest.fixture
def store(tmp_path):
    return SettingsStore(
        QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    )


def test_zoom_survives_a_close_and_reopen(qtbot, repo_linear, store):
    """Le réglage le plus visible d'un lancement à l'autre."""
    first = MainWindow(repo_linear.repo, settings=store)
    qtbot.addWidget(first)
    first.view.set_zoom(1.6)
    first.save_settings()

    second = MainWindow(repo_linear.repo, settings=store)
    qtbot.addWidget(second)
    assert second.view.current_zoom() == pytest.approx(1.6, abs=0.01)


def test_panel_width_survives(qtbot, repo_linear, store):
    first = MainWindow(repo_linear.repo, settings=store)
    qtbot.addWidget(first)
    first.splitter.setSizes([700, 300])
    first.save_settings()

    second = MainWindow(repo_linear.repo, settings=store)
    qtbot.addWidget(second)
    assert second.splitter.sizes()[1] > 0


def test_an_offscreen_geometry_is_ignored(qtbot, repo_linear, store):
    """§D51 : débrancher un moniteur ne doit pas rendre l'app injoignable.

    Le test qui distingue cette phase d'une restauration naïve : sans lui,
    une géométrie mémorisée sur un second écran rouvrirait la fenêtre hors
    de tout écran, invisible et inatteignable.
    """
    window = MainWindow(repo_linear.repo, settings=store)
    qtbot.addWidget(window)
    assert not window.geometry_is_visible(QRect(-9000, -9000, 800, 600))
    assert window.geometry_is_visible(window.geometry())


def test_a_fresh_profile_uses_the_defaults(qtbot, repo_linear, store):
    """Premier lancement : aucun réglage, aucun plantage."""
    window = MainWindow(repo_linear.repo, settings=store)
    qtbot.addWidget(window)
    assert window.view.current_zoom() == pytest.approx(1.0)


def test_saving_twice_is_idempotent(qtbot, repo_linear, store):
    window = MainWindow(repo_linear.repo, settings=store)
    qtbot.addWidget(window)
    window.view.set_zoom(1.3)
    window.save_settings()
    premier = store.value("view/zoom")
    window.save_settings()
    assert store.value("view/zoom") == premier


def test_shortcuts_action_opens_the_shortcuts_window(
    qtbot, repo_linear, store, monkeypatch
):
    """La barre d'outils doit donner accès à la fenêtre des raccourcis.

    `open_shortcuts_window` est monkeypatchée pour ne pas ouvrir de vraie
    fenêtre modale (`exec()` bloquerait le test).
    """
    window = MainWindow(repo_linear.repo, settings=store)
    qtbot.addWidget(window)

    appels = []
    monkeypatch.setattr(
        window, "open_shortcuts_window", lambda: appels.append(True)
    )

    window.shortcuts_action.trigger()

    assert appels == [True]
