import os
import subprocess

import pygit2
import pytest

from tortoisepy.ui.main_window import MainWindow


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
    path = tmp_path / "win"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "master")
    (path / "f.txt").write_text("base\n")
    run_git(path, "add", "f.txt")
    run_git(path, "commit", "-q", "-m", "base")
    run_git(path, "checkout", "-q", "-b", "feature")
    (path / "g.txt").write_text("feature\n")
    run_git(path, "add", "g.txt")
    run_git(path, "commit", "-q", "-m", "feature")
    run_git(path, "checkout", "-q", "master")
    return pygit2.Repository(str(path))


@pytest.fixture
def window(qtbot, repo):
    w = MainWindow(repo)
    qtbot.addWidget(w)
    return w


def test_window_opens(window):
    assert window.isEnabled()


def test_window_title_names_the_repository(window):
    assert "win" in window.windowTitle()


def test_graph_is_displayed(window):
    assert len(window.view.scene().items()) > 0


def test_toolbar_exists(window):
    """§4.3 : la toolbar de la capture — zoom, ajustement."""
    assert window.findChildren(type(window.toolbar)) != []


def test_refresh_rebuilds_the_graph(window):
    before = window.view.scene()
    window.refresh()
    assert window.view.scene() is not before


def test_state_is_read_on_open(window):
    assert window.state is not None
    assert window.state.head_branch == "master"


def test_refresh_updates_state_after_external_change(window, repo):
    path = repo.workdir
    run_git(path, "checkout", "-q", "feature")
    window.refresh()
    assert window.state.head_branch == "feature"


def test_status_bar_shows_the_branch(window):
    assert "master" in window.statusBar().currentMessage()


def test_watcher_is_running(window):
    assert window.watcher.is_watching()


def test_closing_stops_the_watcher(window):
    window.close()
    assert not window.watcher.is_watching()


def test_zoom_actions_exist(window):
    names = {action.text() for action in window.actions()}
    assert any("100" in name or "Zoom" in name for name in names)


def test_empty_repository_does_not_crash(qtbot, tmp_path):
    """Un dépôt sans commit doit s'ouvrir sans planter."""
    path = tmp_path / "vide"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "master")
    w = MainWindow(pygit2.Repository(str(path)))
    qtbot.addWidget(w)
    assert w.view.scene() is not None


def test_commit_panel_starts_on_the_current_branch(window):
    """Change de comportement (demandé par l'utilisateur) : la branche
    courante est sélectionnée à l'ouverture, donc ses commits s'affichent
    sans qu'on ait à cliquer."""
    assert window.commit_panel.count() > 0
    assert window.view.selected_oids() == (window.state.head_oid,)


def test_double_click_shows_the_hidden_commits(window):
    """§4.2.1 : ce que la compression masque doit rester atteignable."""
    node = next(
        n for n in window.graph.nodes
        if any(r.name == "feature" for r in n.refs)
    )
    window._show_commits(node.oid)
    assert window.commit_panel.count() > 0


def test_double_click_titles_the_panel_with_the_branch(window):
    node = next(
        n for n in window.graph.nodes
        if any(r.name == "feature" for r in n.refs)
    )
    window._show_commits(node.oid)
    assert "feature" in window.commit_panel._title.text()


def test_double_click_on_unknown_node_is_ignored(window):
    window.commit_panel.clear()
    window._show_commits("0" * 40)  # ne doit pas lever
    assert window.commit_panel.count() == 0


def test_refresh_returns_the_focus_to_the_current_branch(window):
    """Reconstruire le graphe invalide le panneau, puis la sélection
    revient sur la branche courante — le repère de l'utilisateur."""
    node = next(
        n for n in window.graph.nodes
        if any(r.name == "feature" for r in n.refs)
    )
    window._show_commits(node.oid)
    assert "feature" in window.commit_panel._title.text()

    window.refresh()
    assert window.view.selected_oids() == (window.state.head_oid,)
    assert "feature" not in window.commit_panel._title.text()


def test_view_and_panel_share_a_splitter(window):
    """La répartition graphe / commits doit rester ajustable."""
    assert window.splitter.count() == 2


def _node_item(window, branch: str):
    from tortoisepy.ui.graph_items import NodeItem

    return next(
        item
        for item in window.view.scene().items()
        if isinstance(item, NodeItem)
        and any(r.name == branch for r in item.node.refs)
    )


def test_single_click_shows_the_commits(window):
    """Sélectionner un nœud suffit : c'est le même geste.

    La scène est vidée d'abord : la branche courante est sélectionnée à
    l'ouverture, et `setSelected` **cumule** (contrairement à un clic
    souris, où Qt efface d'abord). Sans cela on testerait deux nœuds.
    """
    window.view.scene().clearSelection()
    _node_item(window, "feature").setSelected(True)
    assert window.commit_panel.count() > 0
    assert "feature" in window.commit_panel._title.text()


def test_two_selected_nodes_clear_the_panel(window):
    """Avec deux nœuds, le menu bascule sur la comparaison (§7.4) :
    montrer les commits de l'un des deux serait arbitraire."""
    window.view.scene().clearSelection()
    _node_item(window, "feature").setSelected(True)
    assert window.commit_panel.count() > 0

    _node_item(window, "master").setSelected(True)
    assert window.commit_panel.count() == 0


def test_returning_to_one_selection_shows_commits_again(window):
    feature = _node_item(window, "feature")
    master = _node_item(window, "master")

    feature.setSelected(True)
    master.setSelected(True)
    assert window.commit_panel.count() == 0

    feature.setSelected(False)
    assert window.commit_panel.count() > 0
    assert "master" in window.commit_panel._title.text()


def test_deselecting_everything_clears_the_panel(window):
    window.view.scene().clearSelection()
    item = _node_item(window, "feature")
    item.setSelected(True)
    assert window.commit_panel.count() > 0

    item.setSelected(False)
    assert window.commit_panel.count() == 0


def test_view_opens_centred_on_the_current_branch(window):
    """Sur un gros dépôt, le graphe dépasse les 20 000 px de haut :
    s'ouvrir en haut place l'utilisateur loin de sa branche courante.

    Le viewport d'une fenêtre jamais affichée mesure quelques pixels : on
    vérifie donc que le centrage a bien VISÉ le nœud, en comparant le
    centre du viewport à sa position, plutôt que d'exiger qu'il y tienne.
    """
    from tortoisepy.ui.graph_items import NodeItem

    head = window.state.head_oid
    assert head is not None

    item = next(
        i for i in window.view.scene().items()
        if isinstance(i, NodeItem) and i.node.oid == head
    )
    viewport = window.view.viewport().rect()
    centre = window.view.mapToScene(viewport.center())
    target = item.sceneBoundingRect().center()

    assert abs(centre.x() - target.x()) < 50.0
    assert abs(centre.y() - target.y()) < 50.0


def test_centring_survives_a_refresh(window):
    from tortoisepy.ui.graph_items import NodeItem

    window.view.centerOn(0, 0)
    window.refresh()

    item = next(
        i for i in window.view.scene().items()
        if isinstance(i, NodeItem) and i.node.oid == window.state.head_oid
    )
    centre = window.view.mapToScene(window.view.viewport().rect().center())
    target = item.sceneBoundingRect().center()
    assert abs(centre.y() - target.y()) < 50.0


def test_centring_on_an_unknown_node_is_harmless(window):
    assert window.view.center_on_node("0" * 40) is False


def test_empty_repository_centres_without_crashing(qtbot, tmp_path):
    from tortoisepy.ui.main_window import MainWindow
    import pygit2

    path = tmp_path / "vide-centre"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "master")

    w = MainWindow(pygit2.Repository(str(path)))
    qtbot.addWidget(w)
    assert w.state.head_oid is None


def test_menu_action_runs_the_operation(window, monkeypatch):
    """Le menu n'affiche plus « pas encore câblé »."""
    from tortoisepy.ui import actions

    called = []
    monkeypatch.setattr(
        actions, "execute_action",
        lambda action, ctx: called.append(action) or None,
    )

    node = next(
        n for n in window.graph.nodes
        if any(r.name == "feature" for r in n.refs)
    )
    window._run_action("checkout_branch", node)
    assert called == ["checkout_branch"]


def test_successful_action_refreshes_the_graph(window, monkeypatch):
    from tortoisepy.core.results import succeeded
    from tortoisepy.ui import actions

    monkeypatch.setattr(
        actions, "execute_action", lambda action, ctx: succeeded("fait")
    )
    before = window.view.scene()

    node = window.graph.nodes[0]
    window._run_action("checkout_branch", node)

    assert window.view.scene() is not before


def test_failed_action_still_refreshes_when_the_repo_changed(
    window, monkeypatch
):
    """§7.6 : un merge en conflit échoue mais a modifié le dépôt."""
    from tortoisepy.core.results import failed
    from tortoisepy.ui import actions

    monkeypatch.setattr(
        actions, "execute_action",
        lambda action, ctx: failed("Fusion", "conflits", repository_changed=True),
    )
    monkeypatch.setattr(
        "tortoisepy.ui.main_window.show_error", lambda parent, result: None
    )
    before = window.view.scene()

    window._run_action("merge_branch", window.graph.nodes[0])
    assert window.view.scene() is not before


def test_cancelled_action_does_not_refresh(window, monkeypatch):
    from tortoisepy.ui import actions

    monkeypatch.setattr(actions, "execute_action", lambda action, ctx: None)
    before = window.view.scene()

    window._run_action("create_branch", window.graph.nodes[0])
    assert window.view.scene() is before


def test_watcher_is_suspended_during_an_action(window, monkeypatch):
    """§7.9 : l'application ne doit pas se notifier elle-même."""
    from tortoisepy.core.results import succeeded
    from tortoisepy.ui import actions

    seen = []
    monkeypatch.setattr(
        actions, "execute_action",
        lambda action, ctx: seen.append(window.watcher._suspended)
        or succeeded("fait"),
    )

    window._run_action("checkout_branch", window.graph.nodes[0])
    assert seen == [True], "la surveillance doit être suspendue"


def test_progress_bar_is_hidden_at_rest(window):
    # `isHidden()` plutôt que `isVisible()` : ce dernier vaut False tant
    # que la fenêtre parente n'est pas affichée, ce qui n'arrive jamais
    # en test offscreen.
    assert window.progress.isHidden() is True


def test_fetch_shows_the_progress_bar(window, monkeypatch):
    """Sans indicateur, rien ne montre que le fetch tourne."""
    from tortoisepy.core import operations
    from tortoisepy.core.results import succeeded

    monkeypatch.setattr(
        operations, "fetch_remote",
        lambda repo, on_progress=None: succeeded("fini", repository_changed=False),
    )

    window._start_fetch()
    assert window.progress.isHidden() is False
    assert window._task is not None
    window._task.wait(5000)


def test_fetch_hides_the_bar_when_done(window, qtbot, monkeypatch):
    from tortoisepy.core import operations
    from tortoisepy.core.results import succeeded

    monkeypatch.setattr(
        operations, "fetch_remote",
        lambda repo, on_progress=None: succeeded("fini", repository_changed=False),
    )

    window._start_fetch()
    qtbot.waitUntil(lambda: not window._task.is_running(), timeout=5000)
    qtbot.wait(100)
    assert window.progress.isHidden() is True


def test_fetch_reports_what_arrived(window, qtbot, monkeypatch):
    """La barre d'état nomme les refs, pas seulement « terminé »."""
    from tortoisepy.core import operations
    from tortoisepy.core.results import succeeded

    monkeypatch.setattr(
        operations, "fetch_remote",
        lambda repo, on_progress=None: succeeded(
            "Fetched from origin — new: origin/feature, v2.0",
            repository_changed=False,
        ),
    )

    window._start_fetch()
    qtbot.waitUntil(lambda: not window._task.is_running(), timeout=5000)
    qtbot.wait(100)
    assert "origin/feature" in window.statusBar().currentMessage()


def test_second_fetch_is_refused_while_one_runs(window, monkeypatch):
    """Deux fetchs simultanés se marcheraient dessus."""
    import time
    from tortoisepy.core import operations
    from tortoisepy.core.results import succeeded

    def slow(repo, on_progress=None):
        time.sleep(0.3)
        return succeeded("fini", repository_changed=False)

    monkeypatch.setattr(operations, "fetch_remote", slow)

    window._start_fetch()
    first = window._task
    window._start_fetch()
    assert window._task is first, "aucun second fil ne doit démarrer"
    first.wait(5000)


def test_watcher_restarts_after_a_fetch(window, qtbot, monkeypatch):
    """§7.9 : la surveillance reprend une fois le fetch terminé."""
    from tortoisepy.core import operations
    from tortoisepy.core.results import succeeded

    monkeypatch.setattr(
        operations, "fetch_remote",
        lambda repo, on_progress=None: succeeded("fini", repository_changed=False),
    )

    window._start_fetch()
    qtbot.waitUntil(lambda: not window._task.is_running(), timeout=5000)
    qtbot.wait(100)
    assert window.watcher.is_watching() is True


def test_commit_window_opens(qtbot, window):
    """L'ouverture est DIFFÉRÉE depuis la phase 24 : `list_changes` coûte
    760 ms sur un dépôt réel, et le payer dans le fil principal gelait
    l'application. L'exigence est inchangée — la fenêtre s'ouvre — seul
    le moment a bougé."""
    window.open_commit_window()
    qtbot.waitUntil(lambda: window.commit_window is not None, timeout=5000)
    window.commit_window.close()


def test_commit_window_is_reused(qtbot, window):
    """Deux fenêtres de commit sur le même dépôt se contrediraient."""
    window.open_commit_window()
    qtbot.waitUntil(lambda: window.commit_window is not None, timeout=5000)
    first = window.commit_window
    window.open_commit_window()
    assert window.commit_window is first
    first.close()


def test_graph_refreshes_after_a_commit(qtbot, window, monkeypatch):
    from tortoisepy.core.results import succeeded

    window.open_commit_window()
    qtbot.waitUntil(lambda: window.commit_window is not None, timeout=5000)
    before = window.view.scene()
    window.commit_window.committed.emit(succeeded("fait"), None)
    assert window.view.scene() is not before
    window.commit_window.close()


def test_commit_action_is_in_the_menu():
    """L'entrée doit exister, sinon la fonction est inatteignable."""
    from tortoisepy.core.model import DisplayNode, NodeKind, Ref, RefType
    from tortoisepy.core.state import RepositoryState
    from tortoisepy.ui.context_menu import build_menu_model

    node = DisplayNode(
        oid="a" * 40,
        kind=NodeKind.REF,
        refs=(Ref("feature", RefType.LOCAL_BRANCH, "a" * 40),),
    )
    state = RepositoryState(
        head_oid="b" * 40, head_branch="master", detached=False,
        has_unstaged_changes=True, has_staged_changes=False,
        has_conflicts=False, operation_in_progress=None, conflicted_paths=(),
    )

    def actions(entries):
        for entry in entries:
            if entry.action:
                yield entry.action
            yield from actions(entry.children)

    assert "open_commit" in set(actions(build_menu_model((node,), state)))


def test_fetch_summary_survives_the_refresh(window, qtbot, monkeypatch):
    """Le résumé doit rester affiché APRÈS la reconstruction du graphe.

    `refresh()` appelle `_update_status()`, qui écrit « Sur <branche> ».
    Afficher le résumé avant le rafraîchissement le faisait disparaître
    sans qu'il soit lu — d'autant plus sur un gros dépôt, où la
    reconstruction prend plusieurs secondes.
    """
    from tortoisepy.core import operations
    from tortoisepy.core.results import succeeded

    monkeypatch.setattr(
        operations, "fetch_remote",
        lambda repo, on_progress=None: succeeded(
            "Fetched from origin — new: origin/feature, v2.0",
            repository_changed=True,
        ),
    )

    window._start_fetch()
    qtbot.waitUntil(lambda: not window._task.is_running(), timeout=10000)
    qtbot.wait(100)

    message = window.statusBar().currentMessage()
    assert "origin/feature" in message
    assert "v2.0" in message


def test_status_bar_reports_a_commit(window):
    from tortoisepy.core.results import succeeded

    window._on_committed(succeeded("Committed 2 files — a1b2c3d4"), None)
    assert "Committed 2 files" in window.statusBar().currentMessage()


def test_status_bar_reports_a_commit_and_push(window):
    from tortoisepy.core.results import succeeded

    window._on_committed(
        succeeded("Committed 2 files — a1b2c3d4"),
        succeeded("Pushed main to origin"),
    )
    message = window.statusBar().currentMessage()
    assert "Committed 2 files" in message
    assert "push" in message.lower()


def test_status_bar_says_when_the_push_failed(window):
    """Review Focus 3 : le commit est fait, l'utilisateur doit le savoir."""
    from tortoisepy.core.results import failed, succeeded

    window._on_committed(
        succeeded("Committed 2 files — a1b2c3d4"),
        failed("Push", "rejeté par le serveur"),
    )
    message = window.statusBar().currentMessage()
    assert "Committed 2 files" in message
    assert "fail" in message.lower() or "échou" in message.lower()


def test_a_failed_commit_does_not_claim_success(window, monkeypatch):
    from tortoisepy.core.results import failed
    from tortoisepy.ui import main_window as module

    monkeypatch.setattr(module, "show_error", lambda *a, **k: None)
    window._on_committed(failed("Commit", "rien de coché"), None)
    assert "Committed" not in window.statusBar().currentMessage()


def test_closed_detail_windows_are_released(window, qtbot):
    """`_detail_windows` ne doit garder que les fenêtres encore ouvertes.

    Inspecter des commits est l'usage prévu de cette fenêtre : sans retrait
    au fil de l'eau, la liste grossirait sans fin pendant une session, en
    retenant à chaque fois un `Repository`, un arbre de fichiers et un
    `DiffView` déjà fermés à l'écran.
    """
    oid = str(window.repository.head.target)

    for _ in range(10):
        window.open_commit_detail(oid)

    assert len(window._detail_windows) == 10

    for detail in list(window._detail_windows):
        detail.close()

    # `WA_DeleteOnClose` planifie la destruction via `deleteLater()` : elle
    # n'a lieu qu'au prochain passage de la boucle d'événements, pas dans
    # `close()` lui-même. `waitUntil` laisse Qt la traiter.
    qtbot.waitUntil(lambda: window._detail_windows == [], timeout=1000)


def test_push_action_exists(window):
    assert window.push_action is not None
    assert window.push_action.text() == "Push"


def test_push_is_disabled_without_a_remote(window):
    """Le dépôt de test n'a pas de remote."""
    window._update_push_action()
    assert window.push_action.isEnabled() is False


def test_disabled_push_explains_why(window):
    window._update_push_action()
    assert window.push_action.toolTip()


def test_push_is_enabled_when_there_is_something_to_push(window, monkeypatch):
    from tortoisepy.core.push_state import PushState
    from tortoisepy.ui import main_window as module

    monkeypatch.setattr(
        module,
        "push_state",
        lambda repo: PushState(
            branch="main", remote_name="origin", unpushed_count=2, can_push=True
        ),
    )
    window._update_push_action()
    assert window.push_action.isEnabled() is True


def test_push_refuses_when_already_running(window, monkeypatch):
    from tortoisepy.ui import main_window as module

    monkeypatch.setattr(module, "confirm", lambda *a, **k: True)

    class Busy:
        def is_running(self):
            return True

    window._task = Busy()
    window._start_push()
    assert "running" in window.statusBar().currentMessage().lower()


def test_push_asks_for_confirmation(window, monkeypatch):
    """§6.3 : pousser sort de la machine, donc on confirme."""
    from tortoisepy.ui import main_window as module

    demandes = []
    monkeypatch.setattr(
        module, "confirm", lambda *a, **k: demandes.append(a) or False
    )
    window._task = None
    window._start_push()
    assert demandes, "aucune confirmation demandée"


def test_pull_action_exists(window):
    assert window.pull_action is not None
    assert window.pull_action.text() == "Pull"


def test_pull_is_disabled_without_a_remote(window):
    window._update_pull_action()
    assert window.pull_action.isEnabled() is False


def test_disabled_pull_explains_why(window):
    window._update_pull_action()
    assert window.pull_action.toolTip()


def test_pull_is_enabled_when_something_is_incoming(window, monkeypatch):
    from tortoisepy.core.pull import PullKind, PullState
    from tortoisepy.ui import main_window as module

    monkeypatch.setattr(
        module,
        "analyse_pull",
        lambda repo: PullState(
            PullKind.FAST_FORWARD, branch="main",
            remote_name="origin", incoming=3,
        ),
    )
    window._update_pull_action()
    assert window.pull_action.isEnabled() is True


def test_pull_refuses_when_a_task_is_running(window):
    class Busy:
        def is_running(self):
            return True

    window._task = Busy()
    window._start_pull()
    assert "running" in window.statusBar().currentMessage().lower()


def test_pull_reports_its_result(window):
    from tortoisepy.core.results import succeeded

    window._on_pull_finished(succeeded("Pulled 3 commits from origin"))
    assert "Pulled 3 commits" in window.statusBar().currentMessage()


def test_pull_conflict_opens_the_resolution_window(window, monkeypatch):
    """Un conflit n'est pas une impasse : la fenêtre doit s'ouvrir."""
    from tortoisepy.core.results import failed
    from tortoisepy.ui import main_window as module

    ouvertes = []
    monkeypatch.setattr(
        module.MainWindow, "open_conflict_window",
        lambda self: ouvertes.append(True),
    )
    monkeypatch.setattr(module, "show_error", lambda *a, **k: None)

    window._on_pull_finished(failed("Pull", "conflicts in: f.txt"))
    assert ouvertes, "la fenêtre de résolution doit s'ouvrir"


def test_open_detail_windows_stay_referenced(window):
    """À l'inverse : une fenêtre encore ouverte ne doit pas disparaître.

    C'est le piège inverse, déjà rencontré dans ce projet avec
    `BackgroundTask` : sans référence retenue, le ramasse-miettes Python
    fermerait la fenêtre aussitôt créée.
    """
    oid = str(window.repository.head.target)

    window.open_commit_detail(oid)

    assert len(window._detail_windows) == 1
    assert not window._detail_windows[0].isHidden()
    window._detail_windows[0].close()


def test_pull_stays_enabled_when_nothing_is_known_yet(window, monkeypatch):
    """Revue finale, phase 8 : les commits entrants ne sont pas connaissables
    sans fetch. Griser le bouton sur `analyse_pull` affichait
    « Already up to date » alors qu'un pull ramènerait du travail — le cas
    courant signalé par l'utilisateur.
    """
    from tortoisepy.core.pull import PullKind, PullState
    from tortoisepy.ui import main_window as module

    monkeypatch.setattr(
        module,
        "analyse_pull",
        lambda repo: PullState(
            PullKind.UP_TO_DATE, branch="main", remote_name="origin"
        ),
    )
    window._update_pull_action()

    assert window.pull_action.isEnabled() is True
    assert "up to date" not in window.pull_action.toolTip().lower()


def test_pull_is_disabled_without_a_remote(window, monkeypatch):
    from tortoisepy.core.pull import PullKind, PullState
    from tortoisepy.ui import main_window as module

    monkeypatch.setattr(
        module,
        "analyse_pull",
        lambda repo: PullState(PullKind.UNAVAILABLE, reason="no remote"),
    )
    window._update_pull_action()
    assert window.pull_action.isEnabled() is False
    assert window.pull_action.toolTip()


def test_a_rolled_back_rebase_does_not_open_an_empty_window(
    window, monkeypatch
):
    """Revue finale : le message porte « conflict » alors que tout a été
    restauré. Ouvrir la fenêtre montrait une liste vide avec « Resolve »
    actif, et cachait le conseil « try merge instead ».
    """
    from tortoisepy.core.results import failed
    from tortoisepy.ui import main_window as module

    ouvertes = []
    monkeypatch.setattr(
        module.MainWindow,
        "open_conflict_window",
        lambda self: ouvertes.append(True),
    )
    monkeypatch.setattr(module, "show_error", lambda *a, **k: None)

    window._on_pull_finished(
        failed(
            "Pull",
            "conflicts in: f.txt (rebase rolled back, branch restored "
            "— try merge instead)",
        )
    )
    assert not ouvertes, "aucune fenêtre ne doit s'ouvrir : rien à résoudre"


def test_a_real_conflict_still_opens_the_window(window, monkeypatch):
    """La garde ci-dessus ne doit pas fermer la porte au vrai cas."""
    from tortoisepy.core.results import failed
    from tortoisepy.ui import main_window as module

    ouvertes = []
    monkeypatch.setattr(
        module.MainWindow,
        "open_conflict_window",
        lambda self: ouvertes.append(True),
    )
    monkeypatch.setattr(module, "show_error", lambda *a, **k: None)

    window._on_pull_finished(failed("Pull", "conflicts in: f.txt"))
    assert ouvertes


def test_the_current_branch_is_always_visible(window):
    """Demandé par l'utilisateur : savoir en permanence où l'on est."""
    assert window.branch_label.text()
    assert window.state.head_branch in window.branch_label.text()


def test_the_branch_survives_a_temporary_message(window):
    """Un widget permanent n'est pas recouvert par `showMessage`.

    C'était le défaut : après un commit, un pull ou un push, le message
    temporaire écrasait « Sur <branche> » et la branche disparaissait.
    """
    from tortoisepy.core.results import succeeded

    avant = window.branch_label.text()
    window._on_committed(succeeded("Committed 2 files — a1b2c3d4"), None)

    assert "Committed" in window.statusBar().currentMessage()
    assert window.branch_label.text() == avant


def test_the_title_carries_the_branch(window):
    """Lisible depuis le sélecteur de fenêtres, hors premier plan."""
    assert f"[{window.state.head_branch}]" in window.windowTitle()


def test_a_detached_head_is_announced(window, monkeypatch):
    """Ne pas laisser croire qu'on est sur une branche quand on n'y est pas."""
    import dataclasses

    window.state = dataclasses.replace(
        window.state, head_branch=None, detached=True, head_oid="a" * 40
    )
    window._update_branch_label()

    texte = window.branch_label.text().lower()
    assert "détaché" in texte or "detached" in texte
    assert "aaaaaaaa" in window.branch_label.text()


def test_fetch_is_in_the_toolbar(window):
    """Demandé par l'utilisateur : Fetch n'était qu'au clic droit."""
    assert window.fetch_action is not None
    assert window.fetch_action.text() == "Fetch"


def test_fetch_is_disabled_without_a_remote(window):
    """Le dépôt de test n'a pas de remote."""
    window._update_fetch_action()
    assert window.fetch_action.isEnabled() is False
    assert window.fetch_action.toolTip()


def test_fetch_is_enabled_with_a_remote(qtbot, tmp_path):
    """Un vrai remote : `pygit2.Repository` est natif, sa propriété
    `remotes` ne peut pas être remplacée par un monkeypatch.
    """
    import subprocess

    from tortoisepy.ui.main_window import MainWindow

    bare = tmp_path / "s.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", str(bare)], capture_output=True
    )
    work = tmp_path / "w"
    subprocess.run(
        ["git", "clone", "-q", str(bare), str(work)], capture_output=True
    )
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
    }
    (work / "f.txt").write_text("a\n")
    subprocess.run(["git", "add", "."], cwd=work, env=env, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "base"],
        cwd=work, env=env, capture_output=True,
    )

    fenetre = MainWindow(pygit2.Repository(str(work)))
    qtbot.addWidget(fenetre)

    assert fenetre.fetch_action.isEnabled() is True
    assert "origin" in fenetre.fetch_action.toolTip()


def test_the_current_branch_is_selected_on_opening(window):
    """Demandé par l'utilisateur : la branche courante doit avoir le focus.

    La vue se recentrait bien dessus, mais rien n'était sélectionné : le
    panneau latéral restait vide, comme si on n'avait rien cliqué.
    """
    assert window.view.selected_oids() == (window.state.head_oid,)


def test_selecting_the_head_fills_the_commit_panel(window):
    """La sélection doit produire le même effet qu'un clic."""
    assert window.commit_panel.count() > 0


def test_the_selection_follows_a_checkout(qtbot, tmp_path):
    """Après un checkout, le focus suit la nouvelle branche courante."""
    import subprocess

    from tortoisepy.core.state import read_state
    from tortoisepy.ui.main_window import MainWindow

    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
    }

    def git(*args):
        subprocess.run(
            ["git", *args], cwd=tmp_path, env=env, capture_output=True
        )

    git("init", "-q", "-b", "main")
    (tmp_path / "f.txt").write_text("a\n")
    git("add", ".")
    git("commit", "-q", "-m", "premier")
    git("checkout", "-q", "-b", "autre")
    (tmp_path / "f.txt").write_text("b\n")
    git("add", ".")
    git("commit", "-q", "-m", "second")
    git("checkout", "-q", "main")

    repository = pygit2.Repository(str(tmp_path))
    fenetre = MainWindow(repository)
    qtbot.addWidget(fenetre)

    cible = str(repository.branches["autre"].target)
    assert fenetre.view.selected_oids() != (cible,)

    subprocess.run(
        ["git", "checkout", "-q", "autre"],
        cwd=tmp_path, env=env, capture_output=True,
    )
    fenetre.refresh()

    assert fenetre.view.selected_oids() == (cible,)
    assert fenetre.commit_panel.count() > 0


def _dialogue_rebase(monkeypatch, module, rejouee, cible, accepte=True):
    """Remplace la fenêtre de rebase par un double qui répond tout de suite.

    Sans cela, le test ouvrirait une vraie fenêtre modale que personne ne
    ferme — vérifié : la suite restait bloquée plusieurs minutes.
    """
    from PySide6.QtWidgets import QDialog

    vues = []

    class Double:
        DialogCode = QDialog.DialogCode

        def __init__(self, parent, current_branch, local_branches, targets):
            vues.append(
                {
                    "courante": current_branch,
                    "locales": list(local_branches),
                    "cibles": list(targets),
                }
            )

        def exec(self):
            return (
                QDialog.DialogCode.Accepted
                if accepte
                else QDialog.DialogCode.Rejected
            )

        def replayed(self):
            return rejouee

        def target(self):
            return cible

    monkeypatch.setattr(module, "RebaseDialog", Double)
    return vues


def test_rebase_offers_both_fields(window, monkeypatch):
    """Demandé par l'utilisateur : la branche rejouée ET la cible."""
    from tortoisepy.ui import main_window as module

    vues = _dialogue_rebase(monkeypatch, module, None, None, accepte=False)
    window.start_rebase_onto()

    assert vues, "la fenêtre doit être proposée"
    assert vues[0]["courante"] == window.state.head_branch
    assert vues[0]["locales"], "les branches locales doivent être proposées"
    assert vues[0]["cibles"], "les cibles doivent être proposées"


def test_cancelling_the_dialog_does_nothing(window, monkeypatch):
    """§7.0 : annuler n'écrit rien."""
    from tortoisepy.ui import main_window as module

    _dialogue_rebase(monkeypatch, module, "feature", "master", accepte=False)
    avant = window.repository.head.target
    window.start_rebase_onto()

    assert window.repository.head.target == avant


def test_the_chosen_branch_reaches_the_core(window, monkeypatch):
    """Le cœur du besoin : rejouer une AUTRE branche que la courante."""
    from tortoisepy.core.results import succeeded
    from tortoisepy.ui import main_window as module

    recus = []
    _dialogue_rebase(monkeypatch, module, "feature", "master")
    monkeypatch.setattr(
        module, "start_rebase",
        lambda repo, onto, branch=None: recus.append((onto, branch))
        or succeeded("Rebased"),
    )

    window.start_rebase_onto()

    assert recus == [("master", "feature")], recus


def test_the_current_branch_passes_none(window, monkeypatch):
    """Quand c'est déjà la courante, on garde le chemin de la phase 9."""
    from tortoisepy.core.results import succeeded
    from tortoisepy.ui import main_window as module

    courante = window.state.head_branch
    recus = []
    _dialogue_rebase(monkeypatch, module, courante, "master")
    monkeypatch.setattr(
        module, "start_rebase",
        lambda repo, onto, branch=None: recus.append((onto, branch))
        or succeeded("Rebased"),
    )

    window.start_rebase_onto()

    assert recus == [("master", None)], recus


def test_a_rebase_conflict_opens_the_window(window, monkeypatch):
    from tortoisepy.core.results import failed
    from tortoisepy.ui import main_window as module

    ouvertes = []
    monkeypatch.setattr(
        module.MainWindow, "open_conflict_window",
        lambda self: ouvertes.append(True),
    )
    monkeypatch.setattr(module, "show_error", lambda *a, **k: None)
    _dialogue_rebase(monkeypatch, module, "feature", "master")
    monkeypatch.setattr(
        module, "start_rebase",
        lambda repo, onto, branch=None: failed("Rebase", "conflicts in: f.txt"),
    )

    window.start_rebase_onto()
    assert ouvertes, "un conflit doit ouvrir la fenêtre de résolution"


def test_force_push_is_confirmed_before_anything_happens(window, monkeypatch):
    """§7.0 : refuser la confirmation n'envoie rien."""
    from tortoisepy.ui import main_window as module

    appels = []
    monkeypatch.setattr(module, "confirm", lambda *a, **k: False)
    monkeypatch.setattr(
        module.operations, "push_branch",
        lambda *a, **k: appels.append(k) or None,
    )
    window._start_push(force=True)
    assert not appels, "rien ne doit partir sans confirmation"


def test_the_confirmation_says_the_history_will_be_rewritten(window, monkeypatch):
    from tortoisepy.ui import main_window as module

    vus = []
    monkeypatch.setattr(
        module, "confirm", lambda parent, request: vus.append(request) or False
    )
    window._start_push(force=True)
    assert vus, "aucune confirmation demandée"
    texte = (vus[0].title + vus[0].message).lower()
    assert "force" in texte
    assert vus[0].destructive is True


def test_the_git_cli_asking_for_a_password_counts_as_authentication():
    """Revue finale, Important : sinon impasse au premier push forcé.

    Le push forcé passe par le `git` du système, qui ne parle pas comme
    libgit2. Sans identifiant en cache et avec `GIT_TERMINAL_PROMPT=0`, il
    répond « could not read Username for … : terminal prompts disabled »
    — vérifié sur git 2.50. Aucun des marqueurs de libgit2 n'y figurait,
    donc la fenêtre d'identifiants ne s'ouvrait pas : l'utilisateur voyait
    une erreur sans aucune issue, précisément au premier usage.
    """
    from tortoisepy.core.results import failed
    from tortoisepy.ui.main_window import _needs_authentication

    for message in (
        "fatal: could not read Username for 'https://gitlab.com': "
        "terminal prompts disabled",
        "fatal: could not read Password for 'https://x@gitlab.com': "
        "terminal prompts disabled",
        "fatal: Authentication failed for 'https://gitlab.com/x.git/'",
        "remote authentication required but no callback set",
    ):
        assert _needs_authentication(failed("Push", message)) is True, message


def test_a_broken_lease_is_not_an_authentication_problem():
    """L'inverse : ne pas demander un mot de passe pour un bail rompu."""
    from tortoisepy.core.results import failed
    from tortoisepy.ui.main_window import _needs_authentication

    for message in (
        "'origin/main' has moved since your last fetch — someone else "
        "pushed. Fetch before forcing.",
        "cannot push non-fastforwardable reference",
    ):
        assert _needs_authentication(failed("Push", message)) is False, message


def test_closing_during_a_background_task_waits_for_it(qtbot, repo):
    """Revue finale : le fil était détruit en pleine exécution.

    Reproduit avant correction : « QThread: Destroyed while thread is
    still running ». Le défaut préexistait, mais un push forcé passe par
    `git` et peut durer jusqu'à cinq minutes, là où un fetch se comptait
    en secondes — la fenêtre pour tomber dessus est devenue large.

    Fenêtre construite ici plutôt que par la fixture `window` : ce test la
    **ferme**, et une fixture partagée fermée fait échouer le démontage
    des tests suivants (vérifié).
    """
    import time

    from tortoisepy.core.results import succeeded
    from tortoisepy.ui.tasks import BackgroundTask, FetchWorker

    fenetre = MainWindow(repo)
    qtbot.addWidget(fenetre)

    def lent(on_progress):
        time.sleep(0.5)
        return succeeded("fini")

    fenetre._task = BackgroundTask(FetchWorker(lent), fenetre)
    fenetre._task.start()
    qtbot.waitUntil(lambda: fenetre._task.is_running(), timeout=2000)

    # `closeEvent` directement : `close()` sur une fenêtre jamais affichée
    # ne le déclenche pas toujours selon la plateforme.
    from PySide6.QtGui import QCloseEvent

    fenetre.closeEvent(QCloseEvent())
    assert fenetre._task.is_running() is False, (
        "la tâche doit être terminée quand `closeEvent` rend la main"
    )


# --- indicateur de divergence (tâche 3) ----------------------------------


def test_the_status_bar_shows_the_divergence(window, monkeypatch):
    from tortoisepy.ui import main_window as module

    monkeypatch.setattr(module, "divergence", lambda repo: (2, 1))
    window.refresh()
    assert "↑2" in window.branch_label.text()
    assert "↓1" in window.branch_label.text()


def test_an_up_to_date_branch_shows_no_arrows(window, monkeypatch):
    """Une branche à jour n'a pas besoin d'être commentée."""
    from tortoisepy.ui import main_window as module

    monkeypatch.setattr(module, "divergence", lambda repo: (0, 0))
    window.refresh()
    assert "↑" not in window.branch_label.text()
    assert "↓" not in window.branch_label.text()


def test_the_tooltip_says_the_figure_may_be_stale(window, monkeypatch):
    """Review Focus 2 : un indicateur muet sur sa fraîcheur mentirait."""
    from tortoisepy.ui import main_window as module

    monkeypatch.setattr(module, "divergence", lambda repo: (1, 1))
    window.refresh()
    assert "fetch" in window.branch_label.toolTip().lower()


def test_no_divergence_keeps_the_existing_tooltip(window, monkeypatch):
    """Piège du brief : le chemin sans écart doit garder l'infobulle
    existante (le nom de la branche), pas la laisser vide ou dupliquée.
    """
    from tortoisepy.ui import main_window as module

    monkeypatch.setattr(module, "divergence", lambda repo: None)
    window.refresh()
    assert window.branch_label.toolTip() == window.state.head_branch


# --- recherche et cache (tâche 3) ----------------------------------------


def test_searching_highlights_the_matching_nodes(window, monkeypatch):
    from tortoisepy.ui import main_window as module

    cible = window.graph.nodes[0].oid
    monkeypatch.setattr(module, "search_commits", lambda repo, motif: (cible,))

    window.search_field.setText("quelque chose")
    window.run_search()

    assert window.view.highlighted_count() == 1
    assert "1" in window.statusBar().currentMessage()


def test_an_empty_search_clears_the_highlight(window, monkeypatch):
    from tortoisepy.ui import main_window as module

    cible = window.graph.nodes[0].oid
    monkeypatch.setattr(module, "search_commits", lambda repo, motif: (cible,))
    window.search_field.setText("x")
    window.run_search()

    monkeypatch.setattr(module, "search_commits", lambda repo, motif: ())
    window.search_field.setText("")
    window.run_search()

    assert window.view.highlighted_count() == 0


def test_a_search_without_result_says_so(window, monkeypatch):
    from tortoisepy.ui import main_window as module

    monkeypatch.setattr(module, "search_commits", lambda repo, motif: ())
    window.search_field.setText("introuvable")
    window.run_search()

    assert "no" in window.statusBar().currentMessage().lower()


def test_an_unchanged_repository_is_not_rebuilt(window, monkeypatch):
    """Le cache en action : un refresh sans changement ne reconstruit pas."""
    from tortoisepy.ui import main_window as module

    appels = []
    vrai = module.build_graph
    monkeypatch.setattr(
        module, "build_graph",
        lambda repo, *a, **k: appels.append(1) or vrai(repo, *a, **k),
    )
    window.refresh()
    window.refresh()

    assert len(appels) <= 1, f"{len(appels)} constructions pour 2 refresh"


def test_the_search_field_spans_the_commit_panel(window):
    """Demandé par l'utilisateur : même largeur que la liste qu'il filtre.

    Il flottait d'abord dans la barre d'outils, sans rapport visuel avec
    ce sur quoi il agit. Il vit maintenant dans le panneau, en tête de
    son layout, donc il en épouse la largeur et suit le splitter.
    """
    from PySide6.QtWidgets import QLineEdit

    champ = window.search_field
    assert champ.parent() is window.commit_panel, (
        "le champ doit appartenir au panneau, pas à la barre d'outils"
    )

    layout = window.commit_panel.layout()
    assert layout.itemAt(0).widget() is champ, "il doit être en tête"

    # Aucun QLineEdit ne doit subsister dans la barre d'outils.
    assert not [
        a
        for a in window.toolbar.actions()
        if isinstance(window.toolbar.widgetForAction(a), QLineEdit)
    ]


def test_searching_filters_the_commit_list(window, monkeypatch):
    """Demandé par l'utilisateur : filtrer la liste, pas seulement surligner."""
    from tortoisepy.ui import main_window as module

    window.commit_panel.show_commits("n", _deux_commits())
    assert window.commit_panel.visible_count() == 2

    monkeypatch.setattr(
        module, "search_commits", lambda repo, motif: ("a" * 40,)
    )
    window.search_field.setText("premier")
    window.run_search()

    assert window.commit_panel.visible_count() == 1


def test_clearing_the_search_restores_the_whole_list(window, monkeypatch):
    from tortoisepy.ui import main_window as module

    window.commit_panel.show_commits("n", _deux_commits())
    monkeypatch.setattr(
        module, "search_commits", lambda repo, motif: ("a" * 40,)
    )
    window.search_field.setText("premier")
    window.run_search()

    window.search_field.setText("")
    window.run_search()

    assert window.commit_panel.visible_count() == 2


def test_results_outside_the_list_are_announced_honestly(window, monkeypatch):
    """Trouvés mais invisibles : ne pas laisser croire à un échec.

    Le panneau est borné aux commits les plus récents et le graphe
    compresse les chaînes : un résultat profond n'apparaît ni dans la
    liste ni sur un nœud. Promettre « sélectionnez un nœud surligné »
    serait faux quand il n'y en a aucun.
    """
    from tortoisepy.ui import main_window as module

    window.commit_panel.show_commits("n", _deux_commits())
    monkeypatch.setattr(
        module, "search_commits", lambda repo, motif: ("f" * 40,)
    )
    window.search_field.setText("profond")
    window.run_search()

    message = window.statusBar().currentMessage()
    assert "1 commit(s) found" in message
    assert "too deep" in message
    assert "highlighted node" not in message


def _deux_commits():
    from datetime import datetime

    from tortoisepy.core.commits import CommitInfo

    return tuple(
        CommitInfo(
            oid=lettre * 40,
            summary=resume,
            message=resume,
            author_name="A",
            author_email="a@a",
            when=datetime(2026, 1, 1),
            parent_count=1,
        )
        for lettre, resume in (("a", "premier"), ("b", "second"))
    )


def test_selecting_the_same_node_twice_reloads_nothing(window, monkeypatch):
    """La raison d'être de la phase : 292 ms par sélection, mesurés.

    Ouverture + 3 rafraîchissements donnaient 4 appels pour **un seul**
    OID distinct — toujours le même historique rechargé.
    """
    from tortoisepy.ui import main_window as module

    oid = window.graph.nodes[0].oid
    appels = []
    vrai = module.commits_for_node
    monkeypatch.setattr(
        module, "commits_for_node",
        lambda r, g, o: appels.append(o) or vrai(r, g, o),
    )
    # La fenêtre sélectionne HEAD à l'ouverture, donc une entrée est déjà
    # en cache : partir d'un cache vide, sinon on mesure l'ouverture.
    window._panel_cache.clear()

    window._show_commits(oid)
    window._show_commits(oid)
    window._show_commits(oid)

    assert len(appels) == 1, f"{len(appels)} chargements au lieu d'un"


def test_each_node_is_cached_separately(window, monkeypatch):
    """Revenir sur un nœud déjà vu ne doit pas le recharger."""
    from tortoisepy.ui import main_window as module

    oids = [n.oid for n in window.graph.nodes]
    if len(oids) < 2:
        import pytest

        pytest.skip("le dépôt de test n'a qu'un nœud")

    appels = []
    vrai = module.commits_for_node
    monkeypatch.setattr(
        module, "commits_for_node",
        lambda r, g, o: appels.append(o) or vrai(r, g, o),
    )
    window._panel_cache.clear()

    window._show_commits(oids[0])
    window._show_commits(oids[1])
    window._show_commits(oids[0])

    assert appels == [oids[0], oids[1]], appels


def test_a_new_commit_invalidates_the_panel_cache(window, repo):
    """Un cache qui ne s'invalide pas affiche un historique FAUX.

    C'est pire que lent : l'utilisateur croit voir son dépôt.

    **Le test vise un nœud dont l'OID ne bouge pas** — celui d'une autre
    branche. Viser HEAD ne prouvait rien : son OID change avec le commit,
    donc la clé change aussi et le cache est contourné plutôt
    qu'invalidé. Vérifié par mutation : supprimer l'invalidation laissait
    ce test passer.
    """
    autre = str(repo.branches.local["feature"].target)
    window._show_commits(autre)
    avant = list(window._panel_cache[autre])
    assert avant, "le nœud doit être en cache"

    run_git(repo.workdir, "commit", "-q", "--allow-empty", "-m", "tout nouveau")
    window.refresh()

    assert autre not in window._panel_cache, (
        "un commit ailleurs doit vider le cache : le graphe a changé, "
        "donc les marqueurs « own » aussi"
    )


def test_unpushed_markers_are_not_cached(window, monkeypatch):
    """§3.3 : on met en cache l'historique, pas sa décoration.

    Les marqueurs de non-poussé changent après un push alors qu'aucun
    commit n'a bougé — les figer afficherait des flèches fantômes.
    """
    from tortoisepy.ui import main_window as module

    oid = window.graph.nodes[0].oid
    vus = []
    monkeypatch.setattr(
        module.CommitPanel, "show_commits",
        lambda self, label, commits, unpushed=frozenset(): vus.append(unpushed),
    )

    monkeypatch.setattr(module, "unpushed_oids", lambda repo: frozenset({"a" * 40}))
    window._show_commits(oid)

    monkeypatch.setattr(module, "unpushed_oids", lambda repo: frozenset())
    window._show_commits(oid)

    assert vus[0] != vus[1], "les marqueurs doivent être relus à chaque affichage"


def test_ctrl_f_is_bound_to_the_search_field(window):
    """D37 : le champ existait depuis la phase 13, sans raccourci.

    **Le focus n'est pas vérifiable ici** : sous pytest-qt en mode
    `offscreen`, la fenêtre n'est jamais activée (`isActiveWindow()` est
    faux) et `focusWidget()` reste `None` — même un `setFocus()` direct
    n'y change rien. Sondé pour ne pas écrire un test qui échoue pour une
    raison étrangère au code.

    On éprouve donc ce qui est observable : la touche est bien liée, et
    déclencher l'action sélectionne le contenu du champ.
    """
    actions = {
        a.shortcut().toString(): a for a in window.actions() if a.shortcut()
    }
    assert "Ctrl+F" in actions, sorted(actions)

    window.search_field.setText("ancienne recherche")
    actions["Ctrl+F"].trigger()

    assert window.search_field.selectedText() == "ancienne recherche", (
        "le contenu doit être sélectionné, pour qu'une nouvelle recherche "
        "remplace la précédente sans avoir à l'effacer"
    )


def test_the_search_shortcut_does_not_clash_with_fetch(window):
    """`Ctrl+Shift+F` est Fetch : les deux doivent rester distincts."""
    touches = [a.shortcut().toString() for a in window.actions() if a.shortcut()]
    assert touches.count("Ctrl+F") == 1
    assert "Ctrl+Shift+F" in touches


def test_focus_search_asks_for_the_focus(window, monkeypatch):
    """Le focus n'étant pas observable en test, on vérifie la demande."""
    demandes = []
    monkeypatch.setattr(
        type(window.search_field), "setFocus",
        lambda self, *a: demandes.append(True),
    )
    window.focus_search()
    assert demandes, "focus_search doit demander le focus"
