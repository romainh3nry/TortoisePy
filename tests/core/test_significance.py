from tortoisepy.core.refs import collect_refs
from tortoisepy.core.significance import significant_commits


def test_ref_tips_are_significant(repo_diverged):
    refs = collect_refs(repo_diverged.repo)
    result = significant_commits(repo_diverged.repo, refs)
    assert repo_diverged.master_tip in result
    assert repo_diverged.feature_tip in result


def test_merge_base_is_significant(repo_diverged):
    """Le cas central de §4.2 : sans C, deux composantes déconnectées."""
    refs = collect_refs(repo_diverged.repo)
    result = significant_commits(repo_diverged.repo, refs)
    assert repo_diverged.merge_base_expected in result


def test_intermediate_commits_are_not_significant(repo_long_linear):
    """Mille commits sans ref ne doivent pas devenir significatifs."""
    refs = collect_refs(repo_long_linear.repo)
    result = significant_commits(repo_long_linear.repo, refs)
    assert len(result) < 10


def test_root_is_significant(repo_linear):
    refs = collect_refs(repo_linear.repo)
    result = significant_commits(repo_linear.repo, refs)
    walker = list(repo_linear.repo.walk(repo_linear.repo.head.target))
    root = str(walker[-1].id)
    assert root in result


def test_both_merge_bases_are_significant(repo_two_merge_bases):
    """Le test décisif de cette tâche.

    Toute implémentation reposant sur une API merge-base de pygit2 échoue
    ici : elles retournent un seul OID là où le dépôt en a deux. Seul le
    parcours du DAG avec marquage par pointe les trouve tous.

    La vérité terrain vient de `git merge-base -a`, pas de pygit2.
    """
    import subprocess

    repo = repo_two_merge_bases.repo
    truth = set(
        subprocess.run(
            ["git", "merge-base", "-a",
             repo_two_merge_bases.tip_a, repo_two_merge_bases.tip_b],
            cwd=repo.workdir, capture_output=True, text=True, check=True,
        ).stdout.split()
    )
    assert len(truth) == 2, "la fixture ne produit pas deux merge-bases"

    result = significant_commits(repo, collect_refs(repo))
    for base in truth:
        assert base in result, f"merge-base {base[:7]} manquant"


def test_octopus_merge_is_significant(repo_octopus):
    """Fixture 12 : quatre parents, aucun indexé en dur."""
    refs = collect_refs(repo_octopus.repo)
    result = significant_commits(repo_octopus.repo, refs)
    assert repo_octopus.octopus_oid in result


def test_empty_repository_yields_nothing(tmp_path):
    import pygit2
    repo = pygit2.init_repository(str(tmp_path / "empty"))
    assert significant_commits(repo, ()) == set()
