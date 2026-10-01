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
    """La largeur exacte, pas seulement « non nulle ».

    Une assertion `> 0` passait alors que la largeur enregistrée revenait
    à une tout autre valeur : le splitter n'a pas de vraie taille avant le
    premier `show()`, qui a lieu après `__init__` — la mise en page qui en
    résulte écrasait toute largeur posée trop tôt (vérifié : 524 au lieu
    de 300 demandés).

    Les tailles demandées ici respectent le minimum de `CommitPanel`
    (420 px, `commit_panel.py`) : y descendre en dessous fait
    silencieusement clamper `setSizes` par Qt lui-même, ce qui n'a rien à
    voir avec la restauration et fausserait ce test (vérifié).
    """
    first = MainWindow(repo_linear.repo, settings=store)
    qtbot.addWidget(first)
    first.resize(1400, 850)
    first.show()
    first.splitter.setSizes([900, 500])
    first.save_settings()
    largeur_enregistree = store.value("view/panel_width")

    second = MainWindow(repo_linear.repo, settings=store)
    qtbot.addWidget(second)
    second.resize(1400, 850)
    second.show()
    assert abs(second.splitter.sizes()[1] - largeur_enregistree) <= 20, (
        f"largeur du panneau non restaurée : {second.splitter.sizes()[1]} "
        f"(attendu ~{largeur_enregistree})"
    )


def test_a_later_resize_is_not_overwritten(qtbot, repo_linear, store):
    """La largeur restaurée n'écrase pas un redimensionnement ultérieur.

    `_largeur_panneau_en_attente` est consommée une seule fois au premier
    `showEvent` : un second `show()` (minimiser/restaurer, changer
    d'écran…) ne doit pas revenir en arrière sur un geste de
    l'utilisateur fait entre-temps.
    """
    first = MainWindow(repo_linear.repo, settings=store)
    qtbot.addWidget(first)
    first.resize(1400, 850)
    first.show()
    first.splitter.setSizes([900, 500])
    first.save_settings()

    second = MainWindow(repo_linear.repo, settings=store)
    qtbot.addWidget(second)
    second.resize(1400, 850)
    second.show()

    # L'utilisateur élargit le panneau après l'ouverture.
    second.splitter.setSizes([1000, 400])
    tailles_apres_geste = second.splitter.sizes()

    # Un second affichage (ex. minimiser puis restaurer) ne doit rien
    # réappliquer : la largeur en attente a déjà été consommée.
    second.hide()
    second.show()
    assert second.splitter.sizes() == tailles_apres_geste


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
