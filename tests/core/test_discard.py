"""Annuler des modifications non commitées.

Demandé par l'utilisateur : « j'aimerai qu'il soit possible d'annuler
les changements depuis le graph — un clic droit sur un changement pour
pouvoir l'annuler unitairement, et un bouton permettant d'annuler tous
les changements en cours ».

C'est la **seule opération de l'application qui détruit du travail
absent de Git**. Un `reset --hard` perd des commits, mais le reflog les
garde 90 jours ; un fichier modifié qu'on annule n'existe nulle part.
D'où le filet demandé : un stash est posé avant chaque annulation, et
`git stash pop` ramène tout.

Deux pièges mesurés avant d'écrire :

  - **`repo.stash(paths=[...])` vide l'arbre de travail ENTIER.** Un
    stash de `a.txt` seul ramenait aussi `b.txt` à son état commité,
    sans que `b.txt` figure dans le stash : son travail était perdu
    pour de bon. La séquence correcte est stash complet, puis
    `stash_apply`, puis le checkout du seul fichier visé ;
  - **les fichiers non suivis n'ont aucune version à restaurer.** Les
    « annuler » reviendrait à les supprimer, ce que `git checkout --`
    ne fait pas, et qu'`abort_operation` refuse déjà dans ce projet
    (« Untracked files are left alone »).
"""

from __future__ import annotations

import os
import subprocess

import pygit2
import pytest

from tortoisepy.core.discard import discard_all, discard_file


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
def depot(tmp_path):
    """Deux fichiers modifiés, un fichier jamais ajouté."""
    chemin = tmp_path / "travail"
    chemin.mkdir()
    run_git(chemin, "init", "-q", "-b", "main")
    for nom in ("a.txt", "b.txt"):
        (chemin / nom).write_text("origine\n")
    run_git(chemin, "add", ".")
    run_git(chemin, "commit", "-q", "-m", "base")

    (chemin / "a.txt").write_text("modifié A\n")
    (chemin / "b.txt").write_text("modifié B\n")
    (chemin / "neuf.txt").write_text("jamais ajouté\n")

    return pygit2.Repository(str(chemin))


def _contenu(repo, nom):
    return (pathlib_chemin(repo) / nom).read_text()


def pathlib_chemin(repo):
    from pathlib import Path

    return Path(repo.workdir)


# --- annuler un fichier -------------------------------------------------


def test_discarding_one_file_restores_it(depot):
    """Le besoin demandé : annuler un changement, unitairement."""
    resultat = discard_file(depot, "a.txt")

    assert resultat.success, resultat.summary
    assert _contenu(depot, "a.txt") == "origine\n"


def test_discarding_one_file_leaves_the_others_alone(depot):
    """LE piège mesuré, et le plus coûteux.

    `repo.stash(paths=["a.txt"])` crée bien un stash ne contenant que
    `a.txt`, mais vide l'arbre de travail ENTIER : `b.txt` revenait à
    « origine » sans figurer dans le stash. Son travail était perdu
    sans que rien ne le signale.
    """
    discard_file(depot, "a.txt")

    assert _contenu(depot, "b.txt") == "modifié B\n", (
        "le travail d'un fichier voisin a été détruit"
    )


def test_discarding_never_touches_untracked_files(depot):
    """Un fichier jamais ajouté n'a aucune version à restaurer.

    L'« annuler » reviendrait à le supprimer. `git checkout --` ne le
    fait pas, et `abort_operation` le refuse déjà ici.
    """
    discard_file(depot, "a.txt")

    assert (pathlib_chemin(depot) / "neuf.txt").exists(), (
        "un fichier non suivi a été supprimé"
    )


def test_discarding_an_untracked_file_is_refused(depot):
    """Et on refuse explicitement de l'annuler, plutôt que de ne rien
    faire en silence.

    Rendre un succès sans agir laisserait croire que le fichier a été
    traité.
    """
    resultat = discard_file(depot, "neuf.txt")

    assert not resultat.success
    assert "untracked" in resultat.summary.lower()
    assert (pathlib_chemin(depot) / "neuf.txt").exists()


def test_discarding_one_file_leaves_a_stash(depot):
    """Le filet demandé : le travail reste récupérable.

    C'est ce qui distingue cette opération d'un `git checkout --` nu.
    """
    avant = len(list(depot.listall_stashes()))

    discard_file(depot, "a.txt")

    assert len(list(depot.listall_stashes())) == avant + 1


def test_the_stash_really_holds_the_lost_work(depot):
    """Le stash doit contenir ce qui a été annulé, sinon il ne sert à
    rien.

    Un test qui compte les stashs sans vérifier leur contenu passerait
    avec un stash vide.

    La récupération passe par `checkout`, PAS par `stash pop` : mesuré,
    `pop` échoue sur « 1 conflict prevents checkout » dès qu'un autre
    fichier du stash est encore modifié — le cas habituel après une
    annulation unitaire. En ligne de commande, `git stash pop` ne
    restaure alors rien et conserve le stash. C'est pourquoi le message
    de `discard_file` donne `git checkout stash@{0} -- <fichier>`.
    """
    discard_file(depot, "a.txt")

    run_git(pathlib_chemin(depot), "checkout", "stash@{0}", "--", "a.txt")

    assert _contenu(depot, "a.txt") == "modifié A\n", (
        "le stash ne contenait pas le travail annulé"
    )
    assert _contenu(depot, "b.txt") == "modifié B\n", (
        "la récupération a écrasé le travail d'un voisin"
    )


def test_the_message_gives_a_command_that_works(depot):
    """Le message doit donner la commande qui marche VRAIMENT.

    Annoncer « git stash pop » serait faux pour une annulation
    unitaire : mesuré, la commande échoue et ne restaure rien. Donner
    une commande qui ne marche pas, au moment précis où l'utilisateur
    cherche à récupérer son travail, est pire que ne rien dire.
    """
    resultat = discard_file(depot, "a.txt")

    assert "checkout stash@{0}" in resultat.summary, resultat.summary
    assert "stash pop" not in resultat.summary, (
        "le message promet une commande qui échoue dans ce cas"
    )


def test_discarding_an_unknown_file_is_refused(depot):
    """Un chemin qui n'existe pas ne doit pas créer un stash pour rien."""
    avant = len(list(depot.listall_stashes()))

    resultat = discard_file(depot, "jamais-vu.txt")

    assert not resultat.success
    assert len(list(depot.listall_stashes())) == avant


def test_discarding_an_unchanged_file_is_refused(depot):
    """Un fichier sans modification : rien à annuler.

    Sans ce contrôle, on poserait un stash inutile à chaque clic.
    """
    run_git(pathlib_chemin(depot), "checkout", "--", "a.txt")
    avant = len(list(depot.listall_stashes()))

    resultat = discard_file(depot, "a.txt")

    assert not resultat.success
    assert len(list(depot.listall_stashes())) == avant


# --- tout annuler -------------------------------------------------------


def test_discarding_all_restores_every_tracked_file(depot):
    """Le second besoin : un bouton pour tout annuler."""
    resultat = discard_all(depot)

    assert resultat.success, resultat.summary
    assert _contenu(depot, "a.txt") == "origine\n"
    assert _contenu(depot, "b.txt") == "origine\n"


def test_discarding_all_keeps_untracked_files(depot):
    """Même règle que pour l'annulation unitaire.

    « Tout annuler » ne veut pas dire « tout supprimer » : un fichier
    neuf qu'on vient d'écrire n'est pas un changement à défaire.
    """
    discard_all(depot)

    assert (pathlib_chemin(depot) / "neuf.txt").exists()
    assert (
        pathlib_chemin(depot) / "neuf.txt"
    ).read_text() == "jamais ajouté\n"


def test_discarding_all_leaves_one_stash(depot):
    """Un seul stash pour l'ensemble, pas un par fichier."""
    avant = len(list(depot.listall_stashes()))

    discard_all(depot)

    assert len(list(depot.listall_stashes())) == avant + 1


def test_the_whole_work_is_recoverable(depot):
    """Tout annuler doit rester récupérable d'un seul `stash pop`."""
    discard_all(depot)

    depot.stash_pop(0)

    assert _contenu(depot, "a.txt") == "modifié A\n"
    assert _contenu(depot, "b.txt") == "modifié B\n"


def test_discarding_all_with_nothing_to_do_is_refused(tmp_path):
    """Un arbre propre : pas de stash vide, pas de faux succès."""
    chemin = tmp_path / "propre"
    chemin.mkdir()
    run_git(chemin, "init", "-q", "-b", "main")
    (chemin / "f.txt").write_text("x\n")
    run_git(chemin, "add", ".")
    run_git(chemin, "commit", "-q", "-m", "base")
    repo = pygit2.Repository(str(chemin))

    resultat = discard_all(repo)

    assert not resultat.success
    assert list(repo.listall_stashes()) == []


def test_untracked_files_alone_are_not_a_reason_to_discard(tmp_path):
    """Seulement des fichiers non suivis : rien à annuler.

    Le piège : les compter comme « des changements en cours » ferait
    poser un stash et rendre un succès, alors qu'aucun fichier ne
    serait touché.
    """
    chemin = tmp_path / "neufs"
    chemin.mkdir()
    run_git(chemin, "init", "-q", "-b", "main")
    (chemin / "f.txt").write_text("x\n")
    run_git(chemin, "add", ".")
    run_git(chemin, "commit", "-q", "-m", "base")
    (chemin / "neuf.txt").write_text("jamais ajouté\n")
    repo = pygit2.Repository(str(chemin))

    resultat = discard_all(repo)

    assert not resultat.success
    assert (chemin / "neuf.txt").exists()
    assert list(repo.listall_stashes()) == []


# --- ce qui doit rester vrai --------------------------------------------


def test_a_staged_change_is_discarded_too(depot):
    """Un fichier déjà ajouté à l'index doit être annulé aussi.

    L'utilisateur voit « modifié » dans la fenêtre des changements, que
    le fichier soit indexé ou non : annuler doit traiter les deux
    pareil, sans quoi le résultat dépendrait d'un état invisible.
    """
    run_git(pathlib_chemin(depot), "add", "a.txt")

    resultat = discard_file(depot, "a.txt")

    assert resultat.success, resultat.summary
    assert _contenu(depot, "a.txt") == "origine\n"
    assert "a.txt" not in depot.status()


def test_the_result_says_what_was_done(depot):
    """Le message doit nommer le fichier et le stash.

    « Done » ne permettrait pas de retrouver le stash en cas d'erreur
    — or c'est précisément le moment où on en a besoin.
    """
    resultat = discard_file(depot, "a.txt")

    assert "a.txt" in resultat.summary
    assert "stash" in resultat.summary.lower()
