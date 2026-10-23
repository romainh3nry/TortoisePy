"""`RepositoryPanel` : l'unité qui deviendra un onglet.

Première moitié de l'étape 1 du chantier des onglets. La classe
assemble le bandeau d'opération, le graphe et la liste ; la logique
reste dans `MainWindow` pour l'instant.

Ces tests portent sur le panneau SEUL, sans `MainWindow` : c'est ce
qui permettra d'en construire plusieurs côte à côte à l'étape 2. Un
module testé uniquement à travers sa fenêtre ne prouve pas qu'il
tient debout séparément.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QSplitter, QWidget

from tortoisepy.ui.repository_panel import (
    ESPACEMENT,
    ETIREMENT_GRAPHE,
    ETIREMENT_LISTE,
    RepositoryPanel,
)


@pytest.fixture
def pieces():
    """Trois widgets quelconques : le panneau n'en connaît pas le type.

    Ils ne sont PAS confiés à `qtbot` : le panneau les reparente, et
    Qt détruit alors l'objet C++ avec son nouveau parent. `qtbot`
    tenterait ensuite de nettoyer un objet déjà détruit —
    « libshiboken: Internal C++ object already deleted », rencontré en
    écrivant ces tests. Seul le propriétaire final est enregistré.
    """
    return QWidget(), QWidget(), QLabel("opération en cours")


# --- le splitter ---------------------------------------------------------


def test_the_splitter_puts_the_graph_first(qtbot, pieces):
    """Graphe à gauche, liste à droite.

    Les intervertir échangerait les deux colonnes de l'application.
    """
    graphe, liste, _ = pieces
    splitter = RepositoryPanel.build_splitter(graphe, liste)
    qtbot.addWidget(splitter)   # personne ne le reparente ici

    assert splitter.orientation() == Qt.Orientation.Horizontal
    assert splitter.count() == 2
    assert splitter.widget(0) is graphe
    assert splitter.widget(1) is liste


def test_the_graph_is_given_the_larger_stretch(qtbot, pieces):
    """Le graphe reçoit plus que la liste — contrat visuel 60/40.

    `setStretchFactor` n'a pas de lecteur public ; on vérifie les
    constantes, qui sont la seule trace lisible de l'intention, et le
    rendu obtenu est vérifié ailleurs (`test_layout_unchanged`).
    """
    assert ETIREMENT_GRAPHE > ETIREMENT_LISTE


def test_the_splitter_takes_the_parent_it_is_given(qtbot, pieces):
    """La parenté est explicite.

    `MainWindow` passe `self` : le splitter doit appartenir à la
    fenêtre au moment où `_repartir_le_splitter` lui donne ses
    tailles, avant que le panneau existe.
    """
    graphe, liste, _ = pieces
    parent = QWidget()
    qtbot.addWidget(parent)

    splitter = RepositoryPanel.build_splitter(graphe, liste, parent)

    assert splitter.parent() is parent


# --- l'assemblage --------------------------------------------------------


def test_the_banner_sits_above_the_splitter(qtbot, pieces):
    """L'ordre vertical : bandeau, puis contenu.

    Inversé, le bandeau passerait sous le graphe, où il serait
    invisible — or il signale un rebase ou un merge en cours.
    """
    graphe, liste, bandeau = pieces
    splitter = RepositoryPanel.build_splitter(graphe, liste)

    panneau = RepositoryPanel(splitter, bandeau)
    qtbot.addWidget(panneau)

    disposition = panneau.layout()
    assert disposition.count() == 2
    assert disposition.itemAt(0).widget() is bandeau
    assert disposition.itemAt(1).widget() is splitter


def test_the_margins_are_zero(qtbot, pieces):
    """Aucune marge : le graphe occupe toute la surface.

    La moindre marge ajouterait un liseré visible autour du graphe.
    """
    graphe, liste, bandeau = pieces
    panneau = RepositoryPanel(
        RepositoryPanel.build_splitter(graphe, liste), bandeau
    )
    qtbot.addWidget(panneau)

    marges = panneau.layout().contentsMargins()
    assert (marges.left(), marges.top(), marges.right(), marges.bottom()) == (
        0, 0, 0, 0
    )


def test_the_spacing_separates_the_banner_from_the_content(qtbot, pieces):
    """Un espacement, mais pas celui de Qt par défaut.

    Zéro collerait le bandeau au graphe ; la valeur par défaut l'en
    détacherait trop.
    """
    graphe, liste, bandeau = pieces
    panneau = RepositoryPanel(
        RepositoryPanel.build_splitter(graphe, liste), bandeau
    )
    qtbot.addWidget(panneau)

    assert panneau.layout().spacing() == ESPACEMENT
    assert ESPACEMENT == 4


def test_the_panel_exposes_what_it_assembles(qtbot, pieces):
    """Le splitter et le bandeau restent accessibles.

    `MainWindow` les manipule encore — tailles du splitter, bandeau
    montré ou caché selon l'opération en cours.
    """
    graphe, liste, bandeau = pieces
    splitter = RepositoryPanel.build_splitter(graphe, liste)

    panneau = RepositoryPanel(splitter, bandeau)
    qtbot.addWidget(panneau)

    assert panneau.splitter is splitter
    assert panneau.banner is bandeau


# --- le piège de l'extraction --------------------------------------------


def test_the_panel_adopts_nothing_else(qtbot, pieces):
    """Le splitter ne doit gérer QUE deux colonnes.

    LE piège : `QSplitter` adopte tout enfant comme widget géré. La
    poignée de repli de `MainWindow` est pour cette raison parentée à
    la fenêtre et posée par-dessus — sinon elle redevient une colonne
    de 18 px, la « bordure trop épaisse » signalée par l'utilisateur.

    Ce test vérifie que le panneau n'ajoute rien au splitter de son
    côté.
    """
    graphe, liste, bandeau = pieces
    splitter = RepositoryPanel.build_splitter(graphe, liste)

    panneau = RepositoryPanel(splitter, bandeau)
    qtbot.addWidget(panneau)

    assert splitter.count() == 2, (
        f"{splitter.count()} colonnes : le panneau a ajouté un widget"
    )


def test_several_panels_can_live_side_by_side(qtbot):
    """Ce que l'étape 2 exigera : plusieurs panneaux à la fois.

    C'est la raison d'être de l'extraction. Un panneau qui ne
    supporterait pas d'avoir un jumeau ne pourrait pas devenir un
    onglet.
    """
    panneaux = []
    for _ in range(3):
        graphe, liste = QWidget(), QWidget()
        panneau = RepositoryPanel(
            RepositoryPanel.build_splitter(graphe, liste), QLabel("b")
        )
        qtbot.addWidget(panneau)
        panneaux.append(panneau)

    # Chacun garde SES widgets : un attribut de classe au lieu d'un
    # attribut d'instance les ferait tous pointer sur le dernier.
    splitters = {id(p.splitter) for p in panneaux}
    assert len(splitters) == 3, "les panneaux partagent un splitter"

    for panneau in panneaux:
        assert isinstance(panneau.splitter, QSplitter)
        assert panneau.splitter.count() == 2
