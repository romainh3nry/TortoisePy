"""Le contenu d'un dépôt : bandeau d'opération, graphe, liste.

Première moitié de l'étape 1 du chantier des onglets. Cette classe
**assemble** les widgets propres à un dépôt ; la logique reste dans
`MainWindow` pour l'instant.

Pourquoi en deux temps : l'inventaire du constructeur donne 28
attributs côté panneau contre 9 côté cadre, et 1055 lignes de méthodes
ne touchent QUE l'état du dépôt, pour 696 lignes mixtes. Déplacer
1751 lignes d'un coup est le genre de changement où une régression
passe inaperçue. Le socle d'abord, le contenu ensuite.

Ce que l'assemblage doit préserver, et que `test_layout_unchanged.py`
vérifie au pixel :

  - l'ordre vertical bandeau puis splitter ;
  - des marges à zéro et un espacement de 4 ;
  - le graphe à gauche, la liste à droite ;
  - **la poignée de repli n'est PAS un enfant du splitter**.

Ce dernier point est le piège de l'extraction. `QSplitter` adopte tout
enfant comme widget géré, et la poignée y redevenait une colonne de
18 px — la « bordure trop épaisse » signalée par l'utilisateur. Elle
reste donc parentée au conteneur et posée par-dessus, à la main.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSplitter, QVBoxLayout, QWidget

# Espacement entre le bandeau d'opération et le contenu. Zéro les
# collerait ; la valeur par défaut de Qt détacherait le bandeau du
# graphe qu'il concerne.
ESPACEMENT = 4

# Le graphe reçoit plus de place que la liste — contrat visuel, « le
# panneau latéral occupe 40 %, le graphe 60 % ». Ces facteurs ne jouent
# en pratique que sur l'espace excédentaire, et `setSizes` les
# neutralise au premier affichage ; ils restent la valeur de départ
# quand aucune largeur n'a été mémorisée.
ETIREMENT_GRAPHE = 3
ETIREMENT_LISTE = 2


class RepositoryPanel(QWidget):
    """Assemble le bandeau, le graphe et la liste d'un dépôt.

    Ne crée aucun de ces widgets : ils lui sont donnés. C'est
    `MainWindow` qui les construit et les câble, et ce découpage lui
    retire seulement l'assemblage — l'étape suivante déplacera la
    logique.
    """

    def __init__(self, splitter: QSplitter, banner: QWidget,
                 parent=None) -> None:
        super().__init__(parent)

        self.splitter = splitter
        self.banner = banner

        disposition = QVBoxLayout(self)
        # Marges à zéro : la moindre marge ajouterait un liseré autour
        # du graphe, qui occupe toute la surface.
        disposition.setContentsMargins(0, 0, 0, 0)
        disposition.setSpacing(ESPACEMENT)
        disposition.addWidget(banner)
        disposition.addWidget(splitter)

    @staticmethod
    def build_splitter(view: QWidget, commit_panel: QWidget,
                       parent=None) -> QSplitter:
        """Le splitter graphe / liste, avec ses proportions.

        Construit à part parce que l'ordre d'initialisation de
        `MainWindow` l'impose : le splitter doit exister — et recevoir
        ses tailles par `_repartir_le_splitter` — AVANT que le bandeau
        d'opération soit construit. Les réordonner changerait le
        rendu, que l'utilisateur a validé.
        """
        splitter = QSplitter(Qt.Orientation.Horizontal, parent)
        splitter.addWidget(view)
        splitter.addWidget(commit_panel)
        splitter.setStretchFactor(0, ETIREMENT_GRAPHE)
        splitter.setStretchFactor(1, ETIREMENT_LISTE)
        return splitter
