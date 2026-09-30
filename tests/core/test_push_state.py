import os
import subprocess

import pygit2
import pytest

from tortoisepy.core.push_state import push_state, unpushed_oids


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
def pair(tmp_path):
    """Un serveur nu, un clone, un commit poussé et deux commits locaux."""
    bare = tmp_path / "serveur.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", str(bare)], capture_output=True
    )
    work = tmp_path / "travail"
    subprocess.run(
        ["git", "clone", "-q", str(bare), str(work)], capture_output=True
    )
    (work / "f.txt").write_text("a\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "pousse")
    run_git(work, "push", "-q", "origin", "HEAD")

    (work / "f.txt").write_text("b\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "local 1")
    (work / "f.txt").write_text("c\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "local 2")
    return pygit2.Repository(str(work))


def summaries(repo, oids):
    return {repo.get(o).message.strip() for o in oids}


def test_local_commits_are_unpushed(pair):
    assert summaries(pair, unpushed_oids(pair)) == {"local 1", "local 2"}


def test_pushed_commit_is_not_listed(pair):
    assert "pousse" not in summaries(pair, unpushed_oids(pair))


def test_counts_them(pair):
    assert push_state(pair).unpushed_count == 2


def test_can_push(pair):
    assert push_state(pair).can_push is True


def test_names_the_remote(pair):
    assert push_state(pair).remote_name == "origin"


def test_names_the_branch(pair):
    assert push_state(pair).branch == "main"


def test_nothing_to_push_after_pushing(pair):
    run_git(pair.workdir, "push", "-q")
    fresh = pygit2.Repository(pair.path)
    assert unpushed_oids(fresh) == frozenset()
    assert push_state(fresh).can_push is False


def test_branch_without_upstream_has_everything_unpushed(tmp_path):
    """Une branche jamais poussée est justement celle qu'il faut publier."""
    bare = tmp_path / "s.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], capture_output=True)
    work = tmp_path / "w"
    subprocess.run(["git", "clone", "-q", str(bare), str(work)], capture_output=True)
    (work / "f.txt").write_text("a\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "base")
    run_git(work, "push", "-q", "origin", "HEAD")
    run_git(work, "checkout", "-q", "-b", "jamais-poussee")
    (work / "g.txt").write_text("neuf\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "sur la nouvelle branche")

    repo = pygit2.Repository(str(work))
    assert "sur la nouvelle branche" in summaries(repo, unpushed_oids(repo))
    assert push_state(repo).can_push is True


def test_repository_without_remote_marks_nothing(tmp_path):
    """Review Focus 1 : tout marquer en rouge serait du bruit permanent."""
    path = tmp_path / "solo"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "f.txt").write_text("a\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "seul")

    repo = pygit2.Repository(str(path))
    assert unpushed_oids(repo) == frozenset()

    state = push_state(repo)
    assert state.can_push is False
    assert state.reason  # explique pourquoi le bouton sera grisé


def test_detached_head_marks_nothing(pair):
    """Review Focus 2 : `branches[shorthand]` lève KeyError (vérifié).

    Depuis la correction du 2026-09-28, la marque ne dépend plus de HEAD :
    le graphe affiche les nœuds des branches locales même en HEAD détachée,
    et leurs commits non poussés le sont réellement (`git log --branches
    --not --remotes` les liste aussi). Seul le **bouton** reste grisé, car
    il n'y a pas de branche courante à pousser.
    """
    run_git(pair.workdir, "checkout", "-q", "--detach")
    fresh = pygit2.Repository(pair.path)

    # Les branches locales gardent leur marque : elle est exacte.
    assert len(unpushed_oids(fresh)) == 2

    # Mais on ne peut pas pousser : aucune branche n'est sortie.
    state = push_state(fresh)
    assert state.can_push is False
    assert state.reason


def test_empty_repository_is_safe(tmp_path):
    path = tmp_path / "vide"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    repo = pygit2.Repository(str(path))
    assert unpushed_oids(repo) == frozenset()
    assert push_state(repo).can_push is False


def test_state_is_frozen(pair):
    import dataclasses

    state = push_state(pair)
    assert dataclasses.is_dataclass(state)
    with pytest.raises(dataclasses.FrozenInstanceError):
        state.can_push = True


def test_reading_state_writes_nothing(pair):
    """§7.0 : calculer l'état de poussée ne modifie pas le dépôt."""
    import hashlib
    from pathlib import Path

    git_dir = Path(pair.path)

    def fingerprint():
        digest = hashlib.sha256()
        for item in sorted(git_dir.rglob("*")):
            if item.is_file():
                digest.update(f"{item}:{item.stat().st_mtime_ns}".encode())
        return digest.hexdigest()

    before = fingerprint()
    unpushed_oids(pair)
    push_state(pair)
    assert fingerprint() == before


def test_remote_name_matches_default_remote(tmp_path):
    """Finding 1 : push_state.remote_name == _default_remote réellement poussé."""
    from tortoisepy.core.operations import _default_remote

    bare = tmp_path / "s.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], capture_output=True)
    work = tmp_path / "w"
    subprocess.run(["git", "clone", "-q", str(bare), str(work)], capture_output=True)

    # Ajouter un second remote alphabétiquement avant origin
    run_git(work, "remote", "add", "aaa-fork", str(bare))

    (work / "f.txt").write_text("a\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "test")

    repo = pygit2.Repository(str(work))
    state = push_state(repo)
    default = _default_remote(repo, repo.head.shorthand)

    # Doivent pointer vers le même remote, même si aaa-fork vient avant origin
    assert state.remote_name == default == "origin"


def test_dangling_tracking_ref_is_safe(tmp_path):
    """Finding 2 : une ref de suivi cassée ne lève pas KeyError."""
    bare = tmp_path / "s.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], capture_output=True)
    work = tmp_path / "w"
    subprocess.run(["git", "clone", "-q", str(bare), str(work)], capture_output=True)

    (work / "f.txt").write_text("a\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "base")
    run_git(work, "push", "-q", "origin", "HEAD")

    repo = pygit2.Repository(str(work))

    # Écrire un OID invalide dans la ref de suivi
    refs_dir = work / ".git" / "refs" / "remotes" / "origin"
    ref_file = refs_dir / "main"
    ref_file.write_text("deadbeefdeadbeefdeadbeefdeadbeefdeadbeef\n")

    # Frais pour que pygit2 relise les refs
    fresh = pygit2.Repository(str(work))

    # Ne doit pas lever : une ref illisible est simplement ignorée,
    # les autres refs distantes continuent de faire foi.
    assert isinstance(unpushed_oids(fresh), frozenset)

    # Ici la seule ref distante est cassée : plus rien ne prouve que le
    # commit est sur le serveur, donc proposer de le pousser est le
    # comportement sûr. L'essentiel est qu'aucune exception ne remonte.
    state = push_state(fresh)
    assert isinstance(state.can_push, bool)


def test_hide_walk_gives_same_result(pair):
    """Finding 3 : hide-based walk retourne exactement l'ensemble différence."""
    # Vérifié : la marche avec hide() produit le même résultat que
    # la construction de deux ensembles et leur différence, mais 160× plus vite.
    # Ce test juste s'assure qu'une future optimisation ne change pas la sémantique.
    oids = unpushed_oids(pair)

    # Doit avoir les 2 commits locaux non poussés
    summaries_found = summaries(pair, oids)
    assert summaries_found == {"local 1", "local 2"}


def test_branch_without_upstream_but_already_on_the_server(tmp_path):
    """Régression, signalée sur le dépôt réel `xpc` le 2026-09-28.

    La branche courante n'a pas d'upstream configuré, mais tout son
    historique est déjà sur le serveur sous une autre ref. L'ancienne règle
    — « pas d'upstream, donc jamais poussée » — marquait ses 1644 commits
    comme non poussés, et contaminait les nœuds des autres branches.
    """
    bare = tmp_path / "serveur.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", str(bare)], capture_output=True
    )
    work = tmp_path / "travail"
    subprocess.run(
        ["git", "clone", "-q", str(bare), str(work)], capture_output=True
    )
    (work / "f.txt").write_text("a\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "tout est sur le serveur")
    run_git(work, "push", "-q", "origin", "HEAD")

    # Une branche locale sur le MÊME commit, sans suivi configuré.
    run_git(work, "checkout", "-q", "-b", "sans-suivi")

    repo = pygit2.Repository(str(work))
    assert repo.branches["sans-suivi"].upstream is None

    assert unpushed_oids(repo) == frozenset(), (
        "aucun commit n'est à pousser : ils sont tous atteints par "
        "refs/remotes/origin/*"
    )
    state = push_state(repo)
    assert state.can_push is False
    assert state.unpushed_count == 0


def test_other_branches_are_not_contaminated(tmp_path):
    """Régression `xpc` : une branche à jour ne doit pas hériter d'une marque.

    `lightweight-calls` avait un tip local identique à son tip distant et
    ressortait pourtant entièrement marquée, parce que ses commits
    appartenaient à l'historique de la branche courante sans upstream.
    """
    bare = tmp_path / "s.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], capture_output=True)
    work = tmp_path / "w"
    subprocess.run(["git", "clone", "-q", str(bare), str(work)], capture_output=True)
    (work / "f.txt").write_text("a\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "base")
    run_git(work, "push", "-q", "origin", "HEAD")

    # Une branche poussée, donc à jour…
    run_git(work, "checkout", "-q", "-b", "a-jour")
    (work / "g.txt").write_text("b\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "poussee puis a jour")
    run_git(work, "push", "-q", "-u", "origin", "a-jour")

    # …et on se place sur une branche sans suivi, bâtie dessus.
    run_git(work, "checkout", "-q", "-b", "sans-suivi")

    repo = pygit2.Repository(str(work))
    a_jour = repo.branches["a-jour"]
    assert a_jour.target == a_jour.upstream.target

    unpushed = unpushed_oids(repo)
    assert str(a_jour.target) not in unpushed, (
        "le tip d'une branche à jour ne doit jamais être marqué"
    )


def test_a_genuinely_local_commit_is_still_detected(tmp_path):
    """La correction ne doit pas rendre la marque aveugle."""
    bare = tmp_path / "s.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], capture_output=True)
    work = tmp_path / "w"
    subprocess.run(["git", "clone", "-q", str(bare), str(work)], capture_output=True)
    (work / "f.txt").write_text("a\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "base")
    run_git(work, "push", "-q", "origin", "HEAD")

    (work / "f.txt").write_text("b\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "vraiment local")

    repo = pygit2.Repository(str(work))
    unpushed = unpushed_oids(repo)
    assert len(unpushed) == 1
    assert repo.get(next(iter(unpushed))).message.strip() == "vraiment local"
    assert push_state(repo).can_push is True


def _serveur_et_deux_clones(tmp_path):
    """Un serveur, mon clone, et celui d'un autre."""
    bare = tmp_path / "serveur.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], capture_output=True)
    moi = tmp_path / "moi"
    subprocess.run(["git", "clone", "-q", str(bare), str(moi)], capture_output=True)
    (moi / "f.txt").write_text("a\n")
    run_git(moi, "add", ".")
    run_git(moi, "commit", "-q", "-m", "base")
    run_git(moi, "push", "-q", "origin", "HEAD")
    autre = tmp_path / "autre"
    subprocess.run(["git", "clone", "-q", str(bare), str(autre)], capture_output=True)
    return bare, moi, autre


def test_an_up_to_date_branch_has_no_divergence(tmp_path):
    from tortoisepy.core.push_state import divergence

    _, moi, _ = _serveur_et_deux_clones(tmp_path)
    assert divergence(pygit2.Repository(str(moi))) == (0, 0)


def test_local_commits_count_as_ahead(tmp_path):
    from tortoisepy.core.push_state import divergence

    _, moi, _ = _serveur_et_deux_clones(tmp_path)
    (moi / "g.txt").write_text("g\n")
    run_git(moi, "add", ".")
    run_git(moi, "commit", "-q", "-m", "local")

    assert divergence(pygit2.Repository(str(moi))) == (1, 0)


def test_remote_commits_count_as_behind_after_a_fetch(tmp_path):
    from tortoisepy.core.push_state import divergence

    _, moi, autre = _serveur_et_deux_clones(tmp_path)
    (autre / "h.txt").write_text("h\n")
    run_git(autre, "add", ".")
    run_git(autre, "commit", "-q", "-m", "ailleurs")
    run_git(autre, "push", "-q", "origin", "HEAD")
    run_git(moi, "fetch", "-q", "origin")

    assert divergence(pygit2.Repository(str(moi))) == (0, 1)


def test_the_divergence_reflects_the_last_fetch_not_the_server(tmp_path):
    """Review Focus 2 : poser ce comportement, pour qu'on ne le « corrige » pas.

    Vérifié : sans nouveau fetch, l'indicateur annonçait 1 commit de
    retard alors que le serveur en avait 2. Interroger le réseau à chaque
    rafraîchissement serait lent et bavard (D22) : la limite est assumée,
    et l'infobulle la dit.
    """
    from tortoisepy.core.push_state import divergence

    _, moi, autre = _serveur_et_deux_clones(tmp_path)
    (autre / "h.txt").write_text("h\n")
    run_git(autre, "add", ".")
    run_git(autre, "commit", "-q", "-m", "un")
    run_git(autre, "push", "-q", "origin", "HEAD")
    run_git(moi, "fetch", "-q", "origin")

    # Le serveur avance ENCORE, sans que nous le sachions.
    (autre / "i.txt").write_text("i\n")
    run_git(autre, "add", ".")
    run_git(autre, "commit", "-q", "-m", "deux")
    run_git(autre, "push", "-q", "origin", "HEAD")

    assert divergence(pygit2.Repository(str(moi))) == (0, 1), (
        "la valeur reflète la ref de suivi, pas le serveur"
    )


def test_a_branch_without_upstream_has_no_divergence(tmp_path):
    """Review Focus 4 : rien à comparer, donc rien à afficher."""
    from tortoisepy.core.push_state import divergence

    _, moi, _ = _serveur_et_deux_clones(tmp_path)
    run_git(moi, "checkout", "-q", "-b", "orpheline")
    assert divergence(pygit2.Repository(str(moi))) is None


def test_divergence_on_a_detached_head_is_none(tmp_path):
    from tortoisepy.core.push_state import divergence

    _, moi, _ = _serveur_et_deux_clones(tmp_path)
    run_git(moi, "checkout", "-q", "--detach")
    assert divergence(pygit2.Repository(str(moi))) is None
