"""Panneau des commits — révèle ce que la compression masque."""

from datetime import datetime, timezone

import pytest

from tortoisepy.core.commits import CommitInfo
from tortoisepy.ui.commit_panel import COLUMNS, CommitPanel


def commit(oid: str, summary: str = "un message", merge: bool = False) -> CommitInfo:
    return CommitInfo(
        oid=oid,
        summary=summary,
        message=summary,
        author_name="Alice",
        author_email="alice@example.com",
        when=datetime(2026, 9, 25, 14, 30, tzinfo=timezone.utc),
        parent_count=2 if merge else 1,
    )


@pytest.fixture
def panel(qtbot):
    widget = CommitPanel()
    qtbot.addWidget(widget)
    return widget


def test_panel_starts_empty(panel):
    assert panel.count() == 0
    assert panel.selected_oid() is None


def test_show_commits_fills_the_list(panel):
    panel.show_commits("feature", (commit("a" * 40), commit("b" * 40)))
    assert panel.count() == 2


def test_first_commit_is_selected(panel):
    panel.show_commits("feature", (commit("a" * 40), commit("b" * 40)))
    assert panel.selected_oid() == "a" * 40


def test_title_reports_the_count(panel):
    panel.show_commits("feature", (commit("a" * 40), commit("b" * 40)))
    assert "2 commits" in panel._title.text()
    assert "feature" in panel._title.text()


def test_title_is_singular_for_one_commit(panel):
    panel.show_commits("feature", (commit("a" * 40),))
    assert "1 commit" in panel._title.text()
    assert "1 commits" not in panel._title.text()


def test_showing_again_replaces_the_previous_list(panel):
    panel.show_commits("a", (commit("a" * 40), commit("b" * 40)))
    panel.show_commits("b", (commit("c" * 40),))
    assert panel.count() == 1
    assert panel.selected_oid() == "c" * 40


def test_clear_empties_the_panel(panel):
    panel.show_commits("feature", (commit("a" * 40),))
    panel.clear()
    assert panel.count() == 0


def test_message_column_comes_early(panel):
    """La colonne qu'on lit ne doit pas sortir du champ."""
    assert COLUMNS.index("Message") == 1


def test_merge_commits_are_tinted(panel):
    from tortoisepy.ui.commit_panel import MERGE_COLOR

    panel.show_commits("f", (commit("a" * 40, merge=True), commit("b" * 40)))
    merge_item = panel._tree.topLevelItem(0)
    plain_item = panel._tree.topLevelItem(1)
    assert merge_item.foreground(0).color() == MERGE_COLOR
    assert plain_item.foreground(0).color() != MERGE_COLOR


def test_selection_emits_the_oid(panel, qtbot):
    with qtbot.waitSignal(panel.commit_selected, timeout=1000) as blocker:
        panel.show_commits("feature", (commit("a" * 40),))
    assert blocker.args == ["a" * 40]


def test_full_message_is_available_as_tooltip(panel):
    info = CommitInfo(
        oid="a" * 40,
        summary="titre",
        message="titre\n\ncorps détaillé",
        author_name="Alice",
        author_email="alice@example.com",
        when=datetime(2026, 9, 25, tzinfo=timezone.utc),
        parent_count=1,
    )
    panel.show_commits("feature", (info,))
    assert "corps détaillé" in panel._tree.topLevelItem(0).toolTip(1)


def test_empty_list_is_accepted(panel):
    panel.show_commits("vide", ())
    assert panel.count() == 0
    assert "0 commits" in panel._title.text()
