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
