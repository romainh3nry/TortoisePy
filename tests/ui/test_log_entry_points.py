"""Les points d'entrée vers la fenêtre de journal.

Trois chemins, demandés par l'utilisateur :

  - clic droit sur une branche → **Show log**. L'entrée existait au menu
    depuis le début mais ne faisait **rien** : `_show_log` rendait un
    succès vide, avec le commentaire « le panneau latéral affiche déjà les
    commits ». Elle est enfin câblée.
  - clic droit sur un fichier, dans le détail d'un commit → **File
    history**, la question qu'aucun écran ne savait traiter.
  - depuis la fenêtre de blâme → l'historique du fichier blâmé.

Les fenêtres filles doivent être **retenues** : sans référence, le
ramasse-miettes les ferme aussitôt ouvertes (piège vécu dans ce projet).
"""

from __future__ import annotations

import pygit2
import pytest

from tortoisepy.ui.log_window import LogWindow


@pytest.fixture
def depot(tmp_path):
    repo = pygit2.init_repository(str(tmp_path / "d"), initial_head="master")
    sig = pygit2.Signature("Test", "t@example.com", 0, 0)

    def commit(message, fichiers, parents):
        builder = repo.TreeBuilder()
        for nom, contenu in sorted(fichiers.items()):
            builder.insert(
                nom, repo.create_blob(contenu.encode()),
                pygit2.GIT_FILEMODE_BLOB,
            )
        return str(repo.create_commit(
            "refs/heads/master", sig, sig, message, builder.write(),
            [pygit2.Oid(hex=p) for p in parents],
        ))

    un = commit("ajoute a", {"a.txt": "v1"}, [])
    commit("modifie a", {"a.txt": "v2", "b.txt": "v1"}, [un])
    return repo


@pytest.fixture
def fenetre(qtbot, depot):
    from tortoisepy.ui.main_window import MainWindow

    w = MainWindow(depot)
    qtbot.addWidget(w)
    return w


# --- Show log sur une branche -------------------------------------------


def test_show_log_opens_a_log_window(qtbot, fenetre):
    """L'entrée de menu ne faisait rien jusqu'ici.

    `show_log` vient du menu du GRAPHE, donc de `_run_action` — pas du
    panneau latéral, qui a son propre jeu d'actions par commit.
    """
    noeud = fenetre.graph.nodes[0]
    fenetre._run_action("show_log", noeud)

    ouvertes = [f for f in fenetre._log_windows if isinstance(f, LogWindow)]
    assert ouvertes, "« Show log » n'ouvre aucune fenêtre"


def test_show_log_targets_the_clicked_branch(qtbot, fenetre):
    """Le journal doit porter sur la branche visée, pas sur HEAD par défaut."""
    fenetre.open_log(ref="master")

    assert fenetre._log_windows[-1].ref == "master"


def test_the_log_window_is_retained(qtbot, fenetre):
    """Sans référence, le ramasse-miettes la ferme aussitôt ouverte."""
    fenetre.open_log(ref="master")

    assert len(fenetre._log_windows) == 1
    assert fenetre._log_windows[0].isVisible()


def test_closing_a_log_window_forgets_it(qtbot, fenetre):
    """Sinon la liste grossirait sans fin au fil d'une session.

    Chaque fenêtre fermée resterait vivante en mémoire avec son
    `Repository` et sa liste de commits — le même défaut que les fenêtres
    de détail, déjà traité par `_forget_detail_window`.
    """
    fenetre.open_log(ref="master")
    fille = fenetre._log_windows[0]

    fille.close()
    qtbot.waitUntil(lambda: fenetre._log_windows == [], timeout=5000)


def test_several_log_windows_can_coexist(qtbot, fenetre):
    """Comparer l'histoire de deux fichiers est un usage légitime.

    Elles sont en lecture seule, donc rien n'impose l'unicité — à la
    différence de la fenêtre de commit, qui écrit l'index.
    """
    fenetre.open_log(ref="master")
    fenetre.open_log(ref="master", path="a.txt")

    assert len(fenetre._log_windows) == 2


# --- historique d'un fichier --------------------------------------------


def test_opening_a_file_history_passes_the_path(qtbot, fenetre):
    """Le chemin doit arriver jusqu'à la fenêtre, sinon elle montre tout."""
    fenetre.open_log(ref="master", path="a.txt")

    fille = fenetre._log_windows[-1]
    assert fille.path == "a.txt"


def test_the_detail_window_offers_the_file_history(qtbot, depot):
    """Le menu contextuel par fichier existait déjà : on s'y greffe."""
    from tortoisepy.ui.commit_detail_window import CommitDetailWindow

    fenetre = CommitDetailWindow(depot, str(depot.head.target))
    qtbot.addWidget(fenetre)

    entrees = fenetre.context_actions_for_row(0)

    assert any("history" in entree.lower() for entree in entrees), (
        f"aucune entrée d'historique de fichier : {entrees}"
    )


def test_the_detail_window_opens_the_history_of_the_right_file(qtbot, depot):
    """Le chemin de la LIGNE visée, pas le premier fichier du commit.

    La fenêtre ouvre et retient ses filles elle-même, comme elle le fait
    déjà pour le blâme (`blame_windows`) : même convention, pas de signal
    supplémentaire à inventer.
    """
    from tortoisepy.ui.commit_detail_window import CommitDetailWindow

    fenetre = CommitDetailWindow(depot, str(depot.head.target))
    qtbot.addWidget(fenetre)

    fenetre.log_row(0)

    journaux = [f for f in fenetre.blame_windows if isinstance(f, LogWindow)]
    assert journaux, "aucune fenêtre de journal ouverte"

    attendu = fenetre._files.topLevelItem(0).text(0)
    assert journaux[0].path in attendu or attendu in journaux[0].path, (
        f"chemin inattendu : {journaux[0].path} pour la ligne « {attendu} »"
    )


# --- navigation depuis le journal ---------------------------------------


def test_activating_a_commit_opens_its_detail(qtbot, fenetre):
    """Double-clic dans le journal : voir ce que le commit a changé."""
    fenetre.open_log(ref="master")
    fille = fenetre._log_windows[-1]

    fille.commit_activated.emit(str(fenetre.repository.head.target))

    assert fenetre._detail_windows, "aucun détail de commit n'a été ouvert"


# --- garantie de lecture seule ------------------------------------------


def test_opening_a_log_writes_nothing(qtbot, fenetre, depot):
    """§7.0 : seule une action explicite de l'utilisateur écrit."""
    refs_avant = {r: str(depot.references[r].target) for r in depot.references}

    fenetre.open_log(ref="master")
    fenetre.open_log(ref="master", path="a.txt")

    assert {
        r: str(depot.references[r].target) for r in depot.references
    } == refs_avant


def test_destroying_a_parent_mid_read_does_not_abort(qtbot, depot):
    """Régression : un `QThread` détruit en pleine exécution tue le processus.

    Reproduit pendant le développement de cette fonctionnalité, et c'était
    un **abort du processus** (`Fatal Python error: Aborted`), pas une
    exception rattrapable — donc un plantage sec de l'application.

    Le scénario réel : ouvrir l'historique d'un fichier depuis le détail
    d'un commit, puis refermer aussitôt ce détail. La fenêtre fille est
    alors détruite par le lien parent Qt **sans que son `closeEvent`
    passe**, et sa lecture tourne encore — d'autant plus probable que le
    dépôt est gros.

    Le garde-fou vit dans `BackgroundTask` (signal `destroyed` du parent),
    donc il protège toutes les fenêtres à tâche de fond, pas seulement
    celle-ci.
    """
    import gc

    from tortoisepy.ui.commit_detail_window import CommitDetailWindow

    detail = CommitDetailWindow(depot, str(depot.head.target))
    detail.log_row(0)

    journal = detail.blame_windows[-1]
    assert journal._task.is_running(), (
        "la lecture doit encore tourner, sinon le test ne prouve rien"
    )

    # Destruction SANS fermeture : le chemin qui plantait.
    del detail
    del journal
    gc.collect()   # ne doit pas abandonner le processus
