"""Le rafraîchissement aussi passe en arrière-plan, avec le loader.

Demandé par l'utilisateur. `refresh()` enchaîne trois lectures dont le
coût croît avec le dépôt — mesuré sur le sien :

    build_graph     2185 ms   (ramené depuis, mais toujours le plus gros)
    read_state       436 ms
    unpushed_oids     56 ms

Deux pièges propres à `refresh` :

  - il est appelé depuis la FIN d'opérations déjà en arrière-plan
    (checkout, commit, fetch) : le verrou est alors pris, et lui
    refuser le passage laisserait le graphe périmé ;
  - l'affichage doit rester dans le FIL PRINCIPAL — Qt interdit de
    toucher aux widgets ailleurs.
"""

from __future__ import annotations

import subprocess

import pygit2
import pytest

from tortoisepy.ui.main_window import MainWindow


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

    # Préférences ISOLÉES : sans cela, les tests écrivent dans les
    # vraies préférences de l'utilisateur — vérifié, un essai avait
    # laissé `view/show_tags` à false dans sa configuration.
    from PySide6.QtCore import QSettings
    from tortoisepy.ui.settings_store import SettingsStore

    store = SettingsStore(
        QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    )
    fenetre = MainWindow(pygit2.Repository(str(w)), settings=store)
    qtbot.addWidget(fenetre)
    fenetre.show()
    return fenetre


def test_refreshing_shows_the_loader(qtbot, fenetre):
    """L'assertion centrale : un retour visuel pendant la lecture."""
    fenetre.refresh()

    assert fenetre.progress.isVisible(), "aucun indicateur de chargement"
    qtbot.waitUntil(lambda: not fenetre.progress.isVisible(), timeout=5000)


def test_the_graph_is_rebuilt(qtbot, fenetre):
    """Le loader ne doit rien changer au résultat."""
    avant = fenetre.view.scene()
    fenetre.refresh()

    qtbot.waitUntil(lambda: fenetre.view.scene() is not avant, timeout=5000)
    assert fenetre.graph is not None


def test_the_display_happens_on_the_main_thread(qtbot, fenetre):
    """Qt interdit de toucher aux widgets hors du fil principal, et le
    plantage qui en résulte est intermittent — donc difficile à
    diagnostiquer après coup."""
    import threading

    principal = threading.get_ident()
    fils = []
    vrai = fenetre.view.show_graph

    def observe(*a, **k):
        fils.append(threading.get_ident())
        return vrai(*a, **k)

    fenetre.view.show_graph = observe
    fenetre.refresh()

    qtbot.waitUntil(lambda: bool(fils), timeout=5000)
    assert fils[0] == principal


def test_a_refresh_after_a_background_action_still_happens(qtbot, fenetre):
    """Le piège : `refresh` est appelé depuis la FIN d'une opération de
    fond, quand le verrou est encore pris.

    Lui refuser le passage laisserait le graphe périmé après chaque
    checkout, commit ou fetch — exactement ce que le rafraîchissement
    doit empêcher.
    """
    avant = fenetre.view.scene()

    termine = []
    fenetre.run_in_background(
        lambda: "fini",
        lambda _: (termine.append(1), fenetre.refresh()),
        "Test…",
    )

    qtbot.waitUntil(lambda: bool(termine), timeout=5000)
    qtbot.waitUntil(lambda: fenetre.view.scene() is not avant, timeout=5000)


def test_the_loader_disappears_on_failure(qtbot, fenetre, monkeypatch):
    """Une barre qui resterait ferait croire à un travail en cours."""
    from tortoisepy.ui import main_window as module

    monkeypatch.setattr(module, "show_error", lambda *a, **k: None)

    def casse(repo):
        raise RuntimeError("lecture impossible")

    monkeypatch.setattr(module, "read_state", casse)
    fenetre.refresh()

    qtbot.waitUntil(lambda: not fenetre.progress.isVisible(), timeout=5000)


def test_the_scroll_position_is_still_preserved(qtbot, fenetre):
    """La garantie de la phase précédente ne doit pas tomber."""
    barre = fenetre.view.verticalScrollBar()
    if barre.maximum() == barre.minimum():
        pytest.skip("rien à faire défiler")

    fenetre.view.pan_by(0, barre.maximum() // 2)
    avant = barre.value()

    fenetre.refresh()
    qtbot.waitUntil(lambda: not fenetre.progress.isVisible(), timeout=5000)

    assert barre.value() == avant, "le rafraîchissement a déplacé la vue"


def test_toggling_show_tags_shows_the_loader(qtbot, fenetre):
    """Demandé par l'utilisateur. La bascule passe par `refresh`, donc
    elle hérite du loader — mais c'est le rafraîchissement le PLUS
    coûteux : changer le filtre invalide le cache du graphe, qui doit
    être reconstruit de zéro.
    """
    fenetre.show_tags_action.setChecked(False)

    assert fenetre.progress.isVisible(), (
        "aucun indicateur en basculant le filtre de tags"
    )
    qtbot.waitUntil(lambda: not fenetre.progress.isVisible(), timeout=5000)


def test_toggling_show_tags_rebuilds_the_graph(qtbot, tmp_path):
    """Le loader ne doit rien changer au résultat : le tag disparaît."""
    w = tmp_path / "w"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "a.txt").write_text("a\n")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "base")
    _git(w, "tag", "v1.0")

    from PySide6.QtCore import QSettings
    from tortoisepy.ui.settings_store import SettingsStore

    store = SettingsStore(
        QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    )
    fenetre = MainWindow(pygit2.Repository(str(w)), settings=store)
    fenetre.show()

    def noms():
        return {r.name for n in fenetre.graph.nodes for r in n.refs}

    assert "v1.0" in noms()

    fenetre.show_tags_action.setChecked(False)
    qtbot.waitUntil(lambda: "v1.0" not in noms(), timeout=5000)

    fenetre.show_tags_action.setChecked(True)
    qtbot.waitUntil(lambda: "v1.0" in noms(), timeout=5000)
