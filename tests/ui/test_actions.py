import os
import subprocess

import pygit2
import pytest

from tortoisepy.core.graph import build_graph
from tortoisepy.core.state import read_state
from tortoisepy.ui.actions import ACTION_HANDLERS, ActionContext, execute_action


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
    path = tmp_path / "actions"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "master")
    (path / "f.txt").write_text("base\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "base")
    run_git(path, "checkout", "-q", "-b", "feature")
    (path / "g.txt").write_text("feature\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "feature")
    run_git(path, "checkout", "-q", "master")
    return pygit2.Repository(str(path))


def context(repo, branch: str = "feature", **overrides) -> ActionContext:
    graph = build_graph(repo)
    node = next(
        n for n in graph.nodes if any(r.name == branch for r in n.refs)
    )
    defaults = dict(
        repository=repo,
        node=node,
        state=read_state(repo),
        parent=None,
        ask_name=lambda *a, **k: "nouvelle-branche",
        ask_mode=lambda *a, **k: "mixed",
        confirm=lambda *a, **k: True,
    )
    defaults.update(overrides)
    return ActionContext(**defaults)


def test_every_menu_action_has_a_handler():
    """Une entrée sans handler afficherait un menu mensonger."""
    from tortoisepy.ui.context_menu import build_menu_model
    from tortoisepy.core.model import DisplayNode, NodeKind, Ref, RefType
    from tortoisepy.core.state import RepositoryState

    node = DisplayNode(
        oid="a" * 40,
        kind=NodeKind.REF,
        refs=(Ref("feature", RefType.LOCAL_BRANCH, "a" * 40),),
    )
    state = RepositoryState(
        head_oid="b" * 40, head_branch="master", detached=False,
        has_unstaged_changes=False, has_staged_changes=False,
        has_conflicts=False, operation_in_progress=None, conflicted_paths=(),
    )

    def actions(entries):
        for entry in entries:
            if entry.action and not entry.is_separator:
                yield entry.action
            yield from actions(entry.children)

    declared = set(actions(build_menu_model((node,), state)))
    missing = declared - set(ACTION_HANDLERS)
    assert not missing, f"actions sans handler : {sorted(missing)}"


def test_checkout_switches_branch(repo):
    result = execute_action("checkout_branch", context(repo))
    assert result.success is True
    assert read_state(repo).head_branch == "feature"


def test_create_branch_uses_the_given_name(repo):
    result = execute_action(
        "create_branch", context(repo, ask_name=lambda *a, **k: "issue-42")
    )
    assert result.success is True
    assert "refs/heads/issue-42" in repo.references


def test_cancelling_a_name_does_nothing(repo):
    """Annuler la saisie ne doit RIEN écrire (§7.0)."""
    before = set(repo.references)
    result = execute_action(
        "create_branch", context(repo, ask_name=lambda *a, **k: None)
    )
    assert result is None
    assert set(repo.references) == before


def test_declining_a_confirmation_does_nothing(repo):
    """§7.5 : refuser la confirmation annule l'opération."""
    before = set(repo.references)
    result = execute_action(
        "delete_branch", context(repo, confirm=lambda *a, **k: False)
    )
    assert result is None
    assert set(repo.references) == before


def test_delete_branch_after_confirmation(repo):
    result = execute_action("delete_branch", context(repo))
    assert result.success is True
    assert "refs/heads/feature" not in repo.references


def test_create_tag_uses_the_given_name(repo):
    result = execute_action(
        "create_tag", context(repo, ask_name=lambda *a, **k: "v1.0")
    )
    assert result.success is True
    assert "refs/tags/v1.0" in repo.references


def test_reset_asks_for_a_mode(repo):
    asked = []
    execute_action(
        "reset_to",
        context(repo, ask_mode=lambda *a, **k: (asked.append(1), "soft")[1]),
    )
    assert asked, "le mode doit être demandé"


def test_cancelling_the_mode_does_nothing(repo):
    head = str(repo.head.target)
    result = execute_action(
        "reset_to", context(repo, ask_mode=lambda *a, **k: None)
    )
    assert result is None
    assert str(repo.head.target) == head


def test_merge_brings_the_branch_in(repo):
    result = execute_action("merge_branch", context(repo))
    assert result.repository_changed is True


def test_copy_hash_writes_nothing(repo):
    """Copier un hash ne touche pas au dépôt."""
    result = execute_action("copy_hash", context(repo))
    assert result is not None
    assert result.repository_changed is False


def test_unknown_action_returns_none(repo):
    assert execute_action("action_inexistante", context(repo)) is None


def test_failure_is_reported_not_raised(repo):
    """§7.6 : aucune exception ne remonte."""
    ctx = context(repo, branch="master")  # supprimer la branche courante
    result = execute_action("delete_branch", ctx)
    assert result is not None
    assert result.success is False
    assert result.git_error


def test_handlers_never_raise(repo):
    """Chaque handler doit survivre à un contexte hostile."""
    ctx = context(repo, ask_name=lambda *a, **k: "", ask_mode=lambda *a, **k: "")
    for action in ACTION_HANDLERS:
        execute_action(action, ctx)  # ne doit jamais lever
