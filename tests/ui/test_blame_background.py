"""Le blâme se calcule en arrière-plan, loader compris.

Dernier écran de l'application à ignorer la règle posée par
l'utilisateur : « à chaque fois qu'une action est susceptible de faire
freezer l'app, on la fait en arrière-plan avec un loader ».

`blame_file` est l'opération la plus coûteuse de git : son prix suit le
nombre de commits ayant **touché le fichier**, pas la taille du dépôt.
Mesuré sur ce dépôt, et l'écart s'est creusé en trois jours de travail
sur le même fichier :

    ui/main_window.py    507 ms  ->  1980 ms
    core/operations.py                 97 ms

Sur un dépôt de plusieurs milliers de commits, un fichier ancien se
compte en dizaines de secondes. Or `_load` était appelé depuis
`__init__`, donc **avant que la fenêtre soit peinte** : elle s'ouvrait
grise et vide pendant tout le calcul.

Ces tests observent le FIL d'exécution, pas la barre de progression :
une barre « montrée » sans que Qt puisse la peindre satisfaisait les
tests de la fenêtre de commit tout en laissant l'interface gelée.
"""

from __future__ import annotations

import subprocess
import threading

import pygit2
import pytest

from tortoisepy.ui.blame_window import BlameWindow

ENV = {
    "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
    "PATH": "/usr/bin:/bin:/usr/local/bin",
}


def _git(chemin, *args, check=True):
    return subprocess.run(
        ["git", "-C", str(chemin), *args], check=check,
        capture_output=True, env=ENV, text=True,
    )


@pytest.fixture
def depot(tmp_path):
    """Un fichier modifié par deux commits : deux auteurs de lignes."""
    w = tmp_path / "w"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    cible = w / "module.py"
    cible.write_text("ligne un\n")
    _git(w, "add", ".")
    _git(w, "commit", "-qm", "base")

    cible.write_text("ligne un\nligne deux\n")
    _git(w, "add", ".")
    _git(w, "commit", "-qm", "ajoute")

    return pygit2.Repository(str(w))


@pytest.fixture
def fenetre(qtbot, depot):
    f = BlameWindow(depot, "module.py", str(depot.head.target))
    qtbot.addWidget(f)
    return f


def _attendre(qtbot, fenetre, timeout: int = 5000) -> None:
    """Attend la fin du calcul de fond."""
    def fini() -> bool:
        tache = getattr(fenetre, "_task", None)
        return tache is None or not tache.is_running()

    qtbot.waitUntil(fini, timeout=timeout)


# --- l'assertion centrale ------------------------------------------------


def test_the_blame_does_not_run_on_the_main_thread(qtbot, depot):
    """Le défaut : la fenêtre gelait pendant tout le calcul.

    On observe le FIL, pas la barre : une barre « montrée » sans que Qt
    puisse la peindre laisse l'interface figée tout en satisfaisant une
    assertion sur `isVisible()`.
    """
    from tortoisepy.ui import blame_window as module

    principal = threading.get_ident()
    fils = []
    vrai = module.blame_file

    def observe(*a, **k):
        fils.append(threading.get_ident())
        return vrai(*a, **k)

    module.blame_file = observe
    try:
        f = BlameWindow(depot, "module.py", str(depot.head.target))
        qtbot.addWidget(f)
        qtbot.waitUntil(lambda: bool(fils), timeout=5000)
        assert fils[0] != principal, "le blâme gèle la fenêtre"
        _attendre(qtbot, f)
    finally:
        module.blame_file = vrai


def test_the_window_opens_without_waiting(qtbot, depot):
    """`__init__` ne doit plus attendre le calcul.

    C'est ce qui faisait s'ouvrir la fenêtre grise et vide : le calcul
    se terminait avant le premier rendu.
    """
    from tortoisepy.ui import blame_window as module

    fini = []
    vrai = module.blame_file

    def lent(*a, **k):
        import time
        time.sleep(0.4)
        resultat = vrai(*a, **k)
        fini.append(1)
        return resultat

    module.blame_file = lent
    try:
        f = BlameWindow(depot, "module.py", str(depot.head.target))
        qtbot.addWidget(f)
        assert not fini, "le constructeur a attendu la fin du calcul"
        _attendre(qtbot, f)
    finally:
        module.blame_file = vrai


# --- le loader -----------------------------------------------------------


def test_the_loader_shows_then_disappears(qtbot, depot):
    """Un retour visuel pendant le calcul, et pas après."""
    f = BlameWindow(depot, "module.py", str(depot.head.target))
    qtbot.addWidget(f)
    f.show()

    assert f.progress.isVisible(), "aucun indicateur de chargement"
    _attendre(qtbot, f)
    qtbot.waitUntil(lambda: not f.progress.isVisible(), timeout=5000)


# --- le résultat ne change pas -------------------------------------------


def test_the_lines_are_still_listed(qtbot, fenetre):
    """L'arrière-plan ne doit rien changer à ce qui s'affiche."""
    _attendre(qtbot, fenetre)

    assert fenetre.line_count() == 2


def test_the_author_and_commit_are_shown(qtbot, fenetre):
    """Les colonnes restent remplies comme avant."""
    _attendre(qtbot, fenetre)

    premier = fenetre._lines.topLevelItem(0)
    assert premier.text(1) == "T", "l'auteur doit être affiché"
    assert premier.text(0), "l'abrégé du commit doit être affiché"


def test_the_display_happens_on_the_main_thread(qtbot, depot):
    """Qt interdit de toucher aux widgets hors du fil principal.

    Le plantage qui en résulte est intermittent, donc difficile à
    diagnostiquer après coup — d'où cette vérification explicite.
    """
    fils = []
    f = BlameWindow(depot, "module.py", str(depot.head.target))
    qtbot.addWidget(f)
    vrai = f._afficher

    def observe(resultat):
        fils.append(threading.get_ident())
        return vrai(resultat)

    f._afficher = observe
    f.reload()

    qtbot.waitUntil(lambda: bool(fils), timeout=5000)
    assert fils[0] == threading.get_ident()
    _attendre(qtbot, f)


# --- cas particuliers ----------------------------------------------------


def test_an_empty_file_still_says_so(qtbot, tmp_path):
    """Un fichier vide rend `()` : sans un mot, la fenêtre est muette.

    Comportement d'origine à préserver — il avait été ajouté parce que
    six fichiers de ce dépôt sont dans ce cas.
    """
    w = tmp_path / "vide"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "vide.txt").write_text("")
    _git(w, "add", ".")
    _git(w, "commit", "-qm", "base")

    repo = pygit2.Repository(str(w))
    f = BlameWindow(repo, "vide.txt", str(repo.head.target))
    qtbot.addWidget(f)
    f.show()
    _attendre(qtbot, f)

    assert f._message.isVisible()
    assert "vide" in f._message.text().lower()


def test_an_unknown_path_reports_the_error(qtbot, depot):
    """Un chemin absent doit le dire, pas rester vide."""
    f = BlameWindow(depot, "jamais-vu.py", str(depot.head.target))
    qtbot.addWidget(f)
    f.show()
    _attendre(qtbot, f)

    assert f._message.isVisible()
    assert f.line_count() == 0


def test_closing_waits_for_the_computation(qtbot, depot):
    """Fermer pendant le calcul détruirait le QThread en pleine exécution.

    « QThread: Destroyed while thread is still running » — le défaut déjà
    corrigé sur la fenêtre principale, celle de commit et le journal.

    On vérifie que le fil est ARRÊTÉ après la fermeture, pas seulement
    que `close()` ne lève pas : trouvé par mutation, retirer l'attente
    laissait le test au vert, parce que l'avertissement de Qt n'est pas
    une exception Python et que l'abandon du processus est intermittent.
    """
    from tortoisepy.ui import blame_window as module

    # Un calcul lent, pour que la fermeture tombe pendant son exécution.
    vrai = module.blame_file

    def lent(*a, **k):
        import time
        time.sleep(0.5)
        return vrai(*a, **k)

    module.blame_file = lent
    try:
        f = BlameWindow(depot, "module.py", str(depot.head.target))
        qtbot.addWidget(f)
        tache = f._task
        assert tache.is_running(), (
            "le calcul doit tourner, sinon le test ne prouve rien"
        )

        f.close()

        assert not tache.is_running(), (
            "le fil tourne encore après la fermeture : Qt le détruira "
            "en pleine exécution"
        )
    finally:
        module.blame_file = vrai


def test_destroying_during_the_computation_does_not_abort(qtbot, depot):
    """Et la destruction sans fermeture, qui faisait abandonner le processus.

    Le garde-fou vit dans `BackgroundTask` (signal `destroyed` du
    parent) : ce test vérifie que cette fenêtre en bénéficie aussi.
    """
    import gc

    f = BlameWindow(depot, "module.py", str(depot.head.target))
    del f
    gc.collect()      # ne doit pas abandonner le processus
