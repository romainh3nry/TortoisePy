"""Exécution des opérations longues hors du fil principal."""

import pytest

from tortoisepy.core.results import failed, succeeded
from tortoisepy.ui.tasks import BackgroundTask, FetchWorker


def test_worker_reports_its_result(qtbot):
    worker = FetchWorker(lambda on_progress: succeeded("fini"))
    task = BackgroundTask(worker)

    with qtbot.waitSignal(task.finished, timeout=5000) as blocker:
        task.start()

    assert blocker.args[0].success is True
    assert blocker.args[0].summary == "fini"


def test_worker_reports_progress(qtbot):
    def operation(on_progress):
        for step in range(1, 4):
            on_progress(step, 3)
        return succeeded("fini")

    worker = FetchWorker(operation)
    task = BackgroundTask(worker)

    seen = []
    task.progress.connect(lambda r, t: seen.append((r, t)))

    with qtbot.waitSignal(task.finished, timeout=5000):
        task.start()

    assert seen == [(1, 3), (2, 3), (3, 3)]


def test_failure_is_reported_not_raised(qtbot):
    """§7.6 : aucune exception ne remonte à l'interface."""
    worker = FetchWorker(lambda on_progress: failed("Fetch", "réseau injoignable"))
    task = BackgroundTask(worker)

    with qtbot.waitSignal(task.finished, timeout=5000) as blocker:
        task.start()

    assert blocker.args[0].success is False
    assert "réseau" in blocker.args[0].git_error


def test_unexpected_exception_becomes_a_result(qtbot):
    """Ceinture : même une erreur non prévue ne fait pas planter le fil."""
    def boom(on_progress):
        raise RuntimeError("inattendu")

    worker = FetchWorker(boom)
    task = BackgroundTask(worker)

    with qtbot.waitSignal(task.finished, timeout=5000) as blocker:
        task.start()

    assert blocker.args[0].success is False
    assert "RuntimeError" in blocker.args[0].git_error


def test_thread_stops_after_completion(qtbot):
    """Un fil laissé tournant empêcherait la fenêtre de se fermer."""
    worker = FetchWorker(lambda on_progress: succeeded("fini"))
    task = BackgroundTask(worker)

    with qtbot.waitSignal(task.finished, timeout=5000):
        task.start()

    assert task.wait(2000) is True
    assert task.is_running() is False


def test_task_runs_off_the_main_thread(qtbot):
    """Le but même de ce module : ne pas geler l'interface."""
    from PySide6.QtCore import QThread

    main = QThread.currentThread()
    seen = []

    def operation(on_progress):
        seen.append(QThread.currentThread())
        return succeeded("fini")

    task = BackgroundTask(FetchWorker(operation))
    with qtbot.waitSignal(task.finished, timeout=5000):
        task.start()

    assert seen and seen[0] is not main
