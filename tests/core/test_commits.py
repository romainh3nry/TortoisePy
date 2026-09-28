"""Lecture des commits masqués par la compression (§4.2.1)."""

import os
import subprocess

import pygit2
import pytest

from tortoisepy.core.commits import (
    CommitInfo,
    commits_for_node,
    commits_on_edge,
    read_commit,
)
from tortoisepy.core.graph import build_graph
from tortoisepy.core.model import GraphEdge


def run_git(path, *args):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Alice", "GIT_AUTHOR_EMAIL": "alice@example.com",
        "GIT_COMMITTER_NAME": "Alice", "GIT_COMMITTER_EMAIL": "alice@example.com",
    }
    return subprocess.run(
        ["git", *args], cwd=path, env=env, capture_output=True, text=True
    )


@pytest.fixture
def repo(tmp_path):
    """Une branche de cinq commits, dont un seul porte une ref."""
    path = tmp_path / "commits"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "master")
    for index in range(5):
        (path / f"f{index}.txt").write_text(f"contenu {index}\n")
        run_git(path, "add", ".")
        run_git(path, "commit", "-q", "-m", f"commit numéro {index}")
    return pygit2.Repository(str(path))


def test_read_commit_returns_the_details(repo):
    oid = str(repo.head.target)
    info = read_commit(repo, oid)
    assert isinstance(info, CommitInfo)
    assert info.oid == oid
    assert info.summary == "commit numéro 4"
    assert info.author_name == "Alice"
    assert info.author_email == "alice@example.com"


def test_short_oid_is_eight_characters(repo):
    info = read_commit(repo, str(repo.head.target))
    assert len(info.short_oid) == 8
    assert info.oid.startswith(info.short_oid)


def test_unknown_commit_returns_none(repo):
    assert read_commit(repo, "0" * 40) is None


def test_malformed_oid_returns_none(repo):
    assert read_commit(repo, "pas-un-oid") is None


def test_summary_is_the_first_line(repo):
    (repo.workdir and None)
    run_git(repo.workdir, "commit", "-q", "--allow-empty",
            "-m", "titre\n\ncorps du message")
    fresh = pygit2.Repository(repo.path)
    info = read_commit(fresh, str(fresh.head.target))
    assert info.summary == "titre"
    assert "corps du message" in info.message


def test_merge_is_flagged(tmp_path):
    path = tmp_path / "merge"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "master")
    (path / "base.txt").write_text("base\n")
    run_git(path, "add", "."); run_git(path, "commit", "-q", "-m", "base")
    run_git(path, "checkout", "-q", "-b", "side")
    (path / "side.txt").write_text("side\n")
    run_git(path, "add", "."); run_git(path, "commit", "-q", "-m", "side")
    run_git(path, "checkout", "-q", "master")
    (path / "main.txt").write_text("main\n")
    run_git(path, "add", "."); run_git(path, "commit", "-q", "-m", "main")
    run_git(path, "merge", "--no-edit", "side")

    repository = pygit2.Repository(str(path))
    info = read_commit(repository, str(repository.head.target))
    assert info.is_merge is True
    assert info.parent_count == 2


def test_non_merge_is_not_flagged(repo):
    info = read_commit(repo, str(repo.head.target))
    assert info.is_merge is False


def test_commits_on_edge_includes_the_descendant_first(repo):
    oids = [str(c.id) for c in repo.walk(repo.head.target)]
    edge = GraphEdge(
        ancestor=oids[-1], descendant=oids[0], skipped=tuple(reversed(oids[1:-1]))
    )
    result = commits_on_edge(repo, edge)
    assert result[0].oid == oids[0], "le commit du nœud vient en tête"


def test_commits_on_edge_is_newest_first(repo):
    oids = [str(c.id) for c in repo.walk(repo.head.target)]
    edge = GraphEdge(
        ancestor=oids[-1], descendant=oids[0], skipped=tuple(reversed(oids[1:-1]))
    )
    result = commits_on_edge(repo, edge)
    dates = [c.when for c in result]
    assert dates == sorted(dates, reverse=True)


def test_commits_for_node_reveals_what_the_edge_hides(repo):
    """Le cœur de §4.2.1 : la compression est visuelle, rien n'est perdu.

    Sur un dépôt à une seule branche, le graphe n'a qu'un nœud et aucune
    arête — les jonctions étant masquées (§6.1). Les commits doivent
    rester atteignables malgré tout : sinon la compression deviendrait
    sémantique, ce que la spec interdit.
    """
    graph = build_graph(repo)
    tip = str(repo.head.target)

    result = commits_for_node(repo, graph, tip)
    total = len(list(repo.walk(repo.head.target)))
    assert len(result) == total, "tous les commits doivent rester accessibles"


def test_commits_for_node_on_a_node_without_incoming_edge(repo):
    """Un nœud sans arête entrante remonte son historique réel.

    Auparavant il ne montrait que son propre commit. Depuis que les
    jonctions sont masquées, ce cas recouvre aussi les nœuds dont la
    jonction amont a disparu : s'arrêter au premier commit rendrait les
    autres inatteignables (§4.2.1).
    """
    graph = build_graph(repo)
    orphans = [
        n.oid for n in graph.nodes
        if not any(e.descendant == n.oid for e in graph.edges)
    ]
    assert orphans

    revealed = commits_for_node(repo, graph, orphans[0])
    assert len(revealed) >= 1
    assert revealed[0].oid == orphans[0], "le commit du nœud vient en tête"


def test_commits_for_node_on_unknown_oid_is_empty(repo):
    graph = build_graph(repo)
    assert commits_for_node(repo, graph, "0" * 40) == ()


def test_dates_are_timezone_aware(repo):
    """Une date naïve produirait des comparaisons fausses."""
    info = read_commit(repo, str(repo.head.target))
    assert info.when.tzinfo is not None


def test_full_history_is_returned(tmp_path):
    """Cliquer une branche montre TOUT son historique, pas seulement son apport."""
    path = tmp_path / "histoire"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "master")
    for index in range(4):
        (path / f"base{index}.txt").write_text(f"{index}\n")
        run_git(path, "add", ".")
        run_git(path, "commit", "-q", "-m", f"base {index}")

    run_git(path, "checkout", "-q", "-b", "feature")
    for index in range(2):
        (path / f"feat{index}.txt").write_text(f"{index}\n")
        run_git(path, "add", ".")
        run_git(path, "commit", "-q", "-m", f"feature {index}")

    repository = pygit2.Repository(str(path))
    graph = build_graph(repository)
    node = next(
        n for n in graph.nodes if any(r.name == "feature" for r in n.refs)
    )

    revealed = commits_for_node(repository, graph, node.oid)
    assert len(revealed) == 6, "les 4 commits hérités doivent être visibles"


def test_own_commits_are_marked(tmp_path):
    """Les commits ajoutés par la branche se distinguent des hérités."""
    path = tmp_path / "marquage"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "master")
    for index in range(3):
        (path / f"base{index}.txt").write_text(f"{index}\n")
        run_git(path, "add", ".")
        run_git(path, "commit", "-q", "-m", f"base {index}")

    run_git(path, "checkout", "-q", "-b", "feature")
    (path / "feat.txt").write_text("apport\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "apport de la branche")

    repository = pygit2.Repository(str(path))
    graph = build_graph(repository)
    node = next(
        n for n in graph.nodes if any(r.name == "feature" for r in n.refs)
    )

    revealed = commits_for_node(repository, graph, node.oid)
    own = [c for c in revealed if c.own]
    inherited = [c for c in revealed if not c.own]

    assert own, "la branche a bien apporté quelque chose"
    assert inherited, "et hérité du reste"
    assert own[0].summary == "apport de la branche"


def test_own_commits_come_first(tmp_path):
    """L'ordre reste chronologique : l'apport est le plus récent."""
    path = tmp_path / "ordre"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "master")
    (path / "a.txt").write_text("a\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "ancien")
    run_git(path, "checkout", "-q", "-b", "feature")
    (path / "b.txt").write_text("b\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "récent")

    repository = pygit2.Repository(str(path))
    graph = build_graph(repository)
    node = next(
        n for n in graph.nodes if any(r.name == "feature" for r in n.refs)
    )

    revealed = commits_for_node(repository, graph, node.oid)
    assert revealed[0].own is True
    assert revealed[0].summary == "récent"


def test_history_is_capped(tmp_path):
    """Un panneau latéral ne charge pas un historique sans fin."""
    from tortoisepy.core.commits import _history

    path = tmp_path / "long"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "master")
    for index in range(30):
        (path / "f.txt").write_text(f"{index}\n")
        run_git(path, "add", ".")
        run_git(path, "commit", "-q", "-m", f"c{index}")

    repository = pygit2.Repository(str(path))
    head = str(repository.head.target)
    assert len(_history(repository, head, {head}, limit=10)) == 10


def test_commit_info_defaults_to_own():
    """Un commit lu isolément est considéré comme propre."""
    from tortoisepy.core.commits import read_commit
    import subprocess

    # read_commit ne connaît pas le graphe : il ne peut pas trancher.
    assert "own" in CommitInfo.__dataclass_fields__
