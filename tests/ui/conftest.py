"""Qt en mode offscreen : les tests tournent sans écran.

Doit être posé AVANT le premier import de PySide6, d'où sa place ici
plutôt que dans une fixture.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(autouse=True)
def _qapp():
    """Garantit une QApplication vivante pour tout le module.

    QFontMetricsF (et plus généralement QFontDatabase) exige une instance
    QGuiApplication ; sans elle, Qt abandonne le processus (SIGABRT) plutôt
    que de lever une exception Python. La fixture `qapp` de pytest-qt fait
    la même chose mais seulement pour les tests qui la demandent
    explicitement (via `qapp` ou `qtbot`) ; ici on la rend automatique pour
    tout le dossier `tests/ui/`.
    """
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def attendre_le_fond():
    """Attend la fin du travail de fond d'une fenêtre.

    Depuis que `refresh()` lit le dépôt en arrière-plan (loader demandé
    par l'utilisateur), la méthode rend la main AVANT que le graphe soit
    reposé : dix tests écrits à l'époque synchrone vérifiaient le
    résultat trop tôt.

    Attendre `view.isEnabled()` ne suffit pas pour les actions d'écriture :
    `run_in_background` réactive l'interface, puis la suite enchaîne sur
    `refresh()`, qui reprend le verrou et remontre la barre. On attend
    donc le verrou lui-même, seul témoin fiable du « plus rien ne tourne ».

    Le verrou se relâche ENTRE deux tâches enchaînées : une action
    d'écriture le rend, puis son `refresh()` le reprend aussitôt. Guetter
    le premier relâchement rendrait donc la main au milieu de la chaîne
    (vérifié sur `test_fetch_summary_survives_the_refresh`). On exige une
    accalmie : le verrou doit être libre, et le rester le temps de laisser
    une tâche suivante démarrer.
    """

    def attendre(qtbot, fenetre, timeout: int = 10000) -> None:
        def libre() -> bool:
            tache = fenetre._task
            return tache is None or not tache.is_running()

        for _ in range(50):
            qtbot.waitUntil(libre, timeout=timeout)
            # Laisse une tâche enchaînée prendre le verrou, s'il y en a une.
            qtbot.wait(30)
            if libre():
                return

        raise AssertionError("le travail de fond ne se termine jamais")

    return attendre


@pytest.fixture
def attendre_la_fenetre():
    """Attend la fin du travail de fond d'une fenêtre de commit.

    Depuis que le commit et le push partent en arrière-plan (le loader ne
    pouvait pas être peint autrement), `commit()` et `commit_and_push()`
    rendent la main avant la fin du travail.

    `commit_and_push` enchaîne DEUX tâches : le commit rend le verrou,
    puis le push le reprend. Il faut donc attendre une accalmie, pas le
    premier relâchement, sinon l'attente se termine entre les deux.
    """

    def attendre(qtbot, fenetre, timeout: int = 10000) -> None:
        def libre() -> bool:
            tache = getattr(fenetre, "_task", None)
            return tache is None or not tache.is_running()

        for _ in range(50):
            qtbot.waitUntil(libre, timeout=timeout)
            qtbot.wait(30)   # laisse une tâche enchaînée prendre le verrou
            if libre():
                return

        raise AssertionError("le travail de fond ne se termine jamais")

    return attendre
