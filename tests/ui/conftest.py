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
