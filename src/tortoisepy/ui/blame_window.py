"""Qui a écrit chaque ligne d'un fichier — phase 14.

Fenêtre en lecture seule : elle affiche le résultat de `blame_file` (tâche 1)
et laisse cliquer une ligne pour aller voir le commit qui l'a écrite (D28 :
« qui » puis « pourquoi »).
"""

from __future__ import annotations

import pygit2
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QLabel,
    QMainWindow,
    QProgressBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tortoisepy.ui import theme
from tortoisepy.core.blame import BlameError, blame_file
from tortoisepy.ui.tasks import BackgroundTask, CallableWorker

OID_ROLE = Qt.ItemDataRole.UserRole

# Deux teintes discrètes, alternées à chaque changement de commit, pour que
# les blocs se voient sans lire les SHA. Dérivées ici, pas dans `theme.py` :
# cette fenêtre n'a rien à voir avec le rendu du graphe.
_TINTS_CLAIR = (QColor(255, 255, 255), QColor(240, 240, 245))
_TINTS_SOMBRE = (QColor(30, 30, 30), QColor(45, 45, 52))


def _tints() -> tuple[QColor, QColor]:
    """Teintes adaptées au thème courant.

    Codées en dur pour un fond blanc, elles donnaient un fond #f0f0f5
    sous un texte de palette #ebebeb en thème sombre — **1,02:1 de
    contraste**, soit du texte invisible. Le même défaut avait déjà été
    signalé par l'utilisateur sur l'aperçu des conflits ; `theme.py`
    expose `is_dark_theme()` précisément pour cela.
    """
    return _TINTS_SOMBRE if theme.is_dark_theme() else _TINTS_CLAIR


class BlameWindow(QMainWindow):
    """Qui a écrit chaque ligne d'un fichier, à un commit donné."""

    commit_activated = Signal(str)
    """OID du commit d'origine de la ligne activée (D28)."""

    def __init__(
        self, repository: pygit2.Repository, path: str, oid: str, parent=None
    ):
        super().__init__(parent)
        self.repository = repository
        self.path = path
        self.oid = oid

        self._message = QLabel()
        self._message.setWordWrap(True)
        self._message.hide()

        self._lines = QTreeWidget()
        self._lines.setColumnCount(4)
        self._lines.setHeaderLabels(("Commit", "Auteur", "Date", "Ligne"))
        self._lines.setRootIsDecorated(False)
        self._lines.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._lines.itemActivated.connect(
            lambda item, _colonne: self._activate(item)
        )

        # Le calcul part en arrière-plan : `blame_file` est l'opération
        # la plus coûteuse de git, et son prix suit le nombre de commits
        # ayant touché LE FICHIER. Mesuré sur ce dépôt, et l'écart s'est
        # creusé en trois jours de travail sur le même fichier :
        #
        #     ui/main_window.py    507 ms  ->  1980 ms
        #
        # Appelé depuis `__init__`, il s'exécutait AVANT le premier rendu :
        # la fenêtre s'ouvrait grise et vide pendant tout ce temps.
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)      # indéterminé : durée inconnue
        self.progress.setMaximumWidth(200)
        self.progress.setFormat("Calcul du blâme…")
        self.progress.hide()

        # La tâche en cours, gardée pour que Python ne collecte ni le fil
        # ni son ouvrier pendant l'exécution (piège QThread connu).
        self._task: BackgroundTask | None = None

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self._message)
        layout.addWidget(self._lines)
        layout.addWidget(self.progress)
        self.setCentralWidget(central)
        self.resize(900, 700)

        self.setWindowTitle(f"Blame — {path} @ {oid[:8]}")
        self.reload()

    def reload(self) -> None:
        """Relance le calcul en arrière-plan."""
        if self._task is not None and self._task.is_running():
            return

        self.progress.show()

        def calculer():
            return blame_file(self.repository, self.path, self.oid)

        self._task = BackgroundTask(CallableWorker(calculer), self)
        self._task.finished.connect(self._afficher)
        self._task.start()

    def line_count(self) -> int:
        """Nombre de lignes affichées. Sert aux tests."""
        return self._lines.topLevelItemCount()

    def closeEvent(self, event) -> None:
        """Attend la tâche avant de rendre la fenêtre.

        Sans cette attente, fermer pendant le calcul détruirait le
        `QThread` en pleine exécution — « QThread: Destroyed while thread
        is still running », le défaut déjà corrigé ailleurs.
        """
        tache = self._task
        if tache is not None:
            arreter = getattr(tache, "stop", None)
            if callable(arreter):
                arreter(10_000)
        super().closeEvent(event)

    def _afficher(self, resultat) -> None:
        """Pose le résultat dans la liste. **Fil principal uniquement** :
        Qt interdit de toucher aux widgets ailleurs."""
        self.progress.hide()
        self._lines.clear()

        if isinstance(resultat, Exception) and not isinstance(
            resultat, BlameError
        ):
            # `CallableWorker` rapporte une exception plutôt que de
            # l'avaler : sans ce mot, la fenêtre resterait vide et muette.
            self._message.setText(f"Calcul impossible : {resultat}")
            self._message.show()
            return

        if isinstance(resultat, BlameError):
            self._message.setText(resultat.reason)
            self._message.show()
            return

        # Un fichier vide rend `()` : sans ce mot, la fenêtre s'ouvrait
        # vide et muette, indiscernable d'un défaut (6 fichiers de ce
        # dépôt sont dans ce cas).
        if not resultat:
            self._message.setText("Ce fichier est vide.")
            self._message.show()
            return

        # Un calcul réussi efface le message d'un essai précédent, sinon
        # « Ce fichier est vide » survivrait à un rechargement correct.
        self._message.hide()

        teintes = _tints()
        teinte_precedente: str | None = None
        indice_teinte = 0
        for ligne in resultat:
            if ligne.oid != teinte_precedente:
                teinte_precedente = ligne.oid
                indice_teinte = (indice_teinte + 1) % len(teintes)

            item = QTreeWidgetItem(
                [
                    ligne.short_oid,
                    ligne.author,
                    f"{ligne.when:%d/%m/%Y}" if ligne.oid else "",
                    ligne.text,
                ]
            )
            item.setData(0, OID_ROLE, ligne.oid)

            fond = QBrush(teintes[indice_teinte])
            for colonne in range(self._lines.columnCount()):
                item.setBackground(colonne, fond)

            self._lines.addTopLevelItem(item)

    def _activate(self, item: QTreeWidgetItem | None) -> None:
        # `item` peut être `None` : un fichier binaire ou absent laisse la
        # liste vide, et un appel hors bornes plantait sur un `NoneType`
        # (vérifié). Une ligne qui n'existe pas n'active rien.
        if item is None:
            return
        oid = item.data(0, OID_ROLE)
        if oid:
            self.commit_activated.emit(oid)

    def line_count(self) -> int:
        return self._lines.topLevelItemCount()

    def message(self) -> str:
        return self._message.text()

    def _item_at(self, numero: int) -> QTreeWidgetItem | None:
        # `numero` est le numéro de ligne du fichier, 1-indexé — comme
        # `BlameLine.number` — alors que `topLevelItem` est 0-indexé.
        # Rend `None` hors bornes, ce que les appelants doivent gérer :
        # la liste est vide sur un binaire ou un fichier absent.
        if numero < 1:
            return None
        return self._lines.topLevelItem(numero - 1)

    def author_at(self, numero: int) -> str:
        item = self._item_at(numero)
        return item.text(1) if item is not None else ""

    def oid_at(self, numero: int) -> str:
        item = self._item_at(numero)
        return item.data(0, OID_ROLE) if item is not None else ""

    def activate_line(self, numero: int) -> None:
        self._activate(self._item_at(numero))
