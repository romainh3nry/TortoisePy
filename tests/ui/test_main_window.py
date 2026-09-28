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


def test_commit_panel_starts_empty(window):
    assert window.commit_panel.count() == 0


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
    window._show_commits("0" * 40)  # ne doit pas lever
    assert window.commit_panel.count() == 0


def test_refresh_clears_the_panel(window):
    """Le panneau porte sur un graphe donné : le reconstruire l'invalide."""
    node = next(
        n for n in window.graph.nodes
        if any(r.name == "feature" for r in n.refs)
    )
    window._show_commits(node.oid)
    assert window.commit_panel.count() > 0

    window.refresh()
    assert window.commit_panel.count() == 0


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
    """Sélectionner un nœud suffit : c'est le même geste."""
    _node_item(window, "feature").setSelected(True)
    assert window.commit_panel.count() > 0
    assert "feature" in window.commit_panel._title.text()


def test_two_selected_nodes_clear_the_panel(window):
    """Avec deux nœuds, le menu bascule sur la comparaison (§7.4) :
    montrer les commits de l'un des deux serait arbitraire."""
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


def test_commit_window_opens(window):
    window.open_commit_window()
    assert window.commit_window is not None
    window.commit_window.close()


def test_commit_window_is_reused(window):
    """Deux fenêtres de commit sur le même dépôt se contrediraient."""
    window.open_commit_window()
    first = window.commit_window
    window.open_commit_window()
    assert window.commit_window is first
    first.close()


def test_graph_refreshes_after_a_commit(window, monkeypatch):
    from tortoisepy.core.results import succeeded

    window.open_commit_window()
    before = window.view.scene()
    window.commit_window.committed.emit(succeeded("fait"))
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
