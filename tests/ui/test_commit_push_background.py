"""Le commit ET le push partent en arrière-plan, loader compris.

Signalé par l'utilisateur : « j'ai fait un commit and push et il n'y
avait pas le loader + processus en fond ».

Le loader ÉTAIT posé, mais tout le travail restait sur le fil principal :
Qt n'avait jamais la main pour peindre la barre — « montrée » sans jamais
devenir visible — et la fenêtre gelait jusqu'à la fin du push, qui
traverse le réseau.

Les tests d'alors passaient pour la mauvaise raison : ils relevaient
`progress.isVisible()` DEPUIS l'intérieur du travail synchrone, ce qui
prouve l'appel à `show()`, pas que l'interface reste vivante. Ceux-ci
observent le FIL d'exécution, seul témoin du dégel.

`commit_and_push` enchaîne deux tâches : le commit rend le verrou, puis
le push le reprend. D'où l'attente d'une accalmie plutôt que du premier
relâchement (cf. la fixture `attendre_la_fenetre`).
"""

import subprocess, threading
import pygit2, pytest
from tortoisepy.ui.commit_window import CommitWindow


def _git(c, *a):
    subprocess.run(["git", "-C", str(c), *a], check=False, capture_output=True,
        env={"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
             "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
             "PATH": "/usr/bin:/bin:/usr/local/bin"})


@pytest.fixture
def fenetre(qtbot, tmp_path, monkeypatch):
    from tortoisepy.ui import commit_window as module
    monkeypatch.setattr(module, "confirm", lambda *a, **k: True)

    distant = tmp_path / "d.git"
    subprocess.run(["git", "init", "-q", "--bare", str(distant)], check=True, capture_output=True)
    w = tmp_path / "w"
    subprocess.run(["git", "init", "-q", "-b", "main", str(w)], check=True, capture_output=True)
    (w / "a.txt").write_text("origine\n")
    _git(w, "add", "."); _git(w, "commit", "-q", "-m", "base")
    _git(w, "remote", "add", "origin", str(distant))
    _git(w, "push", "-q", "-u", "origin", "main")
    (w / "a.txt").write_text("modifie\n")

    f = CommitWindow(pygit2.Repository(str(w)))
    qtbot.addWidget(f); f.show(); f.set_message("un message")
    return f


def test_the_push_does_not_run_on_the_main_thread(qtbot, fenetre, attendre_la_fenetre):
    from tortoisepy.core import operations
    principal = threading.get_ident()
    fils = []
    vrai = operations.push_branch
    def observe(repo, *a, **k):
        fils.append(threading.get_ident())
        return vrai(repo, *a, **k)
    import tortoisepy.ui.commit_window as module
    module.operations.push_branch = observe
    try:
        fenetre.commit_and_push()
        qtbot.waitUntil(lambda: bool(fils), timeout=10000)
        assert fils[0] != principal, "le push gele l'interface"
        attendre_la_fenetre(qtbot, fenetre)
    finally:
        module.operations.push_branch = vrai


def test_commit_and_push_does_both(qtbot, fenetre, attendre_la_fenetre):
    repo = fenetre.repository
    avant = len(list(repo.walk(repo.head.target)))
    fenetre.commit_and_push()
    attendre_la_fenetre(qtbot, fenetre)
    qtbot.waitUntil(lambda: len(list(repo.walk(repo.head.target))) == avant + 1, timeout=10000)
    # le distant a bien recu
    local = str(repo.head.target)
    distant = str(repo.branches["origin/main"].target)
    assert local == distant, f"push non effectue: {local[:8]} != {distant[:8]}"


def test_the_loader_is_visible_during_the_push(qtbot, fenetre, attendre_la_fenetre):
    fenetre.commit_and_push()
    assert fenetre.progress.isVisible()
    attendre_la_fenetre(qtbot, fenetre)
    assert not fenetre.progress.isVisible(), "le loader reste apres le push"
