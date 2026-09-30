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
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tortoisepy.ui import theme
from tortoisepy.core.blame import BlameError, blame_file

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

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self._message)
        layout.addWidget(self._lines)
        self.setCentralWidget(central)
        self.resize(900, 700)

        self.setWindowTitle(f"Blame — {path} @ {oid[:8]}")
        self._load()

    def _load(self) -> None:
        resultat = blame_file(self.repository, self.path, self.oid)

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
