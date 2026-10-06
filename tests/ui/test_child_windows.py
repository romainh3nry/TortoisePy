"""Retenir les fenêtres filles sans les laisser s'accumuler.

Quatre listes et quatre méthodes `_forget_*` quasi identiques vivaient
dans `MainWindow`, qui atteignait 1999 lignes et 79 méthodes. C'est le
fichier où le plus de régressions sont apparues cette semaine — à cette
taille, on ne voit plus les interactions.

Le besoin est double et toujours le même :

  - **retenir** la fenêtre, sans quoi le ramasse-miettes la détruit
    aussitôt ouverte (piège vécu plusieurs fois dans ce projet) ;
  - **l'oublier** une fois fermée, sans quoi la liste grossit sans fin
    au fil d'une session — chaque fenêtre morte gardant son
    `Repository`, son arbre de fichiers et sa vue de diff.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from tortoisepy.ui.child_windows import ChildWindows


@pytest.fixture
def registre():
    return ChildWindows()


@pytest.fixture
def fenetre(qtbot):
    w = QWidget()
    qtbot.addWidget(w)
    return w


def test_a_new_registry_is_empty(registre):
    assert list(registre) == []
    assert len(registre) == 0


def test_adding_retains_the_window(registre, fenetre):
    """L'assertion centrale : sans référence, Qt détruit la fenêtre."""
    registre.add(fenetre)

    assert list(registre) == [fenetre]


def test_closing_forgets_the_window(qtbot, registre):
    """Sinon la liste grossit sans fin au fil d'une session.

    Chaque fenêtre fermée resterait vivante en mémoire avec tout ce
    qu'elle porte.
    """
    w = QWidget()
    qtbot.addWidget(w)
    w.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    registre.add(w)

    w.close()
    qtbot.waitUntil(lambda: len(registre) == 0, timeout=5000)


def test_forgetting_tolerates_a_destroyed_wrapper(registre, fenetre):
    """Un wrapper Python peut survivre à l'objet C++.

    Y toucher lève un `RuntimeError` de shiboken : c'est pourquoi on
    filtre sur la validité plutôt que de viser l'objet directement.
    """
    registre.add(fenetre)

    registre.forget(None)      # signal sans argument utilisable
    assert len(registre) == 1, "une fenêtre vivante ne doit pas disparaître"


def test_forgetting_twice_is_harmless(registre, fenetre):
    """Le signal `destroyed` peut arriver deux fois."""
    registre.add(fenetre)

    registre.forget(fenetre)
    registre.forget(fenetre)

    assert len(registre) == 0


def test_several_windows_coexist(qtbot, registre):
    """Comparer deux commits côte à côte est un usage légitime."""
    fenetres = []
    for _ in range(3):
        w = QWidget()
        qtbot.addWidget(w)
        registre.add(w)
        fenetres.append(w)

    assert len(registre) == 3


def test_the_last_window_is_reachable(registre, qtbot):
    """Les tests et le code visent souvent la dernière ouverte."""
    premier, second = QWidget(), QWidget()
    qtbot.addWidget(premier)
    qtbot.addWidget(second)
    registre.add(premier)
    registre.add(second)

    assert registre.last() is second


def test_the_last_of_an_empty_registry_is_none(registre):
    """Ne pas lever : le code appelant teste souvent la présence."""
    assert registre.last() is None


# --- le branchement dans la fenêtre principale --------------------------


def test_the_main_window_uses_the_registry(qtbot, tmp_path):
    """Les quatre listes doivent passer par le même mécanisme.

    Sans cela, l'extraction n'aurait rien simplifié : le code dupliqué
    serait resté, avec une classe inutilisée à côté.
    """
    import subprocess

    import pygit2

    from tortoisepy.ui.main_window import MainWindow

    w = tmp_path / "w"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "a.txt").write_text("a\n")
    env = {
        "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
        "PATH": "/usr/bin:/bin:/usr/local/bin",
    }
    for args in (["add", "."], ["commit", "-qm", "base"]):
        subprocess.run(
            ["git", "-C", str(w), *args], check=True, capture_output=True,
            env=env,
        )

    fenetre = MainWindow(pygit2.Repository(str(w)))
    qtbot.addWidget(fenetre)

    for nom in (
        "_detail_windows", "_log_windows", "_compare_windows",
        "_recent_windows",
    ):
        assert isinstance(getattr(fenetre, nom), ChildWindows), (
            f"« {nom} » n'utilise pas le registre"
        )


def test_opening_a_detail_still_retains_it(qtbot, tmp_path):
    """L'extraction ne doit rien changer au comportement observable."""
    import subprocess

    import pygit2

    from tortoisepy.ui.main_window import MainWindow

    w = tmp_path / "detail"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "a.txt").write_text("a\n")
    env = {
        "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
        "PATH": "/usr/bin:/bin:/usr/local/bin",
    }
    for args in (["add", "."], ["commit", "-qm", "base"]):
        subprocess.run(
            ["git", "-C", str(w), *args], check=True, capture_output=True,
            env=env,
        )

    repo = pygit2.Repository(str(w))
    fenetre = MainWindow(repo)
    qtbot.addWidget(fenetre)
    fenetre.open_commit_detail(str(repo.head.target))

    assert len(fenetre._detail_windows) == 1
    assert fenetre._detail_windows.last().isVisible()


def test_an_empty_registry_equals_an_empty_list(registre):
    """`== []` doit fonctionner : c'est ainsi que le code existant teste.

    Quatre tests comparaient les listes à `[]` avant l'extraction.
    Casser cette comparaison aurait obligé à les réécrire sans qu'aucun
    comportement n'ait changé — le remaniement aurait alors coûté plus
    qu'il ne simplifie.
    """
    assert registre == []


def test_a_filled_registry_equals_its_contents(registre, qtbot):
    """Et la comparaison garde son sens quand le registre est plein."""
    w = QWidget()
    qtbot.addWidget(w)
    registre.add(w)

    assert registre == [w]
    assert registre != []
