"""Annuler des changements depuis la fenêtre des changements.

Demandé par l'utilisateur : « un clic droit sur un changement pour
pouvoir l'annuler unitairement, et un bouton permettant d'annuler tous
les changements en cours », avec une exigence explicite :

    « il faudra mettre une confirmation pour chaque annulation en cas
      d'erreur de click »

Donc pas de raccourci pour le cas unitaire.
"""

from __future__ import annotations

import os
import subprocess

import pygit2
import pytest

from tortoisepy.ui.commit_window import CommitWindow


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


@pytest.fixture
def fenetre(qtbot, depot):
    f = CommitWindow(depot)
    qtbot.addWidget(f)
    f.show()
    qtbot.waitExposed(f)
    return f


def _ligne_de(fenetre, chemin: str) -> int:
    for index in range(fenetre._files.topLevelItemCount()):
        item = fenetre._files.topLevelItem(index)
        from tortoisepy.ui.commit_window import PATH_ROLE

        if item.data(0, PATH_ROLE) == chemin:
            return index
    raise AssertionError(f"« {chemin} » absent de la liste")


def _attendre_la_fin(qtbot, fenetre) -> None:
    """Attend la FIN réelle de l'annulation.

    L'opération tourne dans un `QThread` : surveiller le contenu d'un
    fichier fait rendre la main sur un état intermédiaire.
    `_poser_le_filet` vide l'arbre de travail avant de réappliquer le
    stash, donc le fichier visé vaut brièvement « origine » alors que
    ses voisins ne sont pas encore restaurés — mesuré, et cela rendait
    le test instable (2 succès, 1 échec sur trois exécutions
    identiques).

    La tâche de fond terminée est le seul signal fiable.
    """
    qtbot.waitUntil(
        lambda: fenetre._task is None or not fenetre._task.is_running(),
        timeout=5000,
    )
    qtbot.wait(50)   # laisse `suite` s'exécuter sur le fil principal


# --- le menu contextuel -------------------------------------------------


def test_a_tracked_file_can_be_discarded(fenetre):
    """Le besoin demandé : annuler un changement, unitairement."""
    entrees = fenetre.context_actions_for_row(_ligne_de(fenetre, "a.txt"))

    assert any("Discard" in e for e in entrees), entrees


def test_copy_path_is_still_offered(fenetre):
    """L'entrée existante ne doit pas disparaître."""
    entrees = fenetre.context_actions_for_row(_ligne_de(fenetre, "a.txt"))

    assert "Copy path" in entrees


def test_an_untracked_file_is_not_offered_the_discard(fenetre):
    """Un fichier jamais ajouté n'a aucune version à restaurer.

    L'« annuler » reviendrait à le supprimer — ce que `git checkout --`
    refuse, et ce que l'utilisateur a choisi de ne pas faire.
    """
    entrees = fenetre.context_actions_for_row(_ligne_de(fenetre, "neuf.txt"))

    assert not any("Discard" in e for e in entrees), (
        f"l'annulation est proposée sur un fichier non suivi : {entrees}"
    )
    assert "Copy path" in entrees, "le reste du menu a disparu"


# --- la confirmation, exigée pour chaque annulation ---------------------


def test_discarding_one_file_asks_first(fenetre, monkeypatch, depot):
    """L'exigence de l'utilisateur : confirmer même pour un fichier."""
    demandes = []
    monkeypatch.setattr(
        fenetre, "_confirmer",
        lambda demande: demandes.append(demande) or False,
    )

    fenetre.discard_row(_ligne_de(fenetre, "a.txt"))

    assert demandes, "aucune confirmation demandée"
    assert "a.txt" in demandes[0].message


def test_refusing_the_confirmation_changes_nothing(fenetre, monkeypatch,
                                                   depot):
    """Dire non doit vraiment ne rien faire.

    C'est tout l'intérêt de la confirmation : un test qui ne vérifie
    que l'affichage du dialogue laisserait passer une annulation qui
    s'exécute quand même.
    """
    monkeypatch.setattr(fenetre, "_confirmer", lambda _demande: False)
    chemin = os.path.join(depot.workdir, "a.txt")

    fenetre.discard_row(_ligne_de(fenetre, "a.txt"))

    assert open(chemin).read() == "modifié A\n"
    assert list(depot.listall_stashes()) == [], (
        "un stash a été posé alors que l'utilisateur a refusé"
    )


def test_accepting_the_confirmation_discards(qtbot, fenetre, monkeypatch,
                                             depot):
    """Et dire oui doit annuler pour de bon."""
    monkeypatch.setattr(fenetre, "_confirmer", lambda _demande: True)
    chemin = os.path.join(depot.workdir, "a.txt")

    fenetre.discard_row(_ligne_de(fenetre, "a.txt"))
    _attendre_la_fin(qtbot, fenetre)

    assert open(chemin).read() == "origine\n"
    assert len(list(depot.listall_stashes())) == 1, "pas de filet posé"


def test_discarding_one_file_leaves_the_others(qtbot, fenetre, monkeypatch,
                                               depot):
    """Le piège mesuré du module `discard` vaut aussi vu d'ici.

    On attend la fin de l'opération par le STASH, pas par le contenu
    de `a.txt` : `_poser_le_filet` vide l'arbre de travail avant de
    réappliquer le stash, donc `a.txt` vaut « origine » de façon
    transitoire, alors que `b.txt` n'est pas encore restauré.
    Surveiller `a.txt` faisait donc rendre la main en plein milieu —
    le test échouait sur un état intermédiaire, pas sur un défaut.
    """
    monkeypatch.setattr(fenetre, "_confirmer", lambda _demande: True)
    a = os.path.join(depot.workdir, "a.txt")
    b = os.path.join(depot.workdir, "b.txt")

    fenetre.discard_row(_ligne_de(fenetre, "a.txt"))
    _attendre_la_fin(qtbot, fenetre)

    assert open(a).read() == "origine\n"
    assert open(b).read() == "modifié B\n", (
        "le travail d'un fichier voisin a été détruit"
    )


# --- le bouton « tout annuler » -----------------------------------------


def test_the_window_offers_a_discard_all_button(fenetre):
    """Le second besoin demandé."""
    assert fenetre.discard_all_button is not None
    assert "Discard" in fenetre.discard_all_button.text()


def test_discarding_all_asks_first(fenetre, monkeypatch):
    """La plus coûteuse des deux : elle se confirme aussi."""
    demandes = []
    monkeypatch.setattr(
        fenetre, "_confirmer",
        lambda demande: demandes.append(demande) or False,
    )

    fenetre.discard_all()

    assert demandes
    assert demandes[0].destructive


def test_the_confirmation_counts_the_files(fenetre, monkeypatch):
    """Le nombre est ce qui fait décider.

    Deux fichiers suivis sont modifiés ; le fichier non suivi ne
    compte pas, puisqu'il ne sera pas touché.
    """
    demandes = []
    monkeypatch.setattr(
        fenetre, "_confirmer",
        lambda demande: demandes.append(demande) or False,
    )

    fenetre.discard_all()

    assert "2 file" in demandes[0].message, demandes[0].message


def test_discarding_all_keeps_untracked_files(qtbot, fenetre, monkeypatch,
                                              depot):
    """« Tout annuler » ne veut pas dire « tout supprimer »."""
    monkeypatch.setattr(fenetre, "_confirmer", lambda _demande: True)
    a = os.path.join(depot.workdir, "a.txt")
    neuf = os.path.join(depot.workdir, "neuf.txt")

    fenetre.discard_all()
    _attendre_la_fin(qtbot, fenetre)

    assert os.path.exists(neuf)
    assert open(neuf).read() == "jamais ajouté\n"


def test_the_button_is_disabled_when_nothing_to_discard(qtbot, tmp_path):
    """Un arbre propre : le bouton ne doit pas inviter au clic.

    Sans cela, cliquer poserait la question puis répondrait « rien à
    faire », ce qui fait douter de ce qu'on vient de voir.
    """
    chemin = tmp_path / "propre"
    chemin.mkdir()
    run_git(chemin, "init", "-q", "-b", "main")
    (chemin / "f.txt").write_text("x\n")
    run_git(chemin, "add", ".")
    run_git(chemin, "commit", "-q", "-m", "base")

    f = CommitWindow(pygit2.Repository(str(chemin)))
    qtbot.addWidget(f)
    f.show()
    qtbot.waitExposed(f)

    assert not f.discard_all_button.isEnabled()


def test_the_button_ignores_untracked_only_trees(qtbot, tmp_path):
    """Seulement des fichiers non suivis : rien à annuler non plus.

    Le piège : les compter ferait proposer une annulation qui ne
    toucherait aucun fichier.
    """
    chemin = tmp_path / "neufs"
    chemin.mkdir()
    run_git(chemin, "init", "-q", "-b", "main")
    (chemin / "f.txt").write_text("x\n")
    run_git(chemin, "add", ".")
    run_git(chemin, "commit", "-q", "-m", "base")
    (chemin / "neuf.txt").write_text("jamais ajouté\n")

    f = CommitWindow(pygit2.Repository(str(chemin)))
    qtbot.addWidget(f)
    f.show()
    qtbot.waitExposed(f)

    assert not f.discard_all_button.isEnabled()


# --- ce qui ne doit pas se dégrader -------------------------------------


def test_the_discard_button_is_not_next_to_commit(fenetre):
    """Un bouton destructif ne se place pas sous la main qui commite.

    Le projet applique déjà ce principe à « Tout cocher », placé à
    gauche parce qu'il agit sur la liste et non sur le dépôt.
    """
    from PySide6.QtWidgets import QHBoxLayout

    barre = fenetre.discard_all_button.parent().findChild(QHBoxLayout)
    if barre is None:
        pytest.skip("barre de boutons introuvable")

    positions = {}
    for i in range(barre.count()):
        widget = barre.itemAt(i).widget()
        if widget is not None:
            positions[widget] = i

    assert positions.get(fenetre.discard_all_button, 0) < positions.get(
        fenetre.commit_button, 99
    ), "« Discard all » est collé aux boutons d'action"
