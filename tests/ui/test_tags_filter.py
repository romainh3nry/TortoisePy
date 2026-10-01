import pytest
from PySide6.QtCore import QSettings

from tortoisepy.ui.main_window import MainWindow
from tortoisepy.ui.settings_store import SettingsStore


@pytest.fixture
def store(tmp_path):
    return SettingsStore(
        QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    )


def test_the_filter_is_exposed(qtbot, repo_linear, store):
    """§5.3 : aucun filtre n'était accessible depuis l'UI."""
    window = MainWindow(repo_linear.repo, settings=store)
    qtbot.addWidget(window)
    assert window.show_tags_action.isCheckable()
    assert window.show_tags_action.isChecked() is True


def test_toggling_updates_the_options(qtbot, repo_linear, store):
    window = MainWindow(repo_linear.repo, settings=store)
    qtbot.addWidget(window)
    window.show_tags_action.setChecked(False)
    assert window.graph_options().show_tags is False


def test_the_choice_survives_a_reopen(qtbot, repo_linear, store):
    first = MainWindow(repo_linear.repo, settings=store)
    qtbot.addWidget(first)
    first.show_tags_action.setChecked(False)
    first.save_settings()

    second = MainWindow(repo_linear.repo, settings=store)
    qtbot.addWidget(second)
    assert second.show_tags_action.isChecked() is False
    assert second.graph_options().show_tags is False


def test_the_other_filters_keep_their_measured_defaults(
    qtbot, repo_linear, store
):
    """§9 : seul `show_tags` entre dans le périmètre.

    Les quatre autres défauts sont justifiés par des mesures dans
    `options.py` et ne doivent pas bouger.
    """
    window = MainWindow(repo_linear.repo, settings=store)
    qtbot.addWidget(window)
    options = window.graph_options()
    assert options.show_local_branches is True
    assert options.show_remote_branches is True
    assert options.show_stashes is True
    assert options.show_junctions is False
