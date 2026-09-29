"""Exécution des opérations longues hors du fil principal.

Un fetch dure une à plusieurs secondes selon le dépôt et le réseau.
Exécuté dans le fil de l'interface, il la fige : mesuré, 1,6 s de gel sur
un fetch qui ne ramenait même rien.

Ce module fait tourner l'opération dans un `QThread` et renvoie ses
résultats par signaux, seule façon sûre de toucher à l'interface depuis
un autre fil en Qt.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, QThread, Signal

from tortoisepy.core.results import OperationResult, failed


class FetchWorker(QObject):
    """Exécute un fetch et rapporte son avancement.

    Les rappels de pygit2 sont appelés depuis le fil de travail : ils
    émettent des signaux plutôt que de modifier des widgets, car Qt
    interdit de toucher à l'interface hors du fil principal.
    """

    progress = Signal(int, int)
    """(objets reçus, objets attendus). `total` vaut 0 tant qu'il est inconnu."""

    finished = Signal(object)
    """`OperationResult` — jamais une exception, `guarded` s'en charge."""

    def __init__(self, operation: Callable[..., OperationResult]):
        super().__init__()
        self._operation = operation

    def run(self) -> None:
        try:
            result = self._operation(on_progress=self._report)
        except Exception as error:  # ceinture : `guarded` devrait tout capter
            result = failed("Fetch", f"{type(error).__name__}: {error}")
        self.finished.emit(result)

    def _report(self, received: int, total: int) -> None:
        self.progress.emit(received, total)


class BackgroundTask(QObject):
    """Garde vivants un fil et son ouvrier le temps d'une opération.

    Sans cette référence, Python les collecterait pendant l'exécution et
    Qt planterait — un piège classique du couple QThread/worker.
    """

    progress = Signal(int, int)
    finished = Signal(object)

    def __init__(self, worker: FetchWorker, parent=None):
        super().__init__(parent)
        self._thread = QThread(self)
        self._worker = worker

        worker.moveToThread(self._thread)
        self._thread.started.connect(worker.run)
        worker.progress.connect(self.progress.emit)
        worker.finished.connect(self._on_finished)

    def start(self) -> None:
        self._thread.start()

    def is_running(self) -> bool:
        return self._thread.isRunning()

    def wait(self, timeout_ms: int = 30_000) -> bool:
        """Attend la fin du fil. Utile aux tests et à la fermeture."""
        return self._thread.wait(timeout_ms)

    def stop(self, timeout_ms: int = 10_000) -> bool:
        """Demande l'arrêt du fil, puis l'attend. Vrai s'il s'est arrêté.

        `wait()` seul ne suffit pas à la fermeture : la boucle du fil ne
        se termine qu'après `quit()`, que `_on_finished` appelle **depuis
        le fil principal**. Attendre sans avoir demandé l'arrêt bloquait
        donc jusqu'au délai maximum (vérifié).

        `quit()` laisse l'opération en cours finir : on ne coupe pas un
        push au milieu, on cesse seulement de traiter la suite.
        """
        self._thread.quit()
        return self._thread.wait(timeout_ms)

    def _on_finished(self, result: OperationResult) -> None:
        self._thread.quit()
        self._thread.wait(5_000)
        self.finished.emit(result)
