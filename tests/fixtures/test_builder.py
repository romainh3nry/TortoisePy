import pygit2


def test_linear_has_four_commits(repo_linear):
    commits = list(repo_linear.repo.walk(repo_linear.repo.head.target))
    assert len(commits) == 4


def test_diverged_branches_are_not_ancestors(repo_diverged):
    """Le cœur du problème de §4.2, vérifié sur la fixture."""
    repo = repo_diverged.repo
    master = pygit2.Oid(hex=repo_diverged.master_tip)
    feature = pygit2.Oid(hex=repo_diverged.feature_tip)
    assert not repo.descendant_of(master, feature)
    assert not repo.descendant_of(feature, master)


def test_diverged_merge_base_is_c(repo_diverged):
    repo = repo_diverged.repo
    base = repo.merge_base(
        pygit2.Oid(hex=repo_diverged.master_tip),
        pygit2.Oid(hex=repo_diverged.feature_tip),
    )
    assert str(base) == repo_diverged.merge_base_expected


def test_merge_commit_has_two_parents(repo_merge):
    commit = repo_merge.repo.get(repo_merge.merge_oid)
    assert len(commit.parents) == 2


def test_long_linear_has_1001_commits(repo_long_linear):
    commits = list(repo_long_linear.repo.walk(pygit2.Oid(hex=repo_long_linear.tip_oid)))
    assert len(commits) == 1001
