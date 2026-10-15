"""Masquer la liste latérale des commits.

Demandé par l'utilisateur : « un bouton qui permet de cacher la liste
latérale des commits ; par défaut elle s'affiche ».

Le graphe est ce qui profite de la place — sur un dépôt large, rendre
les 40 % du panneau au graphe change la lecture. Mais le panneau révèle
ce que la compression masque (§4.2.1) : il reste donc affiché par
défaut, et le masquage est un geste explicite.

Les deux pièges, tous deux vérifiés par un test :

  - `save_settings` mémorise `splitter.sizes()[1]`. Panneau masqué,
    cette taille vaut 0 : la largeur choisie par l'utilisateur serait
    perdue, et il la retrouverait à zéro en rouvrant.
  - masquer un widget ne suffit pas si le splitter lui rend sa place à
    la réapparition suivante.
"""

from __future__ import annotations

import os
import subprocess

import pygit2
import pytest
from PySide6.QtCore import QSettings

from tortoisepy.ui.main_window import MainWindow
from tortoisepy.ui.settings_store import SettingsStore


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
def repo(tmp_path):
    path = tmp_path / "bascule"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "master")
    (path / "f.txt").write_text("base\n")
    run_git(path, "add", "f.txt")
    run_git(path, "commit", "-q", "-m", "base")
    return pygit2.Repository(str(path))


@pytest.fixture
def store(tmp_path):
    """Un fichier `.ini` jetable.

    Sans cette injection, les tests écriraient dans les VRAIES
    préférences de l'utilisateur (`~/Library/Preferences` sur macOS) —
    constaté : une première version de ce fichier y a laissé
    `view/panel_hidden = true`, et le panneau s'ouvrait masqué dans
    l'application réelle.
    """
    return SettingsStore(
        QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    )


@pytest.fixture
def window(qtbot, repo, store):
    w = MainWindow(repo, settings=store)
    qtbot.addWidget(w)
    # Assez large pour que le panneau tienne : il impose un minimum de
    # 420 px, et la fenêtre par défaut du pilote `offscreen` n'en fait
    # que 798 — le splitter repliait alors le panneau à 0 dès
    # l'ouverture, et tout test de largeur comparait 0 à 0.
    w.resize(1600, 900)
    w.show()
    qtbot.waitExposed(w)
    return w


# --- le comportement demandé -------------------------------------------


def test_the_panel_shows_by_default(window):
    """« Par défaut elle s'affiche » — la demande, mot pour mot.

    Le panneau révèle ce que la compression du graphe masque (§4.2.1) :
    un utilisateur qui ouvre l'application pour la première fois doit le
    voir.
    """
    assert window.commit_panel.isVisible()
    assert window.toggle_panel_action.isChecked()


def test_the_button_hides_the_panel(window):
    """Le geste demandé : un clic, le panneau disparaît."""
    window.toggle_panel_action.setChecked(False)

    assert not window.commit_panel.isVisible()


def test_the_button_brings_it_back(window):
    """Et le même bouton le ramène — c'est une bascule, pas un aller."""
    window.toggle_panel_action.setChecked(False)
    window.toggle_panel_action.setChecked(True)

    assert window.commit_panel.isVisible()


def test_the_graph_takes_the_whole_width(qtbot, window):
    """Masquer sert à rendre la place au graphe.

    Le test qui compte : un panneau simplement invisible mais dont le
    splitter garderait la colonne laisserait une bande vide, et le
    geste n'aurait servi à rien.

    On part d'une largeur de panneau posée explicitement. Sous le
    pilote `offscreen`, la fenêtre n'a pas de vraie taille à la
    construction et le splitter s'ouvre à `[tout, 0]` — mesurer sans
    cette mise en place comparerait deux fois le même nombre et
    passerait quoi qu'on implémente (constaté). Avec un affichage
    réel, le graphe passe bien de 1085 à 1512 px (vérifié à la main).
    """
    window._poser_la_largeur_du_panneau(500)
    qtbot.waitUntil(lambda: window._largeur_du_panneau() > 0, timeout=2000)
    avant = window.view.width()

    window.toggle_panel_action.setChecked(False)
    qtbot.waitUntil(lambda: window.view.width() > avant, timeout=2000)

    assert window.view.width() > avant, (
        f"le graphe fait toujours {window.view.width()} px "
        f"(il en faisait {avant})"
    )
    assert window._largeur_du_panneau() == 0, (
        "la colonne du panneau occupe encore de la place"
    )


# --- la largeur choisie ne doit pas se perdre ---------------------------


def test_hiding_does_not_erase_the_remembered_width(window):
    """Le piège principal, vérifié par mutation.

    `save_settings` mémorise `splitter.sizes()[1]`. Panneau masqué,
    cette taille vaut 0 : fermer l'application dans cet état
    enregistrerait une largeur nulle, et le panneau reviendrait écrasé
    à la réouverture — un réglage perdu sans que rien ne le signale.
    """
    window.toggle_panel_action.setChecked(False)
    window.save_settings()

    enregistree = window.settings.value("view/panel_width")
    assert enregistree is None or enregistree > 0, (
        f"largeur mémorisée à {enregistree} : le réglage est perdu"
    )


def test_showing_again_restores_the_previous_width(qtbot, window):
    """Rouvrir le panneau doit le rendre tel qu'il était.

    Un panneau qui reviendrait à une largeur par défaut effacerait le
    redimensionnement de l'utilisateur à chaque bascule.
    """
    window._poser_la_largeur_du_panneau(500)
    # `waitUntil` et non `wait` : le splitter n'applique sa répartition
    # qu'au tour suivant, et lire aussitôt rendrait 0 — la largeur
    # « voulue » serait alors nulle et le test passerait pour rien.
    qtbot.waitUntil(lambda: window._largeur_du_panneau() > 0, timeout=2000)
    voulue = window._largeur_du_panneau()

    window.toggle_panel_action.setChecked(False)
    qtbot.waitUntil(lambda: window._largeur_du_panneau() == 0, timeout=2000)
    window.toggle_panel_action.setChecked(True)
    qtbot.waitUntil(lambda: window._largeur_du_panneau() > 0, timeout=2000)

    retrouvee = window._largeur_du_panneau()
    assert abs(retrouvee - voulue) <= 2, (
        f"le panneau revient à {retrouvee} px au lieu de {voulue}"
    )


# --- l'état survit à la fermeture ---------------------------------------


def test_the_choice_is_remembered(window):
    """Masquer puis rouvrir l'application doit garder le panneau masqué.

    Sinon le geste serait à refaire à chaque lancement — exactement ce
    qui rend un réglage inutile.
    """
    window.toggle_panel_action.setChecked(False)
    window.save_settings()

    assert window.settings.value("view/panel_hidden") is True


def test_a_hidden_panel_comes_back_hidden(qtbot, repo, store, window):
    """Le test de bout en bout : l'état est vraiment relu au démarrage.

    Mémoriser sans relire ne sert à rien, et c'est l'oubli invisible —
    `save_settings` a l'air juste.
    """
    window.toggle_panel_action.setChecked(False)
    window.save_settings()

    seconde = MainWindow(repo, settings=store)
    qtbot.addWidget(seconde)
    seconde.resize(1600, 900)
    seconde.show()
    qtbot.waitExposed(seconde)

    assert not seconde.commit_panel.isVisible()
    assert not seconde.toggle_panel_action.isChecked()


def test_a_shown_panel_comes_back_shown(qtbot, repo, store, window):
    """Le cas symétrique : ne pas masquer par accident.

    Un réglage lu de travers (une chaîne « False » vaut vrai en Python)
    masquerait le panneau de tout le monde. C'est le défaut le plus
    coûteux ici, puisqu'il toucherait des utilisateurs qui n'ont rien
    demandé.
    """
    window.toggle_panel_action.setChecked(False)
    window.toggle_panel_action.setChecked(True)
    window.save_settings()

    seconde = MainWindow(repo, settings=store)
    qtbot.addWidget(seconde)
    seconde.resize(1600, 900)
    seconde.show()
    qtbot.waitExposed(seconde)

    assert seconde.commit_panel.isVisible()


# --- le reste ne doit pas se dégrader -----------------------------------


def test_the_search_field_follows_the_panel(window):
    """Le champ de recherche appartient au panneau.

    Il en épouse la largeur (cf. `main_window`) : masquer le panneau le
    masque donc aussi. On le vérifie pour que ce soit un choix constaté
    et non une surprise — chercher un commit passe par la liste, qui
    n'est plus là.
    """
    window.toggle_panel_action.setChecked(False)

    assert not window.search_field.isVisible()


def test_the_graph_still_works_without_the_panel(window):
    """Masquer le panneau ne doit rien casser du graphe.

    Le piège : une action du panneau appelée alors qu'il est masqué.
    """
    window.toggle_panel_action.setChecked(False)
    window._center_on_head()

    assert window.view.isVisible()


def _ecart_a_la_barre(fenetre) -> int:
    """Pixels entre le centre de la poignée et celui de la séparation.

    Mesuré contre `splitter.handle()`, la géométrie que Qt a VRAIMENT
    posée — et non contre `sizes()`, qui rend la largeur des widgets
    sans la barre (7 px, valeur dépendante du style). Une première
    version de ces tests lisait `sizes()`, donc la même source erronée
    que le code : ils toléraient le décalage signalé deux fois par
    l'utilisateur.
    """
    barre = fenetre.splitter.handle(fenetre._I_PANNEAU)
    origine = fenetre.splitter.mapTo(
        fenetre, fenetre.splitter.rect().topLeft()
    )
    centre_barre = origine.x() + barre.x() + barre.width() // 2
    centre_poignee = fenetre.panel_handle.geometry().center().x()
    return abs(centre_poignee - centre_barre)


# --- la poignée, et non un bouton dans la barre d'outils ----------------


def test_the_handle_sits_beside_the_list(window):
    """Demandé : « une flèche au niveau de la liste, pas en haut ».

    Une entrée dans la barre d'outils se perdait parmi quinze autres
    et ne disait pas ce qu'elle replierait (constaté sur capture). La
    poignée borde la liste : sa position nomme sa cible.

    On mesure la géométrie, pas l'intention — une poignée déclarée
    mais posée ailleurs ne vaudrait rien.
    """
    poignee = window.panel_handle
    liste = window.commit_panel

    assert poignee.parent() is not None
    # Collée au bord gauche de la liste, à quelques pixels près.
    bord = liste.mapTo(window, liste.rect().topLeft()).x()
    droite = poignee.mapTo(window, poignee.rect().topRight()).x()
    assert abs(droite - bord) <= 8, (
        f"la poignée finit à {droite}, la liste commence à {bord}"
    )


def test_the_handle_is_not_in_the_toolbar(window):
    """Le bouton ne doit PAS rester en haut.

    L'utilisateur a explicitement refusé cet emplacement ; l'y laisser
    « au cas où » donnerait deux commandes pour un geste.
    """
    from PySide6.QtWidgets import QToolBar

    for barre in window.findChildren(QToolBar):
        assert window.toggle_panel_action not in barre.actions(), (
            "la bascule est encore dans la barre d'outils"
        )


def test_the_handle_stays_small(window):
    """Demandé : « le bouton prend toute la hauteur, rends-le plus petit ».

    Une bande pleine hauteur se lisait comme une troisième colonne.
    Assez grande pour se viser à la souris, assez courte pour ne pas
    peser dans la fenêtre.
    """
    poignee = window.panel_handle

    assert poignee.width() <= 24, (
        f"la poignée fait {poignee.width()} px de large"
    )
    assert 24 <= poignee.height() <= 96, (
        f"la poignée fait {poignee.height()} px de haut : "
        "ni une poignée courte, ni visable"
    )
    # Le piège : le splitter étire ses widgets. Un bouton posé
    # directement dedans reprendrait toute la hauteur quoi qu'on
    # demande — c'est ce qui a été signalé.
    assert poignee.height() < window.commit_panel.height(), (
        "la poignée fait encore la hauteur de la liste"
    )


def test_the_handle_is_vertically_centred(window):
    """Centrée : c'est là que la main la cherche.

    Collée en haut, elle se confondrait avec la barre d'outils.
    """
    poignee = window.panel_handle
    milieu_poignee = poignee.mapTo(window, poignee.rect().center()).y()
    liste = window.commit_panel
    milieu_liste = liste.mapTo(window, liste.rect().center()).y()

    assert abs(milieu_poignee - milieu_liste) <= 40, (
        f"poignée centrée en {milieu_poignee}, liste en {milieu_liste}"
    )


def test_the_arrow_says_what_the_click_will_do(window):
    """La flèche change de sens selon l'état.

    Une flèche figée laisserait deviner si l'on va replier ou rouvrir.
    """
    ouverte = window.toggle_panel_action.text()
    window.toggle_panel_action.setChecked(False)
    repliee = window.toggle_panel_action.text()

    assert ouverte != repliee, (
        f"la flèche reste « {ouverte} » dans les deux états"
    )
    assert ouverte.strip() and repliee.strip(), "la poignée n'affiche rien"


def test_the_handle_survives_hiding_the_panel(qtbot, window):
    """Le piège qui rendrait l'application inutilisable.

    Si la poignée disparaissait avec le panneau, plus rien ne
    permettrait de le rouvrir — et le réglage étant mémorisé, le
    panneau resterait perdu d'un lancement à l'autre.
    """
    window.toggle_panel_action.setChecked(False)
    qtbot.waitUntil(lambda: not window.commit_panel.isVisible(), timeout=2000)

    assert window.panel_handle.isVisible()
    assert window.panel_handle.width() > 0


def test_the_handle_cannot_be_dragged_shut(window):
    """Replier la poignée au ras ferait disparaître le seul recours.

    `QSplitter` laisse par défaut réduire un widget à zéro en tirant
    la barre : il faut le lui interdire explicitement.
    """
    # La poignée est posée par-dessus le splitter, pas dedans : elle
    # ne peut donc pas être repliée en tirant une barre. On vérifie
    # qu'elle n'est pas devenue un widget du splitter.
    assert window.panel_handle not in [
        window.splitter.widget(i) for i in range(window.splitter.count())
    ], "la poignée est redevenue une colonne : la bordure s'épaissit"


def _teintes(widget) -> int:
    """Nombre de couleurs distinctes réellement peintes."""
    image = widget.grab().toImage()
    return len({
        image.pixelColor(x, y).name()
        for y in range(0, image.height(), 3)
        for x in range(0, image.width(), 2)
    })


def test_the_handle_stays_visible_once_collapsed(qtbot, window):
    """Repliée, la poignée borde le graphe — fond clair.

    Constaté sur capture : sans contour, elle s'y effaçait. C'est le
    défaut le plus coûteux ici, puisqu'il enfermerait l'utilisateur
    dans l'état masqué — lequel est mémorisé d'un lancement à l'autre.

    On compte les PIXELS et non la feuille de style : un style déclaré
    mais non appliqué laisserait le test passer et l'écran vide.
    """
    window.toggle_panel_action.setChecked(False)
    qtbot.waitUntil(lambda: not window.commit_panel.isVisible(), timeout=2000)

    assert _teintes(window.panel_handle) > 3, (
        "la poignée est un aplat : elle disparaît sur le graphe"
    )


def test_the_handle_moves_to_the_edge_when_collapsed(qtbot, window):
    """Repliée, la poignée file au bord droit.

    Mesuré : au moment du basculement, `splitter.sizes()` rend encore
    l'ancienne répartition — la poignée restait plantée au milieu de
    la fenêtre, loin du bord, sans rien à border.
    """
    window.toggle_panel_action.setChecked(False)
    qtbot.waitUntil(lambda: not window.commit_panel.isVisible(), timeout=2000)

    droite = window.panel_handle.geometry().right()
    assert droite >= window.splitter.width() - 30, (
        f"la poignée finit à {droite}, la fenêtre à {window.splitter.width()}"
    )


def test_the_handle_is_aligned_from_the_very_first_paint(qtbot, repo, store):
    """Signalé : « au premier démarrage le bouton est légèrement
    décalé, et une fois qu'on replie/déplie il se cale bien ».

    Le test qui compte : on mesure SANS basculer. Les trois
    déclencheurs posés au départ — barre déplacée, fenêtre
    redimensionnée, panneau basculé — manquaient tous au démarrage,
    où le splitter se remet en page seul une fois la liste remplie
    (mesuré : il passe par `[46, 46]` avant sa vraie répartition).
    """
    fenetre = MainWindow(repo, settings=store)
    qtbot.addWidget(fenetre)
    fenetre.resize(1600, 900)
    fenetre.show()
    qtbot.waitExposed(fenetre)
    qtbot.waitUntil(
        lambda: fenetre._largeur_du_panneau() > 0, timeout=3000
    )

    # 1 px de tolérance, et pas plus : c'est l'arrondi de deux
    # divisions entières (barre de 7 px, bouton de 16). Le défaut
    # signalé valait la moitié de la barre, soit 3 px — cette marge ne
    # le laisserait pas passer.
    assert _ecart_a_la_barre(fenetre) <= 1, (
        f"poignée décalée de {_ecart_a_la_barre(fenetre)} px au premier "
        "affichage"
    )


def test_the_handle_follows_a_later_relayout(qtbot, window):
    """Le splitter peut se remettre en page à tout moment.

    Un `setSizes` fait par du code appelé plus tard — restauration
    d'un réglage, chargement d'une liste — ne passe par aucun des
    signaux surveillés au départ. La poignée doit suivre quand même.
    """
    window._poser_la_largeur_du_panneau(600)
    qtbot.waitUntil(
        lambda: window._largeur_du_panneau() == 600, timeout=2000
    )

    assert _ecart_a_la_barre(window) <= 1, (
        f"poignée décalée de {_ecart_a_la_barre(window)} px : elle n'a "
        "pas suivi la remise en page"
    )


def test_the_placement_follows_any_handle_width(qtbot, window):
    """La largeur de la barre dépend de la plateforme.

    Mesuré : 7 px sous le style macOS, 4 px sous windows et fusion.
    Un placement calculé depuis `sizes()` — qui rend la largeur des
    WIDGETS, barre non comprise — se décale d'une moitié de barre, et
    donc DIFFÉREMMENT selon l'OS. C'est le défaut signalé deux fois
    par l'utilisateur.

    On élargit la barre pour exagérer l'effet : avec 24 px, un calcul
    depuis `sizes()` manque la cible de 12 px, bien au-delà de
    l'arrondi tolérable. Le test tient donc quelle que soit la
    plateforme qui l'exécute.
    """
    window.splitter.setHandleWidth(24)
    qtbot.waitUntil(
        lambda: window.splitter.handle(window._I_PANNEAU).width() == 24,
        timeout=2000,
    )
    window._placer_la_poignee()

    assert _ecart_a_la_barre(window) <= 1, (
        f"barre de 24 px : poignée décalée de "
        f"{_ecart_a_la_barre(window)} px — le placement suppose une "
        "largeur de barre au lieu de la lire"
    )
