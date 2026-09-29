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


def test_creating_a_branch_switches_onto_it(repo):
    """Demandé par l'utilisateur : `git checkout -b`, pas `git branch`.

    Créer une branche pour rester sur l'ancienne n'a pratiquement jamais
    d'intérêt — on la crée pour y travailler.
    """
    execute_action(
        "create_branch", context(repo, ask_name=lambda *a, **k: "ma-feature")
    )
    assert read_state(repo).head_branch == "ma-feature"


def test_creating_a_branch_keeps_uncommitted_work(repo, tmp_path):
    """La bascule ne doit pas emporter le travail en cours.

    Sans risque ici : la nouvelle branche part du même commit, il n'y a
    donc rien à remplacer dans l'arbre de travail. Le test le verrouille.
    """
    import os

    chemin = os.path.join(repo.workdir, "en-cours.txt")
    with open(chemin, "w") as handle:
        handle.write("mon travail\n")

    execute_action(
        "create_branch", context(repo, ask_name=lambda *a, **k: "autre")
    )

    assert read_state(repo).head_branch == "autre"
    with open(chemin) as handle:
        assert handle.read() == "mon travail\n"


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


def test_the_stash_actions_use_the_node_oid(repo, monkeypatch):
    """Le piège de la phase : agir par index viserait un autre stash."""
    from tortoisepy.core.model import DisplayNode, NodeKind, Ref, RefType
    from tortoisepy.ui import actions as module

    vus = []
    for nom in ("apply_stash", "pop_stash", "drop_stash"):
        monkeypatch.setattr(
            module.stash_ops, nom,
            lambda repo, oid, _n=nom: vus.append((_n, oid)) or None,
        )

    oid = "c" * 40
    stash = DisplayNode(
        oid=oid, kind=NodeKind.STASH,
        refs=(Ref("stash@{0}", RefType.STASH, oid),),
    )
    for nom in ("apply_stash", "pop_stash", "drop_stash"):
        module.execute_action(nom, context(repo, node=stash))

    assert vus == [
        ("apply_stash", oid), ("pop_stash", oid), ("drop_stash", oid)
    ]


def test_every_stash_action_has_a_handler():
    """`test_every_menu_action_has_a_handler` part d'un nœud ordinaire.

    Les entrées de stash n'y apparaissent donc pas : sans ce test, une
    action de stash sans handler passerait inaperçue.
    """
    from tortoisepy.core.model import DisplayNode, NodeKind, Ref, RefType
    from tortoisepy.core.state import RepositoryState
    from tortoisepy.ui.context_menu import build_menu_model

    oid = "c" * 40
    stash = DisplayNode(
        oid=oid, kind=NodeKind.STASH,
        refs=(Ref("stash@{0}", RefType.STASH, oid),),
    )
    state = RepositoryState(
        head_oid="a" * 40, head_branch="main", detached=False,
        has_unstaged_changes=True, has_staged_changes=False,
        has_conflicts=False, operation_in_progress=None, conflicted_paths=(),
    )

    def declarees(entries):
        for entry in entries:
            if entry.action and not entry.is_separator:
                yield entry.action
            yield from declarees(entry.children)

    manquantes = set(declarees(build_menu_model((stash,), state))) - set(
        ACTION_HANDLERS
    )
    assert not manquantes, f"actions sans handler : {sorted(manquantes)}"


def test_dropping_a_stash_is_refused_when_the_user_declines(repo, monkeypatch):
    """Revue finale, Critical : Drop détruisait le travail malgré un refus.

    `MenuEntry.needs_confirmation` n'est **lu par personne** : la vraie
    porte est `confirmation_for`, qui n'avait pas de branche `drop_stash`.
    Reproduit — l'utilisateur cliquait « Non » et le stash disparaissait
    quand même, sans récupération possible. Un test au niveau du
    `MenuEntry` passait pourtant : il vérifiait un champ inerte.
    """
    from tortoisepy.core.model import DisplayNode, NodeKind, Ref, RefType
    from tortoisepy.ui import actions as module

    appels = []
    monkeypatch.setattr(
        module.stash_ops, "drop_stash",
        lambda repo, oid: appels.append(oid) or None,
    )

    oid = "c" * 40
    stash = DisplayNode(
        oid=oid, kind=NodeKind.STASH,
        refs=(Ref("stash@{0}", RefType.STASH, oid),),
    )
    vus = []
    resultat = module.execute_action(
        "drop_stash",
        context(repo, node=stash, confirm=lambda parent, req: vus.append(req) or False),
    )

    assert vus, "aucune confirmation demandée"
    assert vus[0].destructive is True
    assert "cannot be recovered" in vus[0].message
    assert resultat is None
    assert not appels, "le stash ne doit pas être retiré après un refus"


def test_dropping_a_stash_proceeds_when_confirmed(repo, monkeypatch):
    from tortoisepy.core.model import DisplayNode, NodeKind, Ref, RefType
    from tortoisepy.ui import actions as module

    appels = []
    monkeypatch.setattr(
        module.stash_ops, "drop_stash",
        lambda repo, oid: appels.append(oid) or None,
    )

    oid = "c" * 40
    stash = DisplayNode(
        oid=oid, kind=NodeKind.STASH,
        refs=(Ref("stash@{0}", RefType.STASH, oid),),
    )
    module.execute_action(
        "drop_stash", context(repo, node=stash, confirm=lambda *a, **k: True)
    )
    assert appels == [oid]


def test_applying_and_popping_a_stash_are_not_confirmed(repo, monkeypatch):
    """Ils restaurent du travail : rien à détruire, donc rien à confirmer."""
    from tortoisepy.core.model import DisplayNode, NodeKind, Ref, RefType
    from tortoisepy.ui import actions as module

    for nom in ("apply_stash", "pop_stash"):
        monkeypatch.setattr(
            module.stash_ops, nom, lambda repo, oid: None
        )

    oid = "c" * 40
    stash = DisplayNode(
        oid=oid, kind=NodeKind.STASH,
        refs=(Ref("stash@{0}", RefType.STASH, oid),),
    )
    for nom in ("apply_stash", "pop_stash"):
        vus = []
        module.execute_action(
            nom,
            context(repo, node=stash, confirm=lambda p, r: vus.append(r) or True),
        )
        assert not vus, f"{nom} ne doit pas demander de confirmation"
