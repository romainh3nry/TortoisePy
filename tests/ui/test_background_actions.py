"""Aucune action de lecture ne doit geler l'interface.

Demandé par l'utilisateur : « à chaque fois qu'une action est susceptible
de faire freezer l'app pendant quelques secondes, on la fait en arrière-
plan avec un loader ».

Mesuré sur son dépôt (713 refs) : `build_graph` 2185 ms, `list_changes`
760 ms, `read_state` 436 ms, `diff_for` 385 ms. Sur un petit dépôt, les
mêmes opérations coûtent 3 à 100 ms — le gel ne se manifeste qu'à
l'échelle, d'où une règle plutôt qu'une liste figée.
"""

from __future__ import annotations

import subprocess
import time

import pygit2
import pytest

from tortoisepy.ui.main_window import MainWindow
from tortoisepy.ui.tasks import CallableWorker


def _git(chemin, *args):
    subprocess.run(
        ["git", "-C", str(chemin), *args], check=False, capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
            "PATH": "/usr/bin:/bin:/usr/local/bin",
        },
    )


@pytest.fixture
def fenetre(qtbot, tmp_path):
    w = tmp_path / "w"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "a.txt").write_text("a\n")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "base")

    fenetre = MainWindow(pygit2.Repository(str(w)))
    qtbot.addWidget(fenetre)
    # `isVisible()` d'un enfant est faux tant que la fenêtre est cachée :
    # sans ce `show`, le test de la barre de progression mesurerait
    # l'affichage de la fenêtre, pas celui de la barre.
    fenetre.show()
    return fenetre


def test_the_worker_runs_any_callable(qtbot):
    """`BackgroundTask` était déjà générique ; seul le worker ne l'était pas."""
    from tortoisepy.ui.tasks import BackgroundTask

    tache = BackgroundTask(CallableWorker(lambda: 6 * 7))
    with qtbot.waitSignal(tache.finished, timeout=5000) as bloqueur:
        tache.start()

    assert bloqueur.args[0] == 42
    tache.stop()


def test_an_exception_is_reported_not_swallowed(qtbot):
    """Une opération qui lève doit le dire, pas disparaître en silence."""
    from tortoisepy.ui.tasks import BackgroundTask

    def casse():
        raise ValueError("quelque chose a mal tourné")

    tache = BackgroundTask(CallableWorker(casse))
    with qtbot.waitSignal(tache.finished, timeout=5000) as bloqueur:
        tache.start()

    resultat = bloqueur.args[0]
    assert isinstance(resultat, Exception), resultat
    assert "mal tourné" in str(resultat)
    tache.stop()


def test_the_interface_stays_responsive(qtbot, fenetre):
    """L'assertion centrale : l'app répond pendant l'opération."""
    lent = lambda: (time.sleep(0.4), "fini")[1]

    recus = []
    lance = fenetre.run_in_background(lent, recus.append, "Chargement…")
    assert lance

    # Pendant l'opération, la fenêtre répond toujours.
    assert fenetre.isEnabled(), "l'interface a été désactivée"
    assert fenetre.progress.isVisible(), "aucun indicateur de chargement"

    qtbot.waitUntil(lambda: bool(recus), timeout=5000)
    assert recus == ["fini"]


def test_the_progress_bar_disappears_afterwards(qtbot, fenetre):
    """Une barre qui resterait affichée ferait croire à un travail en cours."""
    recus = []
    fenetre.run_in_background(lambda: "ok", recus.append, "Chargement…")
    qtbot.waitUntil(lambda: bool(recus), timeout=5000)
    qtbot.waitUntil(lambda: not fenetre.progress.isVisible(), timeout=2000)


def test_the_progress_bar_disappears_on_failure(qtbot, fenetre):
    """Surtout en cas d'échec : sinon elle tourne indéfiniment."""
    def casse():
        raise RuntimeError("échec")

    recus = []
    fenetre.run_in_background(casse, recus.append, "Chargement…")
    qtbot.waitUntil(lambda: bool(recus), timeout=5000)
    qtbot.waitUntil(lambda: not fenetre.progress.isVisible(), timeout=2000)


def test_a_second_request_is_ignored(qtbot, fenetre):
    """§D60 : une seule opération à la fois, choix de l'utilisateur."""
    recus = []
    premier = fenetre.run_in_background(
        lambda: (time.sleep(0.3), "premier")[1], recus.append, "A"
    )
    second = fenetre.run_in_background(
        lambda: "second", recus.append, "B"
    )

    assert premier is True
    assert second is False, "la seconde demande aurait dû être ignorée"

    qtbot.waitUntil(lambda: bool(recus), timeout=5000)
    assert recus == ["premier"], "la première a été perturbée"


def test_another_request_works_once_finished(qtbot, fenetre):
    """Le verrou doit se relâcher, sinon plus rien ne marche ensuite."""
    recus = []
    fenetre.run_in_background(lambda: "un", recus.append, "A")
    qtbot.waitUntil(lambda: bool(recus), timeout=5000)

    assert fenetre.run_in_background(lambda: "deux", recus.append, "B")
    qtbot.waitUntil(lambda: len(recus) == 2, timeout=5000)
    assert recus == ["un", "deux"]


def test_the_result_arrives_on_the_main_thread(qtbot, fenetre):
    """La suite touche l'interface : elle doit être dans le bon fil.

    Qt interdit de modifier un widget hors du fil principal — et le
    plantage qui en résulte est intermittent, donc difficile à
    diagnostiquer après coup.
    """
    import threading

    principal = threading.get_ident()
    fils = []

    def suite(_):
        fils.append(threading.get_ident())

    fenetre.run_in_background(lambda: "ok", suite, "Chargement…")
    qtbot.waitUntil(lambda: bool(fils), timeout=5000)
    assert fils[0] == principal


def test_closing_during_an_operation_is_clean(qtbot, fenetre):
    """Le défaut de la phase 10 : « QThread destroyed while running »."""
    fenetre.run_in_background(
        lambda: (time.sleep(0.3), "ok")[1], lambda _: None, "Chargement…"
    )
    fenetre.close()          # ne doit pas lever
    assert True


# --- Les fenêtres lentes s'ouvrent sans geler ---------------------------


def test_opening_the_commit_window_does_not_freeze(qtbot, fenetre):
    """Mesuré sur le dépôt de l'utilisateur : `list_changes` 760 ms.

    La construction de `CommitWindow` la déclenche — c'est elle qui
    gelait l'interface « plusieurs minutes » avant les corrections de
    performance, et qui reste la plus coûteuse des ouvertures.
    """
    (__import__("pathlib").Path(fenetre.repository.workdir) / "a.txt").write_text(
        "modifie\n"
    )

    fenetre.open_commit_window()

    # L'ouverture est différée : la fenêtre arrive une fois le travail fait.
    qtbot.waitUntil(lambda: fenetre.commit_window is not None, timeout=5000)
    assert fenetre.commit_window.file_count() >= 1


def test_asking_twice_does_not_open_two_windows(qtbot, fenetre):
    """Deux fenêtres sur le même dépôt afficheraient des états divergents."""
    (__import__("pathlib").Path(fenetre.repository.workdir) / "a.txt").write_text(
        "modifie\n"
    )

    fenetre.open_commit_window()
    fenetre.open_commit_window()
    qtbot.waitUntil(lambda: fenetre.commit_window is not None, timeout=5000)

    fenetres = [
        e for e in fenetre.children()
        if type(e).__name__ == "CommitWindow"
    ]
    assert len(fenetres) == 1, f"{len(fenetres)} fenêtres de commit"


def test_an_already_open_window_is_raised_not_rebuilt(qtbot, fenetre):
    """Reconstruire repaierait le coût pour rien."""
    (__import__("pathlib").Path(fenetre.repository.workdir) / "a.txt").write_text(
        "modifie\n"
    )

    fenetre.open_commit_window()
    qtbot.waitUntil(lambda: fenetre.commit_window is not None, timeout=5000)
    premiere = fenetre.commit_window

    fenetre.open_commit_window()
    assert fenetre.commit_window is premiere
