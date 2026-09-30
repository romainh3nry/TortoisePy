from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

from tests.fixtures.builder import RepoBuilder
from tortoisepy.ui.main_window import MainWindow
from tortoisepy.ui.settings_store import MAX_RECENT, SettingsStore


@pytest.fixture
def store(tmp_path):
    return SettingsStore(
        QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    )


def test_a_repository_is_remembered(store, tmp_path):
    store.remember_repository(str(tmp_path))
    assert str(tmp_path) in store.recent_repositories()


def test_the_most_recent_comes_first(store, tmp_path):
    premier = tmp_path / "un"
    second = tmp_path / "deux"
    premier.mkdir()
    second.mkdir()

    store.remember_repository(str(premier))
    store.remember_repository(str(second))
    assert store.recent_repositories()[0] == str(second)


def test_reopening_moves_it_up_without_duplicating(store, tmp_path):
    premier = tmp_path / "un"
    second = tmp_path / "deux"
    premier.mkdir()
    second.mkdir()

    store.remember_repository(str(premier))
    store.remember_repository(str(second))
    store.remember_repository(str(premier))

    recents = store.recent_repositories()
    assert recents[0] == str(premier)
    assert recents.count(str(premier)) == 1


def test_a_vanished_repository_is_purged(store, tmp_path):
    """Un dépôt déplacé ou supprimé ne doit pas encombrer la liste.

    Le test qui compte : sans purge, le menu proposerait des entrées qui
    échouent à l'ouverture, sans que l'utilisateur puisse les retirer.
    """
    disparu = tmp_path / "disparu"
    disparu.mkdir()
    store.remember_repository(str(disparu))
    disparu.rmdir()

    assert str(disparu) not in store.recent_repositories()


def test_the_list_is_capped(store, tmp_path):
    for index in range(MAX_RECENT + 5):
        chemin = tmp_path / f"depot-{index}"
        chemin.mkdir()
        store.remember_repository(str(chemin))

    assert len(store.recent_repositories()) <= MAX_RECENT


def _menu_labels(menu):
    return [action.text() for action in menu.actions()]


def test_the_menu_lists_remembered_repositories(qtbot, repo_linear, tmp_path):
    """Du plus récent au plus ancien, comme `recent_repositories()`."""
    autre = tmp_path / "autre-depot"
    autre.mkdir()

    store = SettingsStore(
        QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    )
    store.remember_repository(str(autre))

    window = MainWindow(repo_linear.repo, settings=store)
    qtbot.addWidget(window)

    menu = window.recent_button.menu()
    menu.aboutToShow.emit()

    labels = _menu_labels(menu)
    # La fenêtre elle-même vient d'être mémorisée dans son __init__ : elle
    # est donc la plus récente, avant `autre`.
    assert labels[0] == str(Path(repo_linear.repo.workdir))
    assert labels[1] == str(autre)


def test_a_vanished_repository_does_not_appear_in_the_menu(
    qtbot, repo_linear, tmp_path
):
    disparu = tmp_path / "disparu"
    disparu.mkdir()

    store = SettingsStore(
        QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    )
    store.remember_repository(str(disparu))
    disparu.rmdir()

    window = MainWindow(repo_linear.repo, settings=store)
    qtbot.addWidget(window)

    menu = window.recent_button.menu()
    menu.aboutToShow.emit()

    assert str(disparu) not in _menu_labels(menu)


def test_an_empty_list_shows_a_disabled_entry(qtbot, tmp_path):
    """Un menu vide se lirait comme un bouton cassé."""
    b = RepoBuilder(tmp_path / "seul")
    b.commit("A")

    store = SettingsStore(
        QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    )
    window = MainWindow(b.repo, settings=store)
    qtbot.addWidget(window)

    # La fenêtre vient de mémoriser SON propre dépôt : on le retire pour
    # retrouver une liste vide, cas que ce test vise précisément.
    store._settings.remove("recent/repositories")

    menu = window.recent_button.menu()
    menu.aboutToShow.emit()

    labels = _menu_labels(menu)
    assert labels == ["No recent repositories"]
    assert menu.actions()[0].isEnabled() is False


def test_triggering_an_entry_opens_it(qtbot, repo_linear, tmp_path, monkeypatch):
    autre = tmp_path / "autre-depot"
    autre.mkdir()

    store = SettingsStore(
        QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    )
    store.remember_repository(str(autre))

    window = MainWindow(repo_linear.repo, settings=store)
    qtbot.addWidget(window)

    ouverts = []
    monkeypatch.setattr(
        window, "open_recent_repository", lambda path: ouverts.append(path)
    )

    menu = window.recent_button.menu()
    menu.aboutToShow.emit()
    action_autre = next(
        a for a in menu.actions() if a.text() == str(autre)
    )
    action_autre.trigger()

    assert ouverts == [str(autre)]
