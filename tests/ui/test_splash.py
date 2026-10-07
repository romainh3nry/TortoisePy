"""Un écran d'attente pendant la construction du graphe.

Demandé par l'utilisateur, mesuré sur son dépôt :

    imports      :   143.2 ms
    build_graph  :  1522.6 ms  (935 nœuds)

La fenêtre principale se construit d'un bloc, graphe compris : pendant
une seconde et demie, rien ne s'affiche. L'application paraît ne pas
démarrer.

L'écran ne rend pas l'ouverture plus rapide — il la rend **lisible**.
C'est ce que fait n'importe quel client Git sur un gros dépôt, et c'est
honnête : le travail a bien lieu.

Sur un petit dépôt, l'ouverture coûte 40 ms : l'écran y serait un
clignotement. Il ne s'affiche donc qu'au-delà d'un seuil.
"""

from __future__ import annotations

import subprocess

import pygit2
import pytest

from tortoisepy.ui.splash import StartupSplash, should_show_splash

ENV = {
    "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
    "PATH": "/usr/bin:/bin:/usr/local/bin",
}


def _git(chemin, *args, check=True):
    return subprocess.run(
        ["git", "-C", str(chemin), *args], check=check,
        capture_output=True, env=ENV, text=True,
    )


@pytest.fixture
def petit_depot(tmp_path):
    """Deux refs : l'ouverture y est instantanée."""
    w = tmp_path / "petit"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "a.txt").write_text("a\n")
    _git(w, "add", ".")
    _git(w, "commit", "-qm", "base")
    return pygit2.Repository(str(w))


@pytest.fixture
def gros_depot(tmp_path):
    """Beaucoup de refs : le graphe y coûte cher à construire.

    Mesuré sur le dépôt de l'utilisateur, 935 nœuds demandent 1522 ms —
    le seuil doit se déclencher bien avant ce volume.
    """
    w = tmp_path / "gros"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "a.txt").write_text("a\n")
    _git(w, "add", ".")
    _git(w, "commit", "-qm", "base")

    repo = pygit2.Repository(str(w))
    cible = repo.head.target
    for i in range(80):
        repo.create_branch(f"equipe/sujet-{i}", repo.get(cible))
    return repo


# --- quand l'écran doit paraître ----------------------------------------


def test_a_small_repository_shows_no_splash(petit_depot):
    """40 ms d'ouverture : l'écran ne serait qu'un clignotement.

    Le piège : l'afficher toujours. Sur un petit dépôt il apparaîtrait
    et disparaîtrait dans le même souffle, donnant l'impression d'un
    défaut d'affichage.
    """
    assert not should_show_splash(petit_depot)


def test_a_large_repository_shows_the_splash(gros_depot):
    """Au-delà du seuil, l'attente mérite d'être annoncée."""
    assert should_show_splash(gros_depot)


def test_the_decision_is_cheap(gros_depot):
    """Décider ne doit pas coûter ce qu'on cherche à masquer.

    Compter les refs suffit : construire le graphe pour savoir s'il
    faut un écran d'attente serait absurde.
    """
    import time

    # Le MEILLEUR de plusieurs essais : une mesure unique dépend de la
    # charge de la machine, et ce test rougissait au hasard selon les
    # autres tests du module. Ce qu'on vérifie est que la décision PEUT
    # être rapide, donc qu'elle ne construit pas le graphe.
    mesures = []
    for _ in range(5):
        debut = time.perf_counter()
        should_show_splash(gros_depot)
        mesures.append((time.perf_counter() - debut) * 1000)

    assert min(mesures) < 50, (
        f"la décision coûte {min(mesures):.1f} ms au mieux"
    )


def test_an_unreadable_repository_shows_nothing(tmp_path):
    """Un dépôt illisible ne doit pas faire échouer le démarrage.

    L'écran est un confort : lever ici empêcherait l'application de
    s'ouvrir pour afficher son erreur.
    """
    class Cassé:
        @property
        def references(self):
            raise pygit2.GitError("illisible")

    assert not should_show_splash(Cassé())


# --- l'écran lui-même ----------------------------------------------------


def test_the_splash_names_the_repository(qtbot, tmp_path):
    """Savoir quel dépôt s'ouvre : plusieurs fenêtres cohabitent."""
    ecran = StartupSplash("vti")
    qtbot.addWidget(ecran)

    assert "vti" in ecran.message()


def test_the_splash_says_what_it_is_doing(qtbot):
    """« Chargement » sans objet laisse croire à un blocage."""
    ecran = StartupSplash("vti")
    qtbot.addWidget(ecran)

    assert "graphe" in ecran.message().lower()


def test_the_splash_can_be_closed(qtbot):
    """Il disparaît une fois la fenêtre prête."""
    ecran = StartupSplash("vti")
    qtbot.addWidget(ecran)
    ecran.show()

    ecran.finish()
    assert not ecran.isVisible()


def test_finishing_twice_is_harmless(qtbot):
    """Le chemin d'erreur peut le fermer après le chemin normal."""
    ecran = StartupSplash("vti")
    qtbot.addWidget(ecran)
    ecran.show()

    ecran.finish()
    ecran.finish()      # ne doit pas lever


# --- position et apparence ----------------------------------------------


def test_the_splash_is_centred_on_the_screen(qtbot):
    """Signalé par l'utilisateur : il s'affichait en haut à gauche.

    Qt place une fenêtre sans bordure à l'origine par défaut. Un écran
    d'attente décentré paraît égaré — c'est le premier contact avec
    l'application.
    """
    from PySide6.QtGui import QGuiApplication

    ecran = StartupSplash("vti")
    qtbot.addWidget(ecran)
    ecran.show()

    disponible = QGuiApplication.primaryScreen().availableGeometry()
    centre_attendu = disponible.center()
    centre_reel = ecran.frameGeometry().center()

    # Tolérance d'un pixel : les géométries entières ne se divisent pas
    # toujours exactement en deux.
    assert abs(centre_reel.x() - centre_attendu.x()) <= 1
    assert abs(centre_reel.y() - centre_attendu.y()) <= 1


def test_the_splash_has_a_usable_size(qtbot):
    """Trop étroit, le texte se coupe ; trop large, il flotte."""
    ecran = StartupSplash("vti")
    qtbot.addWidget(ecran)
    ecran.show()

    assert 320 <= ecran.width() <= 640, f"largeur {ecran.width()} px"
    assert 120 <= ecran.height() <= 320, f"hauteur {ecran.height()} px"


def test_a_long_repository_name_does_not_stretch_the_splash(qtbot):
    """Un nom de dossier très long ne doit pas déformer la fenêtre.

    Le piège : laisser le texte dicter la largeur, et obtenir un écran
    plus large que la fenêtre principale.
    """
    ecran = StartupSplash("un-nom-de-depot-vraiment-tres-tres-long-comme-on-en-voit")
    qtbot.addWidget(ecran)
    ecran.show()

    assert ecran.width() <= 640


def test_the_splash_shows_the_application_name(qtbot):
    """Le premier écran vu doit dire de quelle application il s'agit."""
    ecran = StartupSplash("vti")
    qtbot.addWidget(ecran)

    assert "tortoisePy" in ecran.title_text()


def test_the_splash_carries_a_progress_indicator(qtbot):
    """Un texte figé ne distingue pas « ça travaille » de « ça a planté ».

    Une barre indéterminée dit que quelque chose se passe, même quand on
    ne peut pas dire combien de temps il reste.
    """
    ecran = StartupSplash("vti")
    qtbot.addWidget(ecran)

    assert ecran.progress.isVisibleTo(ecran)
    assert ecran.progress.maximum() == 0, (
        "la durée est inconnue : la barre doit être indéterminée"
    )


# --- la barre doit réellement s'animer ----------------------------------


def test_the_splash_pumps_events_while_waiting(qtbot):
    """Signalé par l'utilisateur : « la barre de chargement ne bouge pas ».

    Qt anime une barre indéterminée depuis sa boucle d'événements. Or le
    fil principal est occupé 1,5 s à construire la fenêtre : la boucle
    ne tourne pas, et rien ne se repeint. Mesuré — zéro tic de minuteur
    pendant un blocage nu, dix avec pompage.

    `pump` rend donc la main à Qt pendant l'attente. Sans elle, l'écran
    reste figé et dit le contraire de ce qu'il affirme : que le travail
    avance.
    """
    import time

    from PySide6.QtCore import QTimer

    ecran = StartupSplash("vti")
    qtbot.addWidget(ecran)
    ecran.show()

    tics = []
    minuteur = QTimer()
    minuteur.setInterval(20)
    minuteur.timeout.connect(lambda: tics.append(1))
    minuteur.start()

    fin = time.perf_counter() + 0.25
    while time.perf_counter() < fin:
        ecran.pump()
        time.sleep(0.005)
    minuteur.stop()

    assert len(tics) >= 3, (
        f"seulement {len(tics)} tics : la boucle Qt n'a pas tourné"
    )


def test_pumping_a_closed_splash_is_harmless(qtbot):
    """L'appelant peut pomper après la fermeture, sur un chemin d'erreur."""
    ecran = StartupSplash("vti")
    qtbot.addWidget(ecran)
    ecran.show()
    ecran.finish()

    ecran.pump()      # ne doit pas lever


# --- le logo à la place du titre ----------------------------------------


def test_the_splash_shows_the_logo(qtbot):
    """Demandé par l'utilisateur : le logo plutôt que le mot « tortoisePy ».

    L'icône existe déjà en 512 px dans les ressources, et sert déjà à la
    fenêtre et au Dock : c'est la même identité, au même endroit.
    """
    ecran = StartupSplash("vti")
    qtbot.addWidget(ecran)

    pixmap = ecran.logo.pixmap()
    assert not pixmap.isNull(), "aucun logo chargé"


def test_the_splash_keeps_its_size(qtbot):
    """« En gardant les mêmes proportions qu'actuel » (demandé).

    Le piège : une image de 1254 px posée telle quelle ferait exploser la
    fenêtre. Le logo s'inscrit dans la place du titre, il ne la dicte
    pas.
    """
    from tortoisepy.ui.splash import HAUTEUR, LARGEUR

    ecran = StartupSplash("vti")
    qtbot.addWidget(ecran)
    ecran.show()

    assert ecran.width() == LARGEUR
    assert ecran.height() == HAUTEUR


def test_the_logo_fits_the_splash(qtbot):
    """Le logo doit tenir dans le cadre, texte et barre compris.

    La borne est tirée de la hauteur réelle plutôt que d'un chiffre
    arbitraire : agrandir le logo ne doit pas obliger à retoucher le
    test, mais comprimer le texte doit le faire rougir.
    """
    from tortoisepy.ui.splash import HAUTEUR, LARGEUR

    ecran = StartupSplash("vti")
    qtbot.addWidget(ecran)
    ecran.show()

    pixmap = ecran.logo.pixmap()
    assert pixmap.width() <= LARGEUR - 40, (
        f"logo trop large : {pixmap.width()} px"
    )
    # Le message et la barre ont besoin de leur place sous le logo.
    assert pixmap.height() <= HAUTEUR - 80, (
        f"logo trop haut : {pixmap.height()} px pour {HAUTEUR} px de cadre"
    )


def test_the_message_is_not_squeezed(qtbot):
    """Agrandir le logo ne doit pas tronquer le texte sous lui.

    Le piège : gagner en logo ce qu'on perd en lisibilité.
    """
    ecran = StartupSplash("vti")
    qtbot.addWidget(ecran)
    ecran.show()

    assert ecran._label.height() >= ecran._label.sizeHint().height(), (
        "le message est comprimé"
    )


def test_the_message_is_still_there(qtbot):
    """Le logo remplace le titre, pas le reste.

    Savoir QUEL dépôt s'ouvre et ce qui se passe reste nécessaire : une
    image seule ne le dit pas.
    """
    ecran = StartupSplash("vti")
    qtbot.addWidget(ecran)

    assert "vti" in ecran.message()
    assert "graphe" in ecran.message().lower()


def test_a_missing_logo_does_not_break_the_splash(qtbot, monkeypatch):
    """Une ressource absente ne doit pas empêcher le démarrage.

    L'écran est un confort : lever ici bloquerait l'ouverture de
    l'application pour une image manquante.
    """
    from tortoisepy.ui import splash as module

    monkeypatch.setattr(module, "_charger_le_logo", lambda _taille: None)

    ecran = StartupSplash("vti")
    qtbot.addWidget(ecran)
    ecran.show()

    assert ecran.width() == module.LARGEUR
