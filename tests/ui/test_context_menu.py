from tortoisepy.core.model import DisplayNode, NodeKind, Ref, RefType
from tortoisepy.core.state import RepositoryState
from tortoisepy.ui.context_menu import build_menu_model


def node(oid: str, kind: NodeKind, *refs: Ref) -> DisplayNode:
    return DisplayNode(oid=oid, kind=kind, refs=refs)


def branch_node(name: str = "feature") -> DisplayNode:
    return node("a" * 40, NodeKind.REF, Ref(name, RefType.LOCAL_BRANCH, "a" * 40))


def clean_state(**overrides) -> RepositoryState:
    defaults = dict(
        head_oid="b" * 40,
        head_branch="master",
        detached=False,
        has_unstaged_changes=False,
        has_staged_changes=False,
        has_conflicts=False,
        operation_in_progress=None,
        conflicted_paths=(),
    )
    defaults.update(overrides)
    return RepositoryState(**defaults)


def find(entries, action: str):
    for entry in entries:
        if entry.action == action:
            return entry
        for child in entry.children:
            if child.action == action:
                return child
    return None


def test_single_node_offers_checkout():
    entries = build_menu_model((branch_node(),), clean_state())
    assert find(entries, "checkout_branch") is not None


def test_menu_is_hierarchical():
    """§7.3 : quatorze entrées à plat seraient illisibles."""
    entries = build_menu_model((branch_node(),), clean_state())
    assert any(entry.children for entry in entries)


def test_copy_hash_is_always_available():
    entries = build_menu_model((branch_node(),), clean_state())
    assert find(entries, "copy_hash").enabled is True


def test_tag_node_cannot_be_checked_out_as_branch():
    """§7.3 : les actions de branche sont grisées sur un tag."""
    tag = node("a" * 40, NodeKind.REF, Ref("v1.0", RefType.TAG, "a" * 40))
    entries = build_menu_model((tag,), clean_state())
    assert find(entries, "delete_branch").enabled is False
    assert find(entries, "rename_branch").enabled is False


def test_junction_node_has_no_branch_actions():
    junction = node("a" * 40, NodeKind.JUNCTION)
    entries = build_menu_model((junction,), clean_state())
    assert find(entries, "delete_branch").enabled is False


def test_stash_node_keeps_only_read_actions():
    """§7.3 : sur un stash, seuls Show Log et Copy hash restent actifs."""
    stash = node("a" * 40, NodeKind.STASH,
                 Ref("stash@{0}", RefType.STASH, "a" * 40))
    entries = build_menu_model((stash,), clean_state())
    assert find(entries, "copy_hash").enabled is True
    assert find(entries, "merge_branch").enabled is False
    assert find(entries, "checkout_branch").enabled is False


def test_current_branch_cannot_be_merged_into_itself():
    """§7.3 : Checkout et Merge sont sans objet sur la branche courante."""
    current = node("a" * 40, NodeKind.REF,
                   Ref("master", RefType.LOCAL_BRANCH, "a" * 40),
                   Ref("HEAD", RefType.HEAD, "a" * 40))
    entries = build_menu_model((current,), clean_state(head_branch="master"))
    assert find(entries, "merge_branch").enabled is False
    assert find(entries, "checkout_branch").enabled is False


def test_operation_in_progress_disables_modifying_actions():
    """§7.3 : pendant un merge, plus rien ne doit modifier le dépôt."""
    entries = build_menu_model(
        (branch_node(),), clean_state(operation_in_progress="merge")
    )
    assert find(entries, "merge_branch").enabled is False
    assert find(entries, "reset_to").enabled is False
    assert find(entries, "copy_hash").enabled is True


def test_operation_in_progress_offers_abort():
    entries = build_menu_model(
        (branch_node(),), clean_state(operation_in_progress="merge")
    )
    assert find(entries, "abort_operation").enabled is True


def test_no_abort_when_nothing_in_progress():
    entries = build_menu_model((branch_node(),), clean_state())
    abort = find(entries, "abort_operation")
    assert abort is None or abort.enabled is False


def test_dirty_worktree_warns_on_checkout():
    """§7.5 : un checkout avec des modifications locales demande confirmation."""
    entries = build_menu_model(
        (branch_node(),), clean_state(has_unstaged_changes=True)
    )
    checkout = find(entries, "checkout_branch")
    assert checkout.needs_confirmation is True


def test_destructive_actions_require_confirmation():
    """§7.5 : reset et suppression de branche sont confirmés."""
    entries = build_menu_model((branch_node(),), clean_state())
    assert find(entries, "reset_to").needs_confirmation is True
    assert find(entries, "delete_branch").needs_confirmation is True


def test_two_nodes_offer_comparison():
    """§7.4 : deux nœuds sélectionnés activent la comparaison."""
    a = branch_node("a")
    b = node("b" * 40, NodeKind.REF, Ref("b", RefType.LOCAL_BRANCH, "b" * 40))
    entries = build_menu_model((a, b), clean_state())
    assert find(entries, "compare_revisions").enabled is True


def test_single_node_cannot_compare():
    entries = build_menu_model((branch_node(),), clean_state())
    compare = find(entries, "compare_revisions")
    assert compare is None or compare.enabled is False


def test_empty_selection_gives_no_menu():
    assert build_menu_model((), clean_state()) == ()


def test_every_entry_has_a_label():
    entries = build_menu_model((branch_node(),), clean_state())
    for entry in entries:
        assert entry.label
        for child in entry.children:
            assert child.label


def test_push_is_in_the_menu():
    from tortoisepy.core.model import DisplayNode, NodeKind, Ref, RefType
    from tortoisepy.core.state import RepositoryState
    from tortoisepy.ui.context_menu import build_menu_model

    node = DisplayNode(
        oid="a" * 40,
        kind=NodeKind.REF,
        refs=(Ref("main", RefType.LOCAL_BRANCH, "a" * 40),),
    )
    state = RepositoryState(
        head_oid="a" * 40, head_branch="main", detached=False,
        has_unstaged_changes=False, has_staged_changes=False,
        has_conflicts=False, operation_in_progress=None, conflicted_paths=(),
    )

    def actions(entries):
        for entry in entries:
            if entry.action:
                yield entry.action
            yield from actions(entry.children)

    assert "push_branch" in set(actions(build_menu_model((node,), state)))


def test_pull_is_in_the_menu():
    from tortoisepy.core.model import DisplayNode, NodeKind, Ref, RefType
    from tortoisepy.core.state import RepositoryState
    from tortoisepy.ui.context_menu import build_menu_model

    node = DisplayNode(
        oid="a" * 40,
        kind=NodeKind.REF,
        refs=(Ref("main", RefType.LOCAL_BRANCH, "a" * 40),),
    )
    state = RepositoryState(
        head_oid="a" * 40, head_branch="main", detached=False,
        has_unstaged_changes=False, has_staged_changes=False,
        has_conflicts=False, operation_in_progress=None, conflicted_paths=(),
    )

    def actions(entries):
        for entry in entries:
            if entry.action:
                yield entry.action
            yield from actions(entry.children)

    assert "pull_branch" in set(actions(build_menu_model((node,), state)))


def _multi_branch_node():
    """Un nœud portant quatre branches locales, dont la courante."""
    oid = "a" * 40
    return DisplayNode(
        oid=oid,
        kind=NodeKind.REF,
        refs=(
            Ref("feature-a", RefType.LOCAL_BRANCH, oid),
            Ref("feature-b", RefType.LOCAL_BRANCH, oid),
            Ref("main", RefType.LOCAL_BRANCH, oid),
            Ref("HEAD", RefType.HEAD, oid),
        ),
    )


def _on_main():
    return RepositoryState(
        head_oid="a" * 40, head_branch="main", detached=False,
        has_unstaged_changes=False, has_staged_changes=False,
        has_conflicts=False, operation_in_progress=None, conflicted_paths=(),
    )


def _find(entries, label):
    for entry in entries:
        if entry.label == label:
            return entry
        found = _find(entry.children, label)
        if found is not None:
            return found
    return None


def test_several_branches_give_a_submenu():
    """Signalé par l'utilisateur : avec plusieurs branches sur un même
    commit, l'action retombait sur la première et les autres étaient
    inatteignables."""
    entries = build_menu_model((_multi_branch_node(),), _on_main())
    checkout = _find(entries, "Switch / Checkout to revision")

    assert checkout is not None
    noms = [c.label for c in checkout.children]
    assert noms == ["feature-a", "feature-b"]


def test_each_submenu_entry_names_its_branch():
    """Sans cette précision, toutes les entrées agiraient sur la même."""
    entries = build_menu_model((_multi_branch_node(),), _on_main())
    checkout = _find(entries, "Switch / Checkout to revision")

    assert [c.branch for c in checkout.children] == ["feature-a", "feature-b"]


def test_the_current_branch_is_not_offered_for_checkout():
    """Basculer sur la branche où l'on est déjà n'a pas de sens."""
    entries = build_menu_model((_multi_branch_node(),), _on_main())
    checkout = _find(entries, "Switch / Checkout to revision")

    assert "main" not in [c.label for c in checkout.children]


def test_checkout_stays_available_beside_the_current_branch():
    """Le nœud porte HEAD, mais basculer vers une voisine reste légitime.

    `is_current` valait vrai pour tout le nœud, ce qui grisait le checkout
    même vers les autres branches.
    """
    entries = build_menu_model((_multi_branch_node(),), _on_main())
    checkout = _find(entries, "Switch / Checkout to revision")

    assert checkout.enabled is True
    assert all(c.enabled for c in checkout.children)


def test_a_single_branch_keeps_a_plain_entry():
    """Pas de sous-menu inutile quand il n'y a qu'une branche."""
    oid = "b" * 40
    node = DisplayNode(
        oid=oid,
        kind=NodeKind.REF,
        refs=(Ref("solo", RefType.LOCAL_BRANCH, oid),),
    )
    entries = build_menu_model((node,), _on_main())
    checkout = _find(entries, "Switch / Checkout to revision")

    assert checkout.children == ()
    assert checkout.branch == "solo"
