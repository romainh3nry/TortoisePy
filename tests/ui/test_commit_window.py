import os
import subprocess

import pygit2
import pytest
from PySide6.QtCore import Qt

from tortoisepy.ui.commit_window import CommitWindow


def run_git(path, *args):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
    }
    return subprocess.run(
        ["git", *args], cwd=path, env=env, capture_output=True, text=True
    )


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "fenetre"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "suivi.txt").write_text("base\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "base")

    (path / "suivi.txt").write_text("modifié\n")
    (path / "nouveau.txt").write_text("neuf\n")
    return pygit2.Repository(str(path))


@pytest.fixture
def window(qtbot, repo):
    w = CommitWindow(repo)
    qtbot.addWidget(w)
    # `isHidden()` d'une fenêtre jamais affichée vaut déjà `True` — sans ce
    # `show()`, les tests de fermeture/maintien de la fenêtre (plus bas)
    # seraient vrais par accident, avant même d'exécuter la logique testée.
    w.show()
    return w


def test_lists_the_changed_files(window):
    assert window.file_count() == 2


def test_tracked_file_is_checked(window):
    assert window.is_checked("suivi.txt") is True


def test_untracked_file_is_unchecked(window):
    """D8 : afficher sans cocher évite d'ajouter un `.env` par mégarde."""
    assert window.is_checked("nouveau.txt") is False


def test_selecting_a_file_shows_its_diff(window):
    window.select_file("suivi.txt")
    assert "modifié" in window.diff_view.text()


def test_commit_is_disabled_without_a_message(window):
    """§4.3 : un commit sans message est une dette immédiate."""
    window.set_message("")
    assert window.commit_button.isEnabled() is False


def test_commit_is_disabled_without_a_selection(window):
    window.set_message("un message")
    window.set_checked("suivi.txt", False)
    assert window.commit_button.isEnabled() is False


def test_commit_is_enabled_with_both(window):
    window.set_message("un message")
    assert window.commit_button.isEnabled() is True


def test_checking_a_box_writes_nothing(window, repo):
    """§5 : l'index n'est touché qu'au commit."""
    before = subprocess.run(
        ["git", "status", "--short"], cwd=repo.workdir,
        capture_output=True, text=True,
    ).stdout

    window.set_checked("nouveau.txt", True)
    window.set_checked("suivi.txt", False)

    after = subprocess.run(
        ["git", "status", "--short"], cwd=repo.workdir,
        capture_output=True, text=True,
    ).stdout
    assert before == after


def test_commit_creates_a_commit(qtbot, window, repo, attendre_la_fenetre):
    before = len(list(repo.walk(repo.head.target)))
    window.set_message("depuis la fenêtre")
    window.commit()
    attendre_la_fenetre(qtbot, window)
    assert len(list(repo.walk(repo.head.target))) == before + 1


def test_commit_uses_the_typed_message(
    qtbot, window, repo, attendre_la_fenetre
):
    window.set_message("message saisi")
    window.commit()
    attendre_la_fenetre(qtbot, window)
    assert repo.get(repo.head.target).message.strip() == "message saisi"


def test_commit_only_includes_checked_files(
    qtbot, window, repo, attendre_la_fenetre
):
    window.set_message("un seul fichier")
    window.set_checked("nouveau.txt", False)
    window.commit()
    attendre_la_fenetre(qtbot, window)

    commit = repo.get(repo.head.target)
    diff = repo.diff(commit.parents[0], commit)
    assert "nouveau.txt" not in {p.delta.new_file.path for p in diff}


def test_window_refreshes_after_a_commit(qtbot, window, attendre_la_fenetre):
    window.set_message("message")
    window.commit()
    attendre_la_fenetre(qtbot, window)
    # Le fichier commité (suivi.txt) disparaît ; nouveau.txt reste (non coché).
    assert window.file_count() == 1


def test_commit_survives_a_locked_index(
    qtbot, window, repo, monkeypatch, attendre_la_fenetre
):
    """Finding 2 (revue, tour 1) : l'échec de la resynchronisation ne doit
    jamais faire croire que le commit a échoué ou n'a pas eu lieu.

    Un `.git/index.lock` présent (git concurrent ou planté) fait lever
    `GitError` dans `_sync_index_after_commit`. Avant le correctif, cette
    exception s'échappait du slot Qt : `_after_commit` ne s'exécutait
    jamais, la fenêtre ne se rafraîchissait pas, et rien ne prévenait
    l'utilisateur que son commit — bien réel — avait eu lieu.
    """
    # `show_message` ouvrirait un `QMessageBox.information` bloquant : on le
    # neutralise comme le reste de la suite le fait pour `show_error`
    # (voir `tests/ui/test_main_window.py`), pour ne tester que le flux, pas
    # la boîte de dialogue elle-même.
    monkeypatch.setattr(
        "tortoisepy.ui.commit_window.show_message", lambda *a, **k: None
    )

    lock_path = os.path.join(repo.workdir, ".git", "index.lock")
    with open(lock_path, "w"):
        pass

    try:
        before = len(list(repo.walk(repo.head.target)))
        window.set_message("commit avec index verrouillé")

        window.commit()  # ne doit pas lever
        attendre_la_fenetre(qtbot, window)

        assert len(list(repo.walk(repo.head.target))) == before + 1
        # La fenêtre s'est bien rafraîchie malgré l'échec de la synchronisation :
        # le message est réinitialisé, preuve que `_after_commit` s'est exécuté.
        assert window.message() == ""
    finally:
        if os.path.exists(lock_path):
            os.remove(lock_path)


def test_conflicted_file_cannot_be_checked(qtbot, tmp_path):
    """Review Focus 2 : commiter un conflit produirait des marqueurs."""
    path = tmp_path / "conflit"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "f.txt").write_text("base\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "base")
    run_git(path, "checkout", "-q", "-b", "autre")
    (path / "f.txt").write_text("leur\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "leur")
    run_git(path, "checkout", "-q", "main")
    (path / "f.txt").write_text("notre\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "notre")
    run_git(path, "merge", "autre")

    w = CommitWindow(pygit2.Repository(str(path)))
    qtbot.addWidget(w)
    assert w.is_checkable("f.txt") is False


def test_conflicted_file_cannot_be_forced_via_set_checked(
    qtbot, tmp_path, attendre_la_fenetre
):
    """Finding 1 (revue, tour 1) : le flag Qt protège la souris, pas l'API.

    `set_checked` doit refuser de cocher un fichier non sélectionnable, et
    `checked_paths()` doit l'exclure même si la coche a quand même été
    posée par un autre chemin — sinon un conflit non résolu peut être
    commité, marqueurs `<<<<<<<` compris.
    """
    path = tmp_path / "conflit-force"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "f.txt").write_text("base\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "base")
    run_git(path, "checkout", "-q", "-b", "autre")
    (path / "f.txt").write_text("leur\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "leur")
    run_git(path, "checkout", "-q", "main")
    (path / "f.txt").write_text("notre\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "notre")
    run_git(path, "merge", "autre")
    # Un second fichier, sain, à côté du conflit : sans lui, `checked_paths()`
    # serait vide et `commit()` échouerait pour « nothing selected », ce qui
    # ouvrirait un `QMessageBox` bloquant sans rapport avec ce qu'on teste ici.
    (path / "sain.txt").write_text("ajout\n")

    w = CommitWindow(pygit2.Repository(str(path)))
    qtbot.addWidget(w)

    w.set_checked("f.txt", True)
    assert w.is_checked("f.txt") is False
    assert "f.txt" not in w.checked_paths()

    # Même en cochant la case Qt directement, sans passer par `set_checked` :
    # `checked_paths()` doit rester la seconde garde.
    item = w._item_for("f.txt")
    item.setCheckState(0, Qt.CheckState.Checked)
    assert "f.txt" not in w.checked_paths()

    w.set_checked("sain.txt", True)
    w.set_message("tentative sur un conflit")
    w.commit()
    attendre_la_fenetre(qtbot, w)

    repo = pygit2.Repository(str(path))
    commit = repo.get(repo.head.target)
    content = commit.tree["f.txt"].data.decode()
    assert "<<<<<<<" not in content
    assert "sain.txt" in {entry.name for entry in commit.tree}


def test_empty_repository_opens_without_crashing(qtbot, tmp_path):
    path = tmp_path / "vide"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")

    w = CommitWindow(pygit2.Repository(str(path)))
    qtbot.addWidget(w)
    assert w.file_count() == 0


def test_window_closes_after_a_successful_commit(
    qtbot, window, repo, attendre_la_fenetre
):
    window.set_message("un message")
    window.commit()
    attendre_la_fenetre(qtbot, window)
    assert window.isHidden() is True


def test_window_stays_open_after_a_failed_commit(
    qtbot, window, repo, monkeypatch, attendre_la_fenetre
):
    """Review Focus 4 : fermer ferait perdre la rédaction."""
    from tortoisepy.core.results import failed
    from tortoisepy.ui import commit_window as module

    monkeypatch.setattr(module, "show_error", lambda *a, **k: None)
    monkeypatch.setattr(
        module.operations,
        "commit_selection",
        lambda *a, **k: failed("Commit", "refus simulé"),
    )

    window.set_message("un message que je ne veux pas perdre")
    window.commit()
    attendre_la_fenetre(qtbot, window)

    assert window.isHidden() is False
    assert window.message() == "un message que je ne veux pas perdre"


def test_window_closes_when_commit_succeeds_but_push_fails(
    qtbot, window, repo, monkeypatch, attendre_la_fenetre
):
    """Review Focus 3 : le commit est acquis, donc on rend la main."""
    from tortoisepy.core.results import failed
    from tortoisepy.ui import commit_window as module

    monkeypatch.setattr(module, "confirm", lambda *a, **k: True)
    monkeypatch.setattr(module, "show_error", lambda *a, **k: None)
    monkeypatch.setattr(
        module.operations,
        "push_branch",
        lambda *a, **k: failed("Push", "rejeté par le serveur"),
    )

    window.set_message("un message")
    window.commit_and_push()
    attendre_la_fenetre(qtbot, window)

    assert window.isHidden() is True


def test_committed_signal_carries_the_push_result(
    qtbot, window, repo, monkeypatch, attendre_la_fenetre
):
    """La fenêtre principale doit pouvoir dire « poussé » ou « non poussé »."""
    from tortoisepy.core.results import succeeded
    from tortoisepy.ui import commit_window as module

    monkeypatch.setattr(module, "confirm", lambda *a, **k: True)
    monkeypatch.setattr(
        module.operations,
        "push_branch",
        lambda *a, **k: succeeded("Pushed main to origin"),
    )

    recus = []
    window.committed.connect(lambda *args: recus.append(args))
    window.set_message("un message")
    window.commit_and_push()
    attendre_la_fenetre(qtbot, window)

    assert recus, "le signal doit être émis"
    commit_result, push_result = recus[0]
    assert commit_result.success is True
    assert push_result is not None and push_result.success is True


def test_committed_signal_has_no_push_result_for_a_plain_commit(
    qtbot, window, repo, attendre_la_fenetre
):
    recus = []
    window.committed.connect(lambda *args: recus.append(args))
    window.set_message("un message")
    window.commit()
    attendre_la_fenetre(qtbot, window)

    assert recus
    commit_result, push_result = recus[0]
    assert commit_result.success is True
    assert push_result is None


# --- amend (tâche 3) ----------------------------------------------------


def _repo_with_one_commit(tmp_path):
    """Un dépôt local à un seul commit — HEAD y est amendable."""
    path = tmp_path / "amend"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "f.txt").write_text("base\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "message initial")
    return pygit2.Repository(str(path))


def test_ticking_amend_fills_in_the_last_message(window, repo):
    """Corriger une faute suppose de voir le message à corriger.

    Le fixture `repo` de ce fichier commite avec le message "base".
    """
    window.amend_box.setChecked(True)
    assert window.message().strip() == "base"


def test_unticking_amend_clears_the_borrowed_message(window, repo):
    """Le message emprunté ne doit pas se retrouver sur un commit neuf."""
    window.amend_box.setChecked(True)
    window.amend_box.setChecked(False)
    assert window.message().strip() == ""


def test_the_button_says_amend(window, repo):
    window.amend_box.setChecked(True)
    assert "Amender" in window.commit_button.text()
    window.amend_box.setChecked(False)
    assert window.commit_button.text() == "Commit"


def test_amend_is_disabled_on_a_detached_head(qtbot, tmp_path):
    """Et l'infobulle dit pourquoi, plutôt que de laisser deviner."""
    repo = _repo_with_one_commit(tmp_path)
    run_git(repo.workdir, "checkout", "-q", "--detach")

    fenetre = CommitWindow(pygit2.Repository(repo.path))
    qtbot.addWidget(fenetre)
    assert fenetre.amend_box.isEnabled() is False
    assert "detached" in fenetre.amend_box.toolTip().lower()


def test_amend_checkbox_alone_enables_the_button(window, repo):
    """Attention (brief) : en amend, le message seul suffit — corriger une
    faute ne touche aucun fichier. `_update_buttons` ne doit plus exiger un
    fichier coché quand `amend_box` est cochée.
    """
    window.amend_box.setChecked(True)
    for path in ("suivi.txt", "nouveau.txt"):
        window.set_checked(path, False)
    window._update_buttons()
    assert window.commit_button.isEnabled() is True


def test_ordinary_commit_still_requires_a_checked_file(window, repo):
    """Le cas ordinaire ne doit pas régresser : sans amend, un fichier coché
    reste obligatoire même avec un message.
    """
    window.set_message("un message")
    window.set_checked("suivi.txt", False)
    window.set_checked("nouveau.txt", False)
    assert window.commit_button.isEnabled() is False


def test_amending_commits_through_the_core(
    qtbot, window, repo, monkeypatch, attendre_la_fenetre
):
    from tortoisepy.ui import commit_window as module
    from tortoisepy.core.results import succeeded

    vus = []
    monkeypatch.setattr(
        module, "amend_commit",
        lambda repo, paths, message: vus.append((paths, message))
        or succeeded("Amended abc12345"),
    )
    window.amend_box.setChecked(True)
    window.set_message("corrige")
    window.commit()
    attendre_la_fenetre(qtbot, window)

    assert vus, "le cœur doit être appelé"
    assert vus[0][1] == "corrige"


def _clone_with_pushed_commit(tmp_path):
    """Un dépôt nu servant de serveur, et un clone dont HEAD est poussé."""
    bare = tmp_path / "serveur.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", str(bare)], capture_output=True
    )
    work = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", "-q", str(bare), str(work)], capture_output=True
    )
    (work / "f.txt").write_text("a\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "deja pousse")
    run_git(work, "push", "-q", "origin", "HEAD")
    return pygit2.Repository(str(work))


def test_commit_and_push_honours_the_amend_box(
    qtbot, tmp_path, monkeypatch, attendre_la_fenetre
):
    """Revue finale, Critical : il créait un SECOND commit, puis le poussait.

    Seul `commit()` consultait la case ; `commit_and_push()` appelait
    `commit_selection` sans condition. Reproduit : avec la case cochée,
    l'historique passait à deux commits — l'intention de l'utilisateur
    silencieusement inversée, et un mauvais commit envoyé au serveur.
    """
    from tortoisepy.core.results import failed
    from tortoisepy.ui import commit_window as module

    repo = _clone_with_pushed_commit(tmp_path)
    open(os.path.join(repo.workdir, "oublie.txt"), "w").write("o\n")

    monkeypatch.setattr(module, "confirm", lambda *a, **k: True)
    monkeypatch.setattr(module, "show_error", lambda *a, **k: None)
    monkeypatch.setattr(
        module.operations, "push_branch",
        lambda *a, **k: failed("Push", "hors ligne (test)"),
    )

    fenetre = CommitWindow(repo)
    qtbot.addWidget(fenetre)
    fenetre.amend_box.setChecked(True)
    fenetre.set_checked("oublie.txt", True)
    fenetre.set_message("faute corrigee")
    fenetre.commit_and_push()
    attendre_la_fenetre(qtbot, fenetre)

    fresh = pygit2.Repository(repo.path)
    messages = [c.message.strip() for c in fresh.walk(fresh.head.target)]
    assert messages == ["faute corrigee"], messages


def test_amending_a_pushed_commit_warns_about_force_push(qtbot, tmp_path):
    """Spec §3.4 : dire avant, plutôt que de laisser git dire après.

    Sans cet avertissement, l'utilisateur découvrait la divergence par un
    « non-fastforwardable » qu'il ne sait pas interpréter.
    """
    fenetre = CommitWindow(_clone_with_pushed_commit(tmp_path))
    qtbot.addWidget(fenetre)

    assert fenetre._last_commit_is_pushed() is True
    fenetre.amend_box.setChecked(True)
    assert "force with lease" in fenetre.amend_warning.text().lower()
    assert not fenetre.amend_warning.isHidden()

    fenetre.amend_box.setChecked(False)
    assert fenetre.amend_warning.isHidden()


def test_no_warning_on_a_repository_without_a_remote(qtbot, tmp_path):
    """Sans remote, `unpushed_oids` est vide et tout paraîtrait poussé."""
    fenetre = CommitWindow(_repo_with_one_commit(tmp_path))
    qtbot.addWidget(fenetre)

    assert fenetre._last_commit_is_pushed() is False
    fenetre.amend_box.setChecked(True)
    assert fenetre.amend_warning.isHidden()


def test_text_typed_in_amend_mode_survives_unticking(qtbot, tmp_path):
    """Revue finale, Minor : décocher effaçait ce qu'on venait d'écrire."""
    fenetre = CommitWindow(_repo_with_one_commit(tmp_path))
    qtbot.addWidget(fenetre)

    fenetre.set_message("mon brouillon precieux")
    fenetre.amend_box.setChecked(True)
    fenetre.set_message("je tape par dessus")
    fenetre.amend_box.setChecked(False)

    assert fenetre.message().strip() == "je tape par dessus"


def test_an_untouched_borrowed_message_is_still_given_back(qtbot, tmp_path):
    """L'inverse : ne pas garder un message emprunté sur un commit neuf."""
    fenetre = CommitWindow(_repo_with_one_commit(tmp_path))
    qtbot.addWidget(fenetre)

    fenetre.set_message("mon brouillon")
    fenetre.amend_box.setChecked(True)
    fenetre.amend_box.setChecked(False)

    assert fenetre.message().strip() == "mon brouillon"
