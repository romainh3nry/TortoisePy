# tests/fixtures/test_hard_cases.py
import pygit2


def _git_merge_base_all(repo_path: str, a: str, b: str) -> set[str]:
    """Vérité terrain : `git merge-base -a`, qui énumère TOUTES les bases."""
    import subprocess
    out = subprocess.run(
        ["git", "merge-base", "-a", a, b],
        cwd=repo_path, capture_output=True, text=True, check=True,
    ).stdout.split()
    return set(out)


def test_two_merge_bases_really_exist(repo_two_merge_bases):
    """Si ce test échoue, la fixture ne reproduit pas le cas visé."""
    bases = _git_merge_base_all(
        repo_two_merge_bases.repo.workdir,
        repo_two_merge_bases.tip_a,
        repo_two_merge_bases.tip_b,
    )
    assert len(bases) == repo_two_merge_bases.expected_base_count


def test_pygit2_apis_cannot_enumerate_all_bases(repo_two_merge_bases):
    """Documente la limite qui impose le parcours du DAG en tâche 6.

    Vérifié sur pygit2 1.20.0 : les trois API retournent un OID unique là
    où le dépôt a deux merge-bases.
    """
    repo = repo_two_merge_bases.repo
    a = pygit2.Oid(hex=repo_two_merge_bases.tip_a)
    b = pygit2.Oid(hex=repo_two_merge_bases.tip_b)

    truth = _git_merge_base_all(
        repo.workdir, repo_two_merge_bases.tip_a, repo_two_merge_bases.tip_b
    )
    assert len(truth) == 2

    for name in ("merge_base", "merge_base_many", "merge_base_octopus"):
        api = getattr(repo, name, None)
        if api is None:
            continue
        result = api(a, b) if name == "merge_base" else api([a, b])
        assert isinstance(result, pygit2.Oid), (
            f"{name} retourne maintenant autre chose qu'un OID unique : "
            "réexaminer si le parcours du DAG reste nécessaire"
        )


def test_octopus_has_four_parents(repo_octopus):
    commit = repo_octopus.repo.get(repo_octopus.octopus_oid)
    assert len(commit.parents) == 4
