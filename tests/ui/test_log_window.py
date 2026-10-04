"""La fenêtre de journal : commits d'une branche, ou d'un fichier.

Une seule fenêtre pour les deux usages — la liste, la recherche et le
rendu sont communs, seule la source change (une ref, un chemin, ou les
deux).

La lecture part en **arrière-plan** dès cette première version. Mesuré :
104 ms pour 70 commits sur ce dépôt, et le coût est linéaire en commits
PARCOURUS, pas trouvés — un fichier peu touché paie le parcours complet.
Sur un dépôt de plusieurs milliers de commits cela se compte en secondes,
et ce serait le gel que l'utilisateur a déjà signalé trois fois (double
clic, bouton commit, puis commit + push).
"""

from __future__ import annotations

import threading

import pygit2
import pytest

from tortoisepy.ui.log_window import LogWindow


@pytest.fixture
def depot(tmp_path):
    """Deux fichiers qui évoluent indépendamment, et un merge.

    Le merge est là parce qu'il est le piège du filtrage par chemin : il
    ne doit compter pour un fichier que s'il en change le contenu par
    rapport à TOUS ses parents.
    """
    repo = pygit2.init_repository(str(tmp_path / "d"), initial_head="master")
    sig = pygit2.Signature("Test", "t@example.com", 0, 0)

    def commit(message, fichiers, parents, ref="refs/heads/master"):
        builder = repo.TreeBuilder()
        for nom, contenu in sorted(fichiers.items()):
            builder.insert(
                nom, repo.create_blob(contenu.encode()),
                pygit2.GIT_FILEMODE_BLOB,
            )
        return str(repo.create_commit(
            ref, sig, sig, message, builder.write(),
            [pygit2.Oid(hex=p) for p in parents],
        ))

    un = commit("ajoute a", {"a.txt": "v1"}, [])
    deux = commit("ajoute b", {"a.txt": "v1", "b.txt": "v1"}, [un])
    # Un message capitalisé : la recherche doit abaisser le MESSAGE autant
    # que le motif (mutation M4).
    commit("MAJUSCULE dans le message", {"a.txt": "v2", "b.txt": "v1"}, [deux])
    return repo



def _resumes(fenetre) -> list[str]:
    arbre = fenetre._commits
    return [
        arbre.topLevelItem(i).text(1) for i in range(arbre.topLevelItemCount())
    ]


# --- journal d'une branche ----------------------------------------------


def test_the_window_lists_the_commits_of_a_ref(qtbot, depot, attendre_la_fenetre):
    """Le cas de `show_log`, qui ne faisait rien jusqu'ici."""
    fenetre = LogWindow(depot, ref="master")
    qtbot.addWidget(fenetre)
    attendre_la_fenetre(qtbot, fenetre)

    assert _resumes(fenetre) == [
        "MAJUSCULE dans le message", "ajoute b", "ajoute a",
    ]


def test_the_title_says_what_is_shown(qtbot, depot, attendre_la_fenetre):
    """Une fenêtre de journal sans sa source ne se relit pas."""
    fenetre = LogWindow(depot, ref="master")
    qtbot.addWidget(fenetre)
    attendre_la_fenetre(qtbot, fenetre)

    assert "master" in fenetre.windowTitle()


# --- journal d'un fichier -----------------------------------------------


def test_the_window_filters_by_path(qtbot, depot, attendre_la_fenetre):
    """Le vrai manque : « quand ce fichier a-t-il changé ? »."""
    fenetre = LogWindow(depot, ref="master", path="b.txt")
    qtbot.addWidget(fenetre)
    attendre_la_fenetre(qtbot, fenetre)

    assert _resumes(fenetre) == ["ajoute b"], (
        "seuls les commits touchant b.txt doivent apparaître"
    )


def test_the_title_names_the_file(qtbot, depot, attendre_la_fenetre):
    """Sinon on ne sait plus de quel fichier on lit l'histoire."""
    fenetre = LogWindow(depot, ref="master", path="b.txt")
    qtbot.addWidget(fenetre)
    attendre_la_fenetre(qtbot, fenetre)

    assert "b.txt" in fenetre.windowTitle()


# --- arrière-plan et loader ---------------------------------------------


def test_the_read_does_not_run_on_the_main_thread(qtbot, depot, attendre_la_fenetre):
    """L'assertion qui compte : la fenêtre ne doit pas geler.

    Vérifier `progress.isVisible()` depuis l'intérieur du travail ne
    prouverait rien — c'est l'erreur qui avait laissé passer le gel du
    commit : la barre était « montrée » sans que Qt puisse la peindre.
    On observe donc le FIL d'exécution.
    """
    from tortoisepy.ui import log_window as module

    principal = threading.get_ident()
    fils = []
    vrai = module.read_log

    def observe(*a, **k):
        fils.append(threading.get_ident())
        return vrai(*a, **k)

    module.read_log = observe
    try:
        fenetre = LogWindow(depot, ref="master")
        qtbot.addWidget(fenetre)
        qtbot.waitUntil(lambda: bool(fils), timeout=5000)
        assert fils[0] != principal, "la lecture gèle la fenêtre"
        attendre_la_fenetre(qtbot, fenetre)
    finally:
        module.read_log = vrai


def test_the_loader_shows_then_disappears(qtbot, depot, attendre_la_fenetre):
    """Un retour visuel pendant la lecture, et pas après.

    `show()` est nécessaire : Qt ne considère un enfant comme visible que
    si sa fenêtre l'est, donc l'assertion porterait sur la fenêtre, pas
    sur la barre.
    """
    fenetre = LogWindow(depot, ref="master")
    qtbot.addWidget(fenetre)
    fenetre.show()

    assert fenetre.progress.isVisible(), "aucun indicateur de chargement"
    attendre_la_fenetre(qtbot, fenetre)
    assert not fenetre.progress.isVisible(), "le loader reste après la lecture"


def test_the_window_opens_without_waiting(qtbot, depot, attendre_la_fenetre):
    """Le constructeur ne doit pas attendre la lecture.

    `blame_window` fait l'inverse — il lit dans `__init__` — et la fenêtre
    s'ouvre grise et vide le temps du calcul.
    """
    lent = []
    from tortoisepy.ui import log_window as module
    vrai = module.read_log

    def observe(*a, **k):
        import time
        time.sleep(0.4)
        r = vrai(*a, **k)
        lent.append(1)
        return r

    module.read_log = observe
    try:
        fenetre = LogWindow(depot, ref="master")
        qtbot.addWidget(fenetre)
        assert not lent, "le constructeur a attendu la fin de la lecture"
        attendre_la_fenetre(qtbot, fenetre)
    finally:
        module.read_log = vrai


# --- recherche ----------------------------------------------------------


def test_searching_filters_the_list(qtbot, depot, attendre_la_fenetre):
    """Ce que le panneau latéral n'a pas : chercher dans les messages."""
    fenetre = LogWindow(depot, ref="master")
    qtbot.addWidget(fenetre)
    attendre_la_fenetre(qtbot, fenetre)

    fenetre.search_field.setText("ajoute")
    fenetre.apply_search()

    assert _resumes(fenetre) == ["ajoute b", "ajoute a"]


def test_an_empty_search_shows_everything_again(qtbot, depot, attendre_la_fenetre):
    """Vider le champ doit rendre la liste complète, pas la laisser filtrée."""
    fenetre = LogWindow(depot, ref="master")
    qtbot.addWidget(fenetre)
    attendre_la_fenetre(qtbot, fenetre)

    fenetre.search_field.setText("ajoute")
    fenetre.apply_search()
    fenetre.search_field.setText("")
    fenetre.apply_search()

    assert len(_resumes(fenetre)) == 3


def test_the_search_ignores_case(qtbot, depot, attendre_la_fenetre):
    """Personne ne respecte la casse en cherchant.

    Les DEUX côtés sont abaissés, et il faut les deux assertions pour le
    prouver : « AJOUTE » contre des messages minuscules ne teste que le
    motif (trouvé par mutation — retirer `.lower()` sur le message
    passait inaperçu). Le dépôt contient donc un message capitalisé.
    """
    fenetre = LogWindow(depot, ref="master")
    qtbot.addWidget(fenetre)
    attendre_la_fenetre(qtbot, fenetre)

    # Motif en majuscules, message en minuscules.
    fenetre.search_field.setText("AJOUTE")
    fenetre.apply_search()
    assert len(_resumes(fenetre)) == 2, "le motif n'est pas abaissé"

    # Motif en minuscules, message capitalisé.
    fenetre.search_field.setText("majuscule")
    fenetre.apply_search()
    assert _resumes(fenetre) == ["MAJUSCULE dans le message"], (
        "le message n'est pas abaissé"
    )


def test_the_search_does_not_reread_the_repository(
    qtbot, depot, attendre_la_fenetre
):
    """Filtrer est un geste d'affichage : relire serait un gel par frappe.

    Le piège : une recherche qui relance `read_log` rendrait la frappe
    insupportable sur un gros dépôt, là où la liste est déjà en mémoire.
    """
    from tortoisepy.ui import log_window as module

    fenetre = LogWindow(depot, ref="master")
    qtbot.addWidget(fenetre)
    attendre_la_fenetre(qtbot, fenetre)

    lectures = []
    vrai = module.read_log
    module.read_log = lambda *a, **k: (lectures.append(1), vrai(*a, **k))[1]
    try:
        fenetre.search_field.setText("ajoute")
        fenetre.apply_search()
        assert lectures == [], "la recherche a relu le dépôt"
    finally:
        module.read_log = vrai


# --- pagination ---------------------------------------------------------


def test_load_more_appends_the_next_page(qtbot, depot, attendre_la_fenetre):
    """« Load more » : ni répétition, ni saut."""
    fenetre = LogWindow(depot, ref="master", page_size=2)
    qtbot.addWidget(fenetre)
    attendre_la_fenetre(qtbot, fenetre)

    assert _resumes(fenetre) == ["MAJUSCULE dans le message", "ajoute b"]

    fenetre.load_more()
    attendre_la_fenetre(qtbot, fenetre)

    assert _resumes(fenetre) == [
        "MAJUSCULE dans le message", "ajoute b", "ajoute a",
    ]


def test_load_more_is_hidden_once_everything_is_read(
    qtbot, depot, attendre_la_fenetre
):
    """Un bouton qui ne fait plus rien apprend à ignorer l'interface."""
    fenetre = LogWindow(depot, ref="master", page_size=50)
    qtbot.addWidget(fenetre)
    attendre_la_fenetre(qtbot, fenetre)

    assert not fenetre.more_button.isVisible(), (
        "tout l'historique tient dans la première page"
    )


def test_load_more_stays_available_while_pages_remain(
    qtbot, depot, attendre_la_fenetre
):
    """Son absence ferait croire l'historique terminé."""
    fenetre = LogWindow(depot, ref="master", page_size=2)
    qtbot.addWidget(fenetre)
    fenetre.show()
    attendre_la_fenetre(qtbot, fenetre)

    assert fenetre.more_button.isVisible()


# --- navigation ---------------------------------------------------------


def test_activating_a_commit_emits_its_oid(qtbot, depot, attendre_la_fenetre):
    """Double-clic : ouvrir le détail du commit, fenêtre déjà existante."""
    fenetre = LogWindow(depot, ref="master")
    qtbot.addWidget(fenetre)
    attendre_la_fenetre(qtbot, fenetre)

    vus = []
    fenetre.commit_activated.connect(vus.append)
    premier = fenetre._commits.topLevelItem(0)
    fenetre._commits.itemActivated.emit(premier, 0)

    assert vus == [str(depot.head.target)]


# --- cas limites --------------------------------------------------------


def test_an_unknown_ref_says_so(qtbot, depot, attendre_la_fenetre):
    """Une branche peut disparaître entre le menu et le clic."""
    fenetre = LogWindow(depot, ref="disparue")
    qtbot.addWidget(fenetre)
    fenetre.show()   # Qt : un enfant n'est visible que si sa fenêtre l'est
    attendre_la_fenetre(qtbot, fenetre)

    assert _resumes(fenetre) == []
    assert fenetre._message.isVisible(), (
        "une liste vide et muette est indiscernable d'un défaut"
    )


def test_a_path_never_versioned_says_so(qtbot, depot, attendre_la_fenetre):
    """Même raison : le vide doit se dire."""
    fenetre = LogWindow(depot, ref="master", path="jamais-vu.txt")
    qtbot.addWidget(fenetre)
    fenetre.show()   # Qt : un enfant n'est visible que si sa fenêtre l'est
    attendre_la_fenetre(qtbot, fenetre)

    assert fenetre._message.isVisible()


def test_reading_a_log_writes_nothing(qtbot, depot, attendre_la_fenetre):
    """§7.0 : l'application ne modifie le dépôt que sur action explicite."""
    refs_avant = {r: str(depot.references[r].target) for r in depot.references}
    head_avant = str(depot.head.target)

    fenetre = LogWindow(depot, ref="master")
    qtbot.addWidget(fenetre)
    attendre_la_fenetre(qtbot, fenetre)
    fenetre.load_more()
    attendre_la_fenetre(qtbot, fenetre)

    assert {
        r: str(depot.references[r].target) for r in depot.references
    } == refs_avant
    assert str(depot.head.target) == head_avant


def test_closing_during_the_read_does_not_crash(qtbot, depot):
    """Fermer pendant la lecture détruirait le QThread en pleine exécution.

    « QThread: Destroyed while thread is still running » — le défaut déjà
    corrigé sur la fenêtre principale puis sur celle de commit.
    """
    fenetre = LogWindow(depot, ref="master")
    qtbot.addWidget(fenetre)
    fenetre.close()   # ne doit pas lever


# --- largeur des colonnes -----------------------------------------------


def test_the_message_column_takes_the_remaining_width(
    qtbot, depot, attendre_la_fenetre
):
    """Signalé par l'utilisateur : « les colonnes ont l'air très courtes
    et empêchent de voir l'ensemble du message ».

    Le message est la colonne qu'on vient lire ; les trois autres
    (abrégé, auteur, date) ont une largeur prévisible. C'est donc le
    message qui doit absorber la place restante — convention déjà en
    place dans le panneau latéral, que cette fenêtre avait oubliée.
    """
    from PySide6.QtWidgets import QHeaderView

    fenetre = LogWindow(depot, ref="master")
    qtbot.addWidget(fenetre)
    fenetre.show()
    attendre_la_fenetre(qtbot, fenetre)

    entete = fenetre._commits.header()
    assert entete.sectionResizeMode(1) == QHeaderView.ResizeMode.Stretch, (
        "la colonne Message doit prendre la largeur restante"
    )


def test_the_narrow_columns_fit_their_content(
    qtbot, depot, attendre_la_fenetre
):
    """Les trois autres s'ajustent, sans voler de place au message.

    Une largeur fixe serait soit trop courte pour un nom d'auteur long,
    soit du vide pris au message.
    """
    from PySide6.QtWidgets import QHeaderView

    fenetre = LogWindow(depot, ref="master")
    qtbot.addWidget(fenetre)
    fenetre.show()
    attendre_la_fenetre(qtbot, fenetre)

    entete = fenetre._commits.header()
    for colonne in (0, 2, 3):
        assert entete.sectionResizeMode(colonne) == (
            QHeaderView.ResizeMode.ResizeToContents
        ), f"la colonne {colonne} doit s'ajuster à son contenu"


def test_the_message_column_is_the_widest(qtbot, depot, attendre_la_fenetre):
    """L'assertion qui compte : la largeur OBTENUE, pas le mode réglé.

    Les deux tests précédents vérifient la configuration ; ils passaient
    alors que le message restait tronqué. Mesuré sur ce dépôt, la colonne
    Date occupait 372 px pour afficher « 04/10/25 » : en dernière
    position, Qt lui fait absorber la place restante malgré
    `ResizeToContents`, et le message n'en gardait que 373 px sur 900.
    """
    fenetre = LogWindow(depot, ref="master")
    qtbot.addWidget(fenetre)
    fenetre.show()
    fenetre.resize(900, 600)
    attendre_la_fenetre(qtbot, fenetre)
    qtbot.wait(50)   # laisse l'en-tête se disposer

    entete = fenetre._commits.header()
    largeurs = {i: entete.sectionSize(i) for i in range(4)}

    assert largeurs[1] > sum(
        largeurs[i] for i in (0, 2, 3)
    ), f"le message doit dominer, or les largeurs sont {largeurs}"


def test_the_date_column_stays_narrow(qtbot, depot, attendre_la_fenetre):
    """Une date courte ne doit pas occuper le quart de la fenêtre.

    C'est le défaut exact signalé par l'utilisateur, vu depuis la cause :
    la dernière colonne absorbait l'espace restant.
    """
    fenetre = LogWindow(depot, ref="master")
    qtbot.addWidget(fenetre)
    fenetre.show()
    fenetre.resize(900, 600)
    attendre_la_fenetre(qtbot, fenetre)
    qtbot.wait(50)

    date = fenetre._commits.header().sectionSize(3)
    assert date < 150, f"la colonne Date occupe {date} px pour « 04/10/25 »"


def test_the_window_is_wide_enough_to_read_a_message(
    qtbot, depot, attendre_la_fenetre
):
    """Une fenêtre étroite rendrait le réglage des colonnes inutile."""
    fenetre = LogWindow(depot, ref="master")
    qtbot.addWidget(fenetre)
    attendre_la_fenetre(qtbot, fenetre)

    assert fenetre.width() >= 900, (
        f"fenêtre trop étroite à l'ouverture : {fenetre.width()} px"
    )
