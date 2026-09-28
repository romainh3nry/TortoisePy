from tortoisepy.core.model import RefType
from tortoisepy.core.refs import collect_refs, group_refs_by_oid


def test_collects_local_branch(repo_linear):
    refs = collect_refs(repo_linear.repo)
    names = {r.name for r in refs if r.type is RefType.LOCAL_BRANCH}
    assert "master" in names


def test_collects_head(repo_linear):
    refs = collect_refs(repo_linear.repo)
    heads = [r for r in refs if r.type is RefType.HEAD]
    assert len(heads) == 1


def test_collects_both_branches_when_diverged(repo_diverged):
    refs = collect_refs(repo_diverged.repo)
    names = {r.name for r in refs if r.type is RefType.LOCAL_BRANCH}
    assert {"master", "feature"} <= names


def test_lightweight_tag_is_collected(repo_linear):
    oid = str(repo_linear.repo.head.target)
    repo_linear.tag_lightweight("v1.0", oid)
    refs = collect_refs(repo_linear.repo)
    tags = [r for r in refs if r.type is RefType.TAG]
    assert [t.name for t in tags] == ["v1.0"]
    assert tags[0].target == oid


def test_annotated_tag_is_peeled_to_commit(repo_linear):
    """§4.1 : un tag annoté est un objet `tag`, pas un `commit`.

    Sans déréférencement, target serait l'OID de l'objet tag, qui
    n'apparaît nulle part dans le DAG — le nœud serait orphelin.
    """
    oid = str(repo_linear.repo.head.target)
    repo_linear.tag_annotated("v2.0", oid)
    refs = collect_refs(repo_linear.repo)
    tag = next(r for r in refs if r.name == "v2.0")
    assert tag.target == oid


def test_remote_branch_is_typed_correctly(repo_linear):
    oid = str(repo_linear.repo.head.target)
    repo_linear.remote_ref("origin", "master", oid)
    refs = collect_refs(repo_linear.repo)
    remotes = [r for r in refs if r.type is RefType.REMOTE_BRANCH]
    assert [r.name for r in remotes] == ["origin/master"]


def test_group_by_oid_merges_refs_on_same_commit(repo_linear):
    """§4.1 : plusieurs refs sur un commit forment un seul groupe."""
    oid = str(repo_linear.repo.head.target)
    repo_linear.tag_lightweight("v1.0", oid)
    repo_linear.remote_ref("origin", "master", oid)
    grouped = group_refs_by_oid(collect_refs(repo_linear.repo))
    assert len(grouped[oid]) >= 3  # master, HEAD, v1.0, origin/master


def test_empty_repository_yields_no_refs(tmp_path):
    import pygit2
    repo = pygit2.init_repository(str(tmp_path / "empty"))
    assert collect_refs(repo) == ()


def test_symbolic_ref_is_resolved(repo_linear):
    """`refs/remotes/origin/HEAD` pointe vers une autre REF, pas un OID.

    Rencontré en ouvrant un vrai dépôt cloné : `ref.target` est alors une
    chaîne (« refs/remotes/origin/master »), et `repo.get()` levait un
    ValueError non rattrapé — l'application refusait d'ouvrir le dépôt.
    Presque tout dépôt cloné a cette ref.
    """
    oid = str(repo_linear.repo.head.target)
    repo_linear.remote_ref("origin", "master", oid)
    repo_linear.repo.create_reference(
        "refs/remotes/origin/HEAD", "refs/remotes/origin/master"
    )

    refs = collect_refs(repo_linear.repo)
    names = {r.name for r in refs}
    assert "origin/HEAD" in names

    symbolic = next(r for r in refs if r.name == "origin/HEAD")
    assert symbolic.target == oid, "la ref symbolique doit être résolue"


def test_symbolic_ref_groups_with_its_target(repo_linear):
    """origin/HEAD et origin/master partagent le même nœud."""
    oid = str(repo_linear.repo.head.target)
    repo_linear.remote_ref("origin", "master", oid)
    repo_linear.repo.create_reference(
        "refs/remotes/origin/HEAD", "refs/remotes/origin/master"
    )

    grouped = group_refs_by_oid(collect_refs(repo_linear.repo))
    names = {r.name for r in grouped[oid]}
    assert {"origin/HEAD", "origin/master"} <= names


def test_broken_symbolic_ref_is_skipped(repo_linear):
    """Une ref symbolique pointant dans le vide ne doit pas tout casser."""
    repo_linear.repo.create_reference(
        "refs/remotes/origin/HEAD", "refs/remotes/origin/inexistante"
    )
    refs = collect_refs(repo_linear.repo)  # ne doit pas lever
    assert all(r.name != "origin/HEAD" for r in refs)
