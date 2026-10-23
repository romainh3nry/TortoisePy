"""L'aspect ne doit pas changer en extrayant `RepositoryPanel`.

L'étape 1 du chantier des onglets déplace 28 attributs hors de
`MainWindow` sans rien ajouter à l'écran. La consigne du projet est
explicite — « ne jamais dégrader l'aspect actuel » — et un
déplacement de widgets est exactement ce qui le dégrade sans qu'on le
remarque : une marge qui change de propriétaire, un espacement qui
revient à sa valeur par défaut, une poignée que `QSplitter` adopte
comme colonne.

Ces tests épinglent la GÉOMÉTRIE RÉELLE, mesurée après affichage, et
non les valeurs déclarées : une marge posée sur le mauvais widget se
lit juste dans le code et se voit à l'écran.

Ils sont écrits AVANT l'extraction et doivent passer AVANT comme
APRÈS. Un échec après extraction nomme ce qui a bougé.
"""

from __future__ import annotations

import os
import subprocess

import pygit2
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSplitter

from tortoisepy.ui.main_window import MainWindow


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
    """Deux branches : de quoi peupler le graphe et la liste."""
    chemin = tmp_path / "aspect"
    chemin.mkdir()
    run_git(chemin, "init", "-q", "-b", "main")
    for i in range(3):
        (chemin / f"f{i}.txt").write_text(f"contenu {i}\n")
        run_git(chemin, "add", ".")
        run_git(chemin, "commit", "-q", "-m", f"commit {i}")
    run_git(chemin, "branch", "autre")
    return pygit2.Repository(str(chemin))


@pytest.fixture
def fenetre(qtbot, depot):
    f = MainWindow(depot)
    qtbot.addWidget(f)
    f.resize(1200, 800)
    f.show()
    qtbot.waitExposed(f)
    return f


# --- la composition du centre -------------------------------------------


def test_the_central_widget_holds_the_banner_then_the_splitter(fenetre):
    """L'ordre vertical : bandeau d'opération, puis le splitter.

    Inverser les deux mettrait le bandeau sous le graphe, où il
    passerait inaperçu — il signale un rebase ou un merge en cours.
    """
    central = fenetre.centralWidget()
    assert central is not None

    disposition = central.layout()
    assert disposition is not None, "le centre n'a pas de mise en page"
    assert disposition.count() == 2, (
        f"{disposition.count()} widget(s) au centre, il en faut deux"
    )

    premier = disposition.itemAt(0).widget()
    second = disposition.itemAt(1).widget()

    assert premier is fenetre._banner
    assert second is fenetre.splitter


def test_the_central_margins_and_spacing_are_preserved(fenetre):
    """Marges à zéro, espacement à 4.

    Des marges par défaut ajouteraient un liseré autour du graphe. La
    valeur 4 sépare le bandeau du contenu sans le détacher.
    """
    disposition = fenetre.centralWidget().layout()

    assert disposition.contentsMargins().left() == 0
    assert disposition.contentsMargins().top() == 0
    assert disposition.contentsMargins().right() == 0
    assert disposition.contentsMargins().bottom() == 0
    assert disposition.spacing() == 4


def test_the_splitter_is_horizontal_with_graph_then_panel(fenetre):
    """Graphe à gauche, liste à droite — dans cet ordre.

    Les intervertir échangerait les deux colonnes de l'application.
    """
    assert fenetre.splitter.orientation() == Qt.Orientation.Horizontal
    assert fenetre.splitter.count() == 2
    assert fenetre.splitter.widget(0) is fenetre.view
    assert fenetre.splitter.widget(1) is fenetre.commit_panel


def test_the_graph_gets_the_larger_share(qtbot, fenetre):
    """Le graphe occupe plus de place que la liste.

    C'est la proportion du contrat visuel — « le panneau latéral
    occupe 40 %, le graphe 60 % ». Mesuré à l'ouverture : 776 / 420,
    soit 65 % pour le graphe.

    Ce test ne vérifie PAS `setStretchFactor(0, 3)` / `(1, 2)`, et
    c'est délibéré. Mesuré : remplacer ces facteurs par 1/4, 4/1 ou
    1/1 donne un rendu **identique au pixel**, à l'ouverture comme
    après avoir doublé la largeur. `restore_settings` et `showEvent`
    appellent `setSizes`, qui impose les tailles et neutralise les
    facteurs. Écrire une assertion dessus donnerait un test qu'aucune
    mutation ne peut faire échouer — j'en ai écrit deux avant de le
    mesurer.

    Ce qui est vrai et observable, c'est la proportion obtenue. C'est
    elle que l'extraction ne doit pas changer.
    """
    graphe, panneau = fenetre.splitter.sizes()
    total = graphe + panneau
    assert total > 0

    part = graphe / total
    assert 0.55 <= part <= 0.75, (
        f"le graphe occupe {part:.0%} de la largeur, attendu ~65 % "
        f"(graphe {graphe}, liste {panneau})"
    )
    assert graphe > panneau, "la liste est plus large que le graphe"


# --- la poignée, le piège le plus coûteux -------------------------------


def test_the_handle_is_not_a_splitter_column(fenetre):
    """LE piège de l'extraction.

    La poignée est parentée à la FENÊTRE, pas au splitter, et le code
    dit pourquoi : `QSplitter` adopte tout enfant comme widget géré, et
    la poignée y redevenait une colonne de 18 px — la « bordure trop
    épaisse » signalée par l'utilisateur.

    En déplaçant le splitter dans un panneau, reparenter la poignée au
    passage est l'erreur naturelle. Ce test l'interdit.
    """
    colonnes = [
        fenetre.splitter.widget(i) for i in range(fenetre.splitter.count())
    ]
    assert fenetre.panel_handle not in colonnes, (
        "la poignée est devenue une colonne : la bordure s'épaissit"
    )


def test_the_handle_keeps_its_size_and_stays_centred(fenetre):
    """16 × 48 px, centrée verticalement.

    Valeurs du contrat visuel, demandées par l'utilisateur : « une
    sorte de flèche au niveau de la liste, pas en haut ».
    """
    assert fenetre.panel_handle.width() == 16
    assert fenetre.panel_handle.height() == 48

    centre_poignee = (
        fenetre.panel_handle.y() + fenetre.panel_handle.height() / 2
    )
    centre_splitter = (
        fenetre.splitter.mapTo(fenetre, fenetre.splitter.rect().center()).y()
    )
    assert abs(centre_poignee - centre_splitter) <= 30, (
        f"poignée centrée à {centre_poignee:.0f}, "
        f"splitter à {centre_splitter:.0f}"
    )


def test_the_handle_is_painted_not_just_styled(fenetre):
    """Compter les pixels, pas la feuille de style.

    Un style déclaré mais non appliqué — ce qui arrive quand le widget
    change de parent — laisserait passer un aplat invisible.
    """
    image = fenetre.panel_handle.grab().toImage()
    teintes = {
        image.pixelColor(x, y).name()
        for y in range(0, image.height(), 3)
        for x in range(0, image.width(), 2)
    }
    assert len(teintes) >= 2, (
        f"la poignée ne peint qu'une teinte ({teintes}) : pas de contour"
    )


# --- ce que la fenêtre garde --------------------------------------------


def test_the_window_keeps_one_splitter_for_the_repository(fenetre):
    """Un seul splitter horizontal au niveau du dépôt.

    L'extraction ne doit pas en ajouter un deuxième « pour la
    structure » : les splitters imbriqués changent la façon dont la
    place se répartit.
    """
    horizontaux = [
        s for s in fenetre.findChildren(QSplitter)
        if s.orientation() == Qt.Orientation.Horizontal
    ]
    assert len(horizontaux) == 1, (
        f"{len(horizontaux)} splitters horizontaux au lieu d'un"
    )


def test_the_toolbar_and_status_bar_stay_on_the_window(fenetre):
    """La barre d'outils et la barre d'état appartiennent au CADRE.

    Elles ne doivent pas partir dans le panneau : l'étape 3 les
    rebranchera sur l'onglet actif, et une barre par onglet est
    justement ce que l'utilisateur n'a pas voulu.
    """
    assert fenetre.toolbar.parent() is fenetre
    assert fenetre.statusBar().parent() is fenetre
    # Et elles sont peuplées.
    assert fenetre.toolbar.actions(), "barre d'outils vide"
    assert fenetre.progress is not None
    assert fenetre.branch_label is not None


def test_the_banner_starts_hidden(fenetre):
    """Pas d'opération en cours : le bandeau ne prend aucune place.

    Visible par défaut, il ajouterait une bande vide en haut du
    graphe.
    """
    assert fenetre._banner.isHidden()


def test_the_graph_and_panel_are_both_visible_by_default(fenetre):
    """L'état par défaut : les deux colonnes affichées.

    Le panneau révèle ce que la compression du graphe masque ; il
    reste affiché, et le masquage est un geste explicite.
    """
    assert fenetre.view.isVisible()
    assert fenetre.commit_panel.isVisible()
    assert fenetre.commit_panel.width() > 0
