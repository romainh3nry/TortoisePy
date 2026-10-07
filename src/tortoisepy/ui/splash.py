"""Un écran d'attente pendant la construction du graphe.

Demandé par l'utilisateur, mesuré sur son dépôt :

    imports      :   143.2 ms
    build_graph  :  1522.6 ms  (935 nœuds)

`MainWindow` se construit d'un bloc, graphe compris : pendant une
seconde et demie, rien ne s'affiche et l'application paraît ne pas
démarrer.

Cet écran ne rend pas l'ouverture plus rapide — il la rend **lisible**.
Le travail a bien lieu ; le dire est plus honnête qu'une fenêtre figée.

Sur un petit dépôt, l'ouverture coûte 40 ms : l'écran y serait un
clignotement, et paraîtrait lui-même défectueux. D'où le seuil.
"""

from __future__ import annotations

import pygit2
from PySide6.QtCore import Qt
from pathlib import Path

from PySide6.QtGui import QFont, QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from tortoisepy.ui import theme

REFS_POUR_AFFICHER = 50
"""Au-delà de ce nombre de refs, l'ouverture mérite un écran d'attente.

Le coût de `build_graph` suit le nombre de refs : 2 refs sur ce dépôt
coûtent 17 ms, 935 nœuds en coûtent 1522 chez l'utilisateur. Le seuil
est placé bas — mieux vaut un écran de trop sur un dépôt moyen qu'une
fenêtre figée sur un gros.
"""

LARGEUR = 420
HAUTEUR = 220
"""Taille fixe.

Laisser le texte dicter la largeur donnerait un écran plus large que la
fenêtre principale dès qu'un dépôt porte un nom long (vérifié).
"""


TAILLE_LOGO = 104
"""Côté du logo, en pixels.

Agrandi à la demande de l'utilisateur. La hauteur du cadre suit, sans
quoi le logo comprimerait le texte : mesuré, marges et espacement
occupent 78 px, le message 30 et la barre 4.

L'image source fait 512 px — la poser telle quelle ferait exploser le
cadre.
"""


def _charger_le_logo(taille: int):
    """Le logo de l'application, mis à l'échelle. `None` s'il manque.

    Même image que l'icône de la fenêtre et du Dock : c'est la même
    identité, au même endroit.

    Rend `None` plutôt que de lever : l'écran est un confort, et une
    ressource absente ne doit pas empêcher l'application de s'ouvrir.
    """
    chemin = (
        Path(__file__).resolve().parent.parent / "resources" / "icon-512.png"
    )
    if not chemin.exists():
        return None

    image = QPixmap(str(chemin))
    if image.isNull():
        return None

    return image.scaled(
        taille,
        taille,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def should_show_splash(repository) -> bool:
    """L'ouverture de ce dépôt sera-t-elle assez longue pour l'annoncer ?

    Compte les refs plutôt que de mesurer : construire le graphe pour
    savoir s'il faut annoncer sa construction serait absurde. Mesuré à
    9 ms sur un dépôt de 650 refs, négligeable devant ce qu'il couvre.

    Un dépôt illisible rend `False` : l'écran est un confort, et lever
    ici empêcherait l'application de s'ouvrir pour afficher son erreur.
    """
    try:
        refs = repository.references
        total = sum(1 for _ in refs)
    except (pygit2.GitError, KeyError, ValueError, AttributeError, TypeError):
        return False

    return total > REFS_POUR_AFFICHER


class StartupSplash(QWidget):
    """Fenêtre sans bordure, affichée le temps du premier chargement."""

    def __init__(self, nom_du_depot: str, parent=None):
        super().__init__(parent)
        # `SplashScreen` plutôt qu'une fenêtre ordinaire : pas de barre
        # de titre à fermer, et elle reste au-dessus pendant que la
        # principale se construit.
        self.setWindowFlags(
            Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint
        )
        self.setFixedSize(LARGEUR, HAUTEUR)

        # Le logo à la place du mot « tortoisePy » (demandé), dans la même
        # bande : la fenêtre garde ses proportions.
        self.logo = QLabel()
        self.logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image = _charger_le_logo(TAILLE_LOGO)
        if image is not None:
            self.logo.setPixmap(image)
        else:
            # Sans image, le nom écrit vaut mieux qu'une bande vide.
            self.logo.setText("tortoisePy")
            police = QFont(theme.NODE_FONT_FAMILY, 20)
            police.setBold(True)
            self.logo.setFont(police)

        # Nommer le dépôt ET le travail en cours : « Chargement… » seul
        # laisse croire à un blocage, et plusieurs fenêtres peuvent
        # cohabiter sur des dépôts différents.
        self._label = QLabel(
            f"Ouverture de « {nom_du_depot} »\n"
            "Construction du graphe des révisions…"
        )
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setWordWrap(True)

        # Barre indéterminée : un texte figé ne distingue pas « ça
        # travaille » de « ça a planté », et la durée dépend du dépôt.
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(4)

        cadre = QFrame()
        cadre.setObjectName("cadreSplash")
        interieur = QVBoxLayout(cadre)
        interieur.setContentsMargins(28, 24, 28, 24)
        interieur.setSpacing(14)
        interieur.addWidget(self.logo)
        interieur.addWidget(self._label)
        interieur.addStretch(1)
        interieur.addWidget(self.progress)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(cadre)

        # Les couleurs suivent la palette du système : codées en dur,
        # elles seraient illisibles dans l'un des deux thèmes — le
        # défaut que `theme.py` documente pour les couleurs du diff.
        cadre.setStyleSheet(
            "#cadreSplash {"
            "  background: palette(base);"
            "  border: 1px solid palette(mid);"
            "  border-radius: 10px;"
            "}"
        )

        self._centrer()

    def _centrer(self) -> None:
        """Place l'écran au centre de l'écran physique.

        Signalé par l'utilisateur : il apparaissait en haut à gauche. Qt
        place une fenêtre sans bordure à l'origine par défaut, et un
        écran d'attente décentré paraît égaré — c'est le premier contact
        avec l'application.

        `availableGeometry` et non `geometry` : la barre de menus et le
        Dock de macOS ne comptent pas comme espace utilisable.
        """
        ecran = QGuiApplication.primaryScreen()
        if ecran is None:
            return

        cadre = self.frameGeometry()
        cadre.moveCenter(ecran.availableGeometry().center())
        self.move(cadre.topLeft())

    def showEvent(self, event) -> None:
        """Recentre à l'affichage, la taille du cadre étant alors connue.

        Le centrage du constructeur suffit à une taille fixe, mais Qt
        peut ajuster le cadre selon le gestionnaire de fenêtres : mieux
        vaut recalculer une fois la fenêtre réellement posée.
        """
        super().showEvent(event)
        self._centrer()

    def pump(self) -> None:
        """Rend la main à Qt le temps de repeindre.

        Signalé par l'utilisateur : « la barre de chargement ne bouge
        pas ». Qt anime une barre indéterminée depuis sa boucle
        d'événements — or le fil principal est occupé une seconde et
        demie à construire la fenêtre, donc la boucle ne tourne pas.
        Mesuré : zéro tic de minuteur pendant un blocage nu, dix avec
        pompage.

        Un écran figé dit le contraire de ce qu'il affirme : que le
        travail avance.

        Sans application vivante — cas des tests isolés — il n'y a rien
        à pomper, et appeler `processEvents` lèverait.
        """
        application = QGuiApplication.instance()
        if application is not None:
            application.processEvents()

    def message(self) -> str:
        return self._label.text()

    def title_text(self) -> str:
        """Le texte de l'en-tête : vide quand le logo s'affiche.

        Conservé pour le repli — une ressource absente écrit le nom —
        et parce qu'un test vérifie que l'application se nomme.
        """
        return self.logo.text() or "tortoisePy"

    def finish(self) -> None:
        """Retire l'écran. Appelable plusieurs fois sans dommage.

        Le chemin d'erreur peut le fermer après le chemin normal : lever
        ici masquerait l'erreur qu'on cherchait à montrer.
        """
        self.close()
