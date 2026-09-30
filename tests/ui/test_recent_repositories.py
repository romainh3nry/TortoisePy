import pytest
from PySide6.QtCore import QSettings

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
