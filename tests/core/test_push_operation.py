import os
import subprocess

import pygit2
import pytest

from tortoisepy.core.operations import push_branch


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
    """Un dépôt nu servant de serveur, et un clone de travail."""
    bare = tmp_path / "serveur.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", str(bare)], capture_output=True
    )
    work = tmp_path / "travail"
    subprocess.run(
        ["git", "clone", "-q", str(bare), str(work)], capture_output=True
    )
    (work / "f.txt").write_text("base\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "base")
    run_git(work, "push", "-q", "origin", "HEAD")
    return bare, pygit2.Repository(str(work))


def server_log(bare) -> str:
    return subprocess.run(
        ["git", "log", "--oneline"], cwd=bare, capture_output=True, text=True
    ).stdout


def test_push_sends_the_commit(pair):
    bare, repo = pair
    (repo.workdir and None)
    from pathlib import Path
    Path(repo.workdir, "f.txt").write_text("suite\n")
    run_git(repo.workdir, "add", ".")
    run_git(repo.workdir, "commit", "-q", "-m", "à pousser")

    result = push_branch(repo)
    assert result.success is True, result.git_error
    assert "à pousser" in server_log(bare)


def test_push_uses_the_current_branch(pair):
    """Vérifié : un clone récent est sur `main`, pas `master`."""
    bare, repo = pair
    run_git(repo.workdir, "checkout", "-q", "-b", "une-autre-branche")
    from pathlib import Path
    Path(repo.workdir, "g.txt").write_text("x\n")
    run_git(repo.workdir, "add", ".")
    run_git(repo.workdir, "commit", "-q", "-m", "sur une autre branche")

    result = push_branch(repo)
    assert result.success is True, result.git_error

    refs = subprocess.run(
        ["git", "branch"], cwd=bare, capture_output=True, text=True
    ).stdout
    assert "une-autre-branche" in refs


def test_rejected_push_reports_the_server_message(pair, tmp_path):
    """Review Focus 5 : le serveur a avancé entre-temps."""
    bare, repo = pair

    other = tmp_path / "concurrent"
    subprocess.run(
        ["git", "clone", "-q", str(bare), str(other)], capture_output=True
    )
    (other / "concurrent.txt").write_text("x\n")
    run_git(other, "add", ".")
    run_git(other, "commit", "-q", "-m", "concurrent")
    run_git(other, "push", "-q")

    from pathlib import Path
    Path(repo.workdir, "local.txt").write_text("y\n")
    run_git(repo.workdir, "add", ".")
    run_git(repo.workdir, "commit", "-q", "-m", "local")

    result = push_branch(repo)
    assert result.success is False
    assert result.git_error


def test_push_without_remote_fails_cleanly(tmp_path):
    path = tmp_path / "sans-remote"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "f.txt").write_text("a\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "base")

    result = push_branch(pygit2.Repository(str(path)))
    assert result.success is False
    assert "remote" in (result.git_error or "").lower()


def test_push_from_detached_head_fails_cleanly(pair):
    """Sans branche, il n'y a rien à pousser."""
    bare, repo = pair
    head = str(repo.head.target)
    run_git(repo.workdir, "checkout", "-q", "--detach", head)

    result = push_branch(pygit2.Repository(repo.path))
    assert result.success is False


def test_push_does_not_change_the_local_graph(pair):
    """Pousser n'ajoute ni ne déplace de ref locale."""
    bare, repo = pair
    before = {r for r in repo.references}
    push_branch(repo)
    assert {r for r in repo.references} == before


def test_push_reports_progress(pair):
    """Le rappel de progression doit être celui du push, pas du fetch."""
    bare, repo = pair
    from pathlib import Path
    Path(repo.workdir, "f.txt").write_text("suite\n")
    run_git(repo.workdir, "add", ".")
    run_git(repo.workdir, "commit", "-q", "-m", "à pousser")

    seen = []
    result = push_branch(repo, on_progress=lambda a, b: seen.append((a, b)))
    assert result.success is True, result.git_error
    assert seen, (
        "push_transfer_progress n'a pas été appelé — FetchCallbacks utilise "
        "transfer_progress, qui est la progression du fetch"
    )


def test_progress_callback_takes_three_arguments():
    """Vérifié : la signature du push a un argument de plus que le fetch.

    `push_transfer_progress(objects_pushed, total_objects, bytes_pushed)`.
    Une méthode à deux paramètres lèverait TypeError pendant le push.
    """
    import inspect

    from tortoisepy.core.operations import PushCallbacks

    signature = inspect.signature(PushCallbacks.push_transfer_progress)
    assert len(signature.parameters) == 4  # self + 3


def test_rejection_message_is_not_reported_as_success(pair, monkeypatch):
    """Un refus annoncé par le serveur ne doit pas passer pour un succès.

    `remote.push()` ne lève pas dans ce cas : le refus arrive par
    `push_update_reference`. Sans cette vérification, l'utilisateur lit
    « Pushed main to origin » alors que rien n'est arrivé.
    """
    import pygit2

    from tortoisepy.core import operations

    bare, repo = pair

    def refuse(self, refspecs, callbacks=None):
        callbacks.push_update_reference(
            "refs/heads/main", "pre-receive hook declined"
        )

    monkeypatch.setattr(pygit2.Remote, "push", refuse)

    result = operations.push_branch(repo)
    assert result.success is False
    assert "declined" in (result.git_error or "")


def test_push_follows_the_configured_upstream_not_alphabetical_order(pair, tmp_path):
    """Review Finding 1 : `remotes.names()` est alphabétique, pas l'intention.

    Un second remote nommé `aaa-upstream` trierait avant `origin` ; sans
    suivre le suivi configuré de la branche, le push partirait vers le
    mauvais dépôt — le scénario classique du fork.
    """
    bare, repo = pair

    other_bare = tmp_path / "aaa-upstream.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", str(other_bare)], capture_output=True
    )
    run_git(repo.workdir, "remote", "add", "aaa-upstream", str(other_bare))
    run_git(repo.workdir, "push", "-q", "aaa-upstream", "HEAD")
    run_git(
        repo.workdir,
        "branch",
        "--set-upstream-to=origin/main",
        "main",
    )

    from pathlib import Path
    Path(repo.workdir, "f.txt").write_text("suite\n")
    run_git(repo.workdir, "add", ".")
    run_git(repo.workdir, "commit", "-q", "-m", "à pousser vers origin")

    result = push_branch(repo)
    assert result.success is True, result.git_error
    assert "à pousser vers origin" in server_log(bare)
    assert "à pousser vers origin" not in server_log(other_bare)


def test_push_prefers_origin_when_no_upstream_is_configured(pair, tmp_path):
    """Sans suivi configuré, `origin` gagne sur l'ordre alphabétique."""
    bare, repo = pair

    other_bare = tmp_path / "aaa-upstream.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", str(other_bare)], capture_output=True
    )
    run_git(repo.workdir, "remote", "add", "aaa-upstream", str(other_bare))
    # Pas de `branch --set-upstream-to` : aucun suivi configuré.

    from pathlib import Path
    Path(repo.workdir, "f.txt").write_text("suite\n")
    run_git(repo.workdir, "add", ".")
    run_git(repo.workdir, "commit", "-q", "-m", "à pousser vers origin aussi")

    result = push_branch(repo)
    assert result.success is True, result.git_error
    assert "à pousser vers origin aussi" in server_log(bare)
    assert "à pousser vers origin aussi" not in server_log(other_bare)


def _serveur_et_clone(tmp_path, nom="moi"):
    """Un dépôt nu et un clone qui a poussé « main »."""
    bare = tmp_path / "serveur.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], capture_output=True)
    work = tmp_path / nom
    subprocess.run(["git", "clone", "-q", str(bare), str(work)], capture_output=True)
    (work / "f.txt").write_text("a\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "base")
    run_git(work, "push", "-q", "origin", "HEAD")
    return bare, work


def test_a_forced_push_lands_when_the_server_is_untouched(tmp_path):
    """Le bail tient : on remplace son propre historique."""
    bare, work = _serveur_et_clone(tmp_path)
    run_git(work, "commit", "-q", "--amend", "-m", "base reecrit")

    result = push_branch(pygit2.Repository(str(work)), force_with_lease=True)
    assert result.success is True, result.git_error

    serveur = pygit2.Repository(str(bare))
    assert [c.message.strip() for c in serveur.walk(
        serveur.references["refs/heads/main"].target
    )] == ["base reecrit"]


def test_a_forced_push_loses_the_race_to_nobody(tmp_path):
    """Le défaut Critical de la revue : la course détruisait un commit.

    L'ancienne conception vérifiait le bail **côté client**, puis poussait
    un refspec « + » qui force sans condition. Un collègue poussant dans
    cet intervalle voyait son travail détruit *alors que le bail venait
    d'être jugé valide*. Reproduit à l'époque : le serveur ne gardait plus
    que `['base reecrit']`.

    Le bail est désormais arbitré par le serveur, donc pousser pendant
    l'opération ne peut plus rien écraser silencieusement.
    """
    bare, work = _serveur_et_clone(tmp_path)
    autre = tmp_path / "collegue"
    subprocess.run(
        ["git", "clone", "-q", str(bare), str(autre)], capture_output=True
    )

    # Le collègue pousse pendant que nous préparons notre réécriture.
    (autre / "g.txt").write_text("collegue\n")
    run_git(autre, "add", ".")
    run_git(autre, "commit", "-q", "-m", "travail du collegue")
    run_git(autre, "push", "-q", "origin", "HEAD")
    attendu = str(pygit2.Repository(str(autre)).head.target)

    run_git(work, "commit", "-q", "--amend", "-m", "base reecrit")
    result = push_branch(pygit2.Repository(str(work)), force_with_lease=True)

    assert result.success is False
    serveur = pygit2.Repository(str(bare))
    assert str(serveur.references["refs/heads/main"].target) == attendu, (
        "le commit du collègue a été écrasé"
    )


def test_the_refusal_says_to_fetch_first(tmp_path):
    """« stale info » ne dit pas quoi faire ; notre message le dit."""
    bare, work = _serveur_et_clone(tmp_path)
    autre = tmp_path / "collegue"
    subprocess.run(
        ["git", "clone", "-q", str(bare), str(autre)], capture_output=True
    )
    (autre / "g.txt").write_text("c\n")
    run_git(autre, "add", ".")
    run_git(autre, "commit", "-q", "-m", "collegue")
    run_git(autre, "push", "-q", "origin", "HEAD")

    run_git(work, "commit", "-q", "--amend", "-m", "reecrit")
    result = push_branch(pygit2.Repository(str(work)), force_with_lease=True)
    detail = (result.git_error or "").lower()
    assert "fetch" in detail, detail
    assert "stale info" not in detail, "message brut de git non traduit"


def test_a_forced_push_of_a_brand_new_branch(tmp_path):
    """Review Focus 1 : une première publication n'écrase rien."""
    _, work = _serveur_et_clone(tmp_path)
    run_git(work, "checkout", "-q", "-b", "toute-neuve")
    (work / "n.txt").write_text("neuf\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "neuf")

    result = push_branch(pygit2.Repository(str(work)), force_with_lease=True)
    assert result.success is True, result.git_error


def test_a_normal_push_is_still_not_forced(tmp_path):
    """Garde-fou D15 : aucun chemin ne force sans qu'on le demande."""
    from tortoisepy.core.operations import push_branch

    _, work = _serveur_et_clone(tmp_path)
    repo = pygit2.Repository(str(work))
    envoyes = []
    vrai_push = pygit2.Remote.push

    def espion(self, specs, **kwargs):
        envoyes.extend(specs)
        return vrai_push(self, specs, **kwargs)

    pygit2.Remote.push = espion
    try:
        push_branch(repo)
    finally:
        pygit2.Remote.push = vrai_push

    assert envoyes, "aucun refspec envoyé"
    assert not any(s.startswith("+") for s in envoyes), envoyes


def test_a_forced_push_lands_after_a_rebase(tmp_path):
    """La raison d'être de la phase : le push normal échouait ici."""
    from tortoisepy.core.operations import push_branch
    from tortoisepy.core.rebase import start_rebase

    bare, work = _serveur_et_clone(tmp_path)
    run_git(work, "checkout", "-q", "-b", "feature")
    (work / "g.txt").write_text("mon travail\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "mon travail")
    run_git(work, "push", "-q", "origin", "feature")

    run_git(work, "checkout", "-q", "main")
    (work / "h.txt").write_text("avance\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "avance main")
    run_git(work, "push", "-q", "origin", "main")
    run_git(work, "checkout", "-q", "feature")

    start_rebase(pygit2.Repository(str(work)), "main")

    refuse = push_branch(pygit2.Repository(str(work)))
    assert refuse.success is False, "le push normal devrait être rejeté"

    force = push_branch(pygit2.Repository(str(work)), force_with_lease=True)
    assert force.success is True, force.git_error

    serveur = pygit2.Repository(str(bare))
    local = pygit2.Repository(str(work))
    assert str(serveur.references["refs/heads/feature"].target) == str(
        local.references["refs/heads/feature"].target
    )


def test_a_forced_push_refuses_to_erase_a_colleague(tmp_path):
    """L'assertion qui compte : son commit est toujours là."""
    from tortoisepy.core.operations import push_branch

    bare, work = _serveur_et_clone(tmp_path)
    autre = tmp_path / "collegue"
    subprocess.run(["git", "clone", "-q", str(bare), str(autre)], capture_output=True)
    (autre / "g.txt").write_text("collegue\n")
    run_git(autre, "add", ".")
    run_git(autre, "commit", "-q", "-m", "travail du collegue")
    run_git(autre, "push", "-q", "origin", "HEAD")
    attendu = str(pygit2.Repository(str(autre)).head.target)

    (work / "f.txt").write_text("reecrit\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "--amend", "-m", "base reecrit")

    result = push_branch(pygit2.Repository(str(work)), force_with_lease=True)
    assert result.success is False
    assert "fetch" in (result.git_error or "").lower()

    serveur = pygit2.Repository(str(bare))
    assert str(serveur.references["refs/heads/main"].target) == attendu, (
        "le commit du collègue a été écrasé"
    )


def test_push_with_pushurl_only_remote_does_not_raise_attributeerror(pair):
    """Review Finding 2 : un remote sans `url` (seulement `pushurl`) ne doit
    pas faire planter `_credentials` avec un `AttributeError` brut.

    `remote.url` vaut alors `None`. Vérifié séparément (hors suite, car
    le crash n'est pas rattrapable par pytest) : passer ce remote tel quel
    à `remote.push()` fait planter le **processus entier** par segfault
    dans libgit2 1.20 — un bug de la bibliothèque, pas de tortoisePy, que
    `git` en CLI n'a pas dans cette même configuration. Comme aucun
    `try/except` Python ne protège d'un segfault, `push_branch` doit
    détecter `remote.url is None` et refuser *avant* d'appeler
    `remote.push()`, plutôt que de risquer soit l'`AttributeError` (ancien
    comportement, via `_credentials`), soit le crash.
    """
    bare, repo = pair

    config = repo.config
    config["remote.origin.pushurl"] = str(bare)
    del config["remote.origin.url"]

    from pathlib import Path
    Path(repo.workdir, "f.txt").write_text("suite\n")
    run_git(repo.workdir, "add", ".")
    run_git(repo.workdir, "commit", "-q", "-m", "via pushurl")

    result = push_branch(repo)
    assert result.success is False
    assert "AttributeError" not in (result.git_error or "")
    assert "origin" in (result.git_error or "")


def test_a_forced_push_works_on_a_pushurl_only_remote(tmp_path):
    """Revue finale, Minor : refus à tort, avec un motif hors sujet.

    Les garde-fous de `push_branch` protègent d'un segfault de libgit2 sur
    un remote `pushurl`-only. Le push forcé passe par `git`, qui n'a pas
    ce défaut — invoquer « pygit2 crashes » dans un chemin sans pygit2
    refusait une opération parfaitement valide.
    """
    bare, work = _serveur_et_clone(tmp_path)
    run_git(work, "config", "--unset", "remote.origin.url")
    run_git(work, "config", "remote.origin.pushurl", str(bare))
    run_git(work, "commit", "-q", "--amend", "-m", "base reecrit")

    result = push_branch(pygit2.Repository(str(work)), force_with_lease=True)
    assert result.success is True, result.git_error

    serveur = pygit2.Repository(str(bare))
    assert [c.message.strip() for c in serveur.walk(
        serveur.references["refs/heads/main"].target
    )] == ["base reecrit"]


def test_a_timed_out_forced_push_says_so(tmp_path, monkeypatch):
    """Un délai dépassé doit se dire, pas se déguiser en autre chose.

    `repository_changed=True` : un `git push` interrompu peut avoir déjà
    mis à jour le serveur et la ref de suivi. Prétendre le contraire
    supprimerait le rafraîchissement qui le montrerait.
    """
    from tortoisepy.core import operations

    _, work = _serveur_et_clone(tmp_path)

    def trop_long(*a, **k):
        raise subprocess.TimeoutExpired(cmd="git push", timeout=1)

    monkeypatch.setattr(operations.subprocess, "run", trop_long)
    result = push_branch(pygit2.Repository(str(work)), force_with_lease=True)

    assert result.success is False
    assert "timed out" in (result.git_error or "")
    assert result.repository_changed is True


def _avec_branche_distante(tmp_path):
    """Un serveur, un clone, et une branche `feature` poussée."""
    bare, work = _serveur_et_clone(tmp_path)
    run_git(work, "checkout", "-q", "-b", "feature")
    (work / "g.txt").write_text("travail\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "travail")
    run_git(work, "push", "-q", "origin", "feature")
    run_git(work, "checkout", "-q", "main")
    return bare, work


def test_deleting_a_remote_branch_removes_it_from_the_server(tmp_path):
    from tortoisepy.core.operations import delete_remote_branch

    bare, work = _avec_branche_distante(tmp_path)
    result = delete_remote_branch(pygit2.Repository(str(work)), "feature")
    assert result.success is True, result.git_error

    serveur = pygit2.Repository(str(bare))
    assert "refs/heads/feature" not in list(serveur.references)
    assert "refs/heads/main" in list(serveur.references)


def test_deleting_a_remote_branch_keeps_the_local_one(tmp_path):
    """Les deux entrées du menu sont distinctes : celle-ci ne touche pas au local."""
    from tortoisepy.core.operations import delete_remote_branch

    _, work = _avec_branche_distante(tmp_path)
    delete_remote_branch(pygit2.Repository(str(work)), "feature")

    local = pygit2.Repository(str(work))
    assert "feature" in list(local.branches.local), (
        "la branche locale doit survivre"
    )


def test_deleting_a_branch_absent_from_the_server_is_refused(tmp_path):
    """pygit2 accepte en silence (vérifié) ; `git` refuse, et c'est mieux.

    Un nom mal tapé passerait sinon pour une réussite.
    """
    from tortoisepy.core.operations import delete_remote_branch

    _, work = _avec_branche_distante(tmp_path)
    result = delete_remote_branch(pygit2.Repository(str(work)), "nexiste-pas")
    assert result.success is False
    assert "does not exist" in (result.git_error or "").lower()


def test_deleting_the_servers_default_branch_is_refused(tmp_path):
    """Le garde-fou que libgit2 n'applique pas.

    Vérifié : le refspec `:refs/heads/main` de pygit2 a **détruit** `main`
    sur un dépôt nu, alors que `git push --delete` le refuse
    (« deletion of the current branch prohibited »). D'où la délégation.
    """
    from tortoisepy.core.operations import delete_remote_branch

    bare, work = _avec_branche_distante(tmp_path)
    result = delete_remote_branch(pygit2.Repository(str(work)), "main")

    assert result.success is False
    serveur = pygit2.Repository(str(bare))
    assert "refs/heads/main" in list(serveur.references), (
        "la branche par défaut du serveur ne doit pas disparaître"
    )


def test_deleting_a_remote_branch_without_a_remote_is_refused(tmp_path):
    from tortoisepy.core.operations import delete_remote_branch

    path = tmp_path / "seul"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "f.txt").write_text("a\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "base")

    # Une branche NON protégée : sinon c'est la protection qui répond,
    # et non l'absence de remote qu'on veut éprouver ici.
    run_git(path, "checkout", "-q", "-b", "feature")

    result = delete_remote_branch(pygit2.Repository(str(path)), "feature")
    assert result.success is False
    assert "no remote" in (result.git_error or "").lower()


def test_integration_branches_cannot_be_deleted_remotely(tmp_path):
    """Demandé par l'utilisateur, et git ne suffit pas.

    Git ne protège que la branche par défaut du serveur : **vérifié**,
    `develop` et `master` ont été supprimées sans résistance sur un dépôt
    dont la branche par défaut était `main`. Perdre la branche
    d'intégration d'une équipe ne doit pas tenir à un clic.
    """
    from tortoisepy.core.operations import (
        PROTECTED_BRANCHES,
        delete_remote_branch,
    )

    bare, work = _serveur_et_clone(tmp_path)
    for nom in ("develop", "master"):
        run_git(work, "checkout", "-q", "-b", nom)
        (work / f"{nom}.txt").write_text("x\n")
        run_git(work, "add", ".")
        run_git(work, "commit", "-q", "-m", nom)
        run_git(work, "push", "-q", "origin", nom)
    run_git(work, "checkout", "-q", "main")

    assert PROTECTED_BRANCHES == {"main", "master", "develop"}

    serveur = pygit2.Repository(str(bare))
    for nom in sorted(PROTECTED_BRANCHES):
        result = delete_remote_branch(pygit2.Repository(str(work)), nom)
        assert result.success is False, nom
        assert "integration branch" in (result.git_error or ""), nom
        assert f"refs/heads/{nom}" in list(serveur.references), (
            f"{nom} ne doit pas disparaître du serveur"
        )


def test_an_ordinary_branch_is_still_deletable(tmp_path):
    """La protection ne doit pas bloquer le cas normal."""
    from tortoisepy.core.operations import delete_remote_branch

    bare, work = _avec_branche_distante(tmp_path)
    result = delete_remote_branch(pygit2.Repository(str(work)), "feature")
    assert result.success is True, result.git_error
    assert "refs/heads/feature" not in list(pygit2.Repository(str(bare)).references)


def test_a_server_refusal_is_reported_without_its_boilerplate(tmp_path):
    """Un refus serveur tient en une ligne, pas en douze.

    Vérifié : git répond une douzaine de lignes `remote:` de conseils de
    configuration, où « deletion of the current branch prohibited » se
    perd.
    """
    from tortoisepy.core.operations import _refus_de_suppression

    sortie = (
        "remote: error: By default, deleting the current branch is denied,\n"
        "remote: You can set 'receive.denyDeleteCurrent' configuration\n"
        "To ../s2.git\n"
        " ! [remote rejected] main (deletion of the current branch prohibited)\n"
        "error: failed to push some refs to '../s2.git'\n"
    )
    assert _refus_de_suppression(sortie) == (
        "[remote rejected] main (deletion of the current branch prohibited)"
    )
    assert _refus_de_suppression("") == "deletion failed"
