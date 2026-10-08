"""Fenêtre « Keyboard Shortcuts » : afficher et modifier.

L'affichage est natif (⌘F sur macOS, Ctrl+F sur Windows), le stockage
portable (§D47). La conversion se fait ici, à la frontière : `core/` ne
connaît que des chaînes portables.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from tortoisepy.core.shortcuts import CATALOGUE, spec_for, validate
from tortoisepy.ui.dialogs import show_message
from tortoisepy.ui.settings_store import SettingsStore


def _natif(sequence: str) -> str:
    """Texte portable -> texte natif, pour l'affichage seul."""
    return QKeySequence(sequence).toString(
        QKeySequence.SequenceFormat.NativeText
    )


class _CaptureDialog(QDialog):
    """Boîte modale minimale : capture une séquence via `QKeySequenceEdit`.

    Pas de capture de touches réimplémentée à la main : c'est exactement
    le rôle de ce widget Qt.
    """

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Change shortcut — {label}")

        disposition = QVBoxLayout(self)
        disposition.addWidget(QLabel("Press the new shortcut:"))

        self.editeur = QKeySequenceEdit(self)
        disposition.addWidget(self.editeur)

        boutons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        boutons.accepted.connect(self.accept)
        boutons.rejected.connect(self.reject)
        disposition.addWidget(boutons)

    def sequence_portable(self) -> str:
        """Ce qui est passé à `try_assign` : jamais le texte natif."""
        return self.editeur.keySequence().toString(
            QKeySequence.SequenceFormat.PortableText
        )


class ShortcutsWindow(QDialog):
    """Liste les raccourcis et permet de les réassigner."""

    shortcuts_changed = Signal(dict)
    """Émis après une assignation ACCEPTÉE, avec les séquences résolues.

    La fenêtre principale s'y branche pour appliquer sans relancer l'app.
    Un refus n'émet rien : sans cela, un conflit repeindrait l'interface
    avec un état que le magasin n'a pas enregistré.
    """

    def __init__(self, store: SettingsStore, parent=None):
        super().__init__(parent)
        self._store = store
        self.setWindowTitle("Keyboard Shortcuts")

        disposition = QVBoxLayout(self)
        disposition.addWidget(
            QLabel("Double-click a shortcut to change it.")
        )

        self.table = QTableWidget(len(CATALOGUE), 2, self)
        self.table.setHorizontalHeaderLabels(["Action", "Shortcut"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.cellDoubleClicked.connect(self._on_row_double_clicked)
        disposition.addWidget(self.table)

        boutons = QHBoxLayout()
        self.reset_button = QPushButton("Reset to defaults", self)
        self.reset_button.clicked.connect(self.reset_all)
        boutons.addWidget(self.reset_button)
        boutons.addStretch(1)
        self.close_button = QPushButton("Close", self)
        self.close_button.clicked.connect(self.accept)
        boutons.addWidget(self.close_button)
        disposition.addLayout(boutons)

        self._refresh()

    def rows(self) -> tuple[tuple[str, str, str], ...]:
        """(action_id, libellé, séquence en texte natif)."""
        resolus = self._store.resolved_shortcuts()
        return tuple(
            (spec.action_id, spec.label, _natif(resolus[spec.action_id]))
            for spec in CATALOGUE
        )

    def _refresh(self) -> None:
        for ligne, (_, label, natif) in enumerate(self.rows()):
            self.table.setItem(ligne, 0, QTableWidgetItem(label))
            element = QTableWidgetItem(natif)
            element.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(ligne, 1, element)

    def try_assign(self, action_id: str, sequence: str) -> str | None:
        """Motif du refus, ou `None` si la séquence a été enregistrée.

        Rien n'est écrit tant que la validation n'est pas passée : un
        refus doit laisser l'état exactement tel qu'il était.
        """
        motif = validate(
            action_id, sequence, self._store.resolved_shortcuts()
        )
        if motif is not None:
            return motif

        spec = spec_for(action_id)
        # Revenir au défaut efface la surcharge plutôt que de l'écrire
        # (§D49) : le défaut pourra ainsi évoluer plus tard.
        if spec is not None and sequence == spec.default:
            self._store.set_shortcut(action_id, None)
        else:
            self._store.set_shortcut(action_id, sequence)

        self._refresh()
        self.shortcuts_changed.emit(self._store.resolved_shortcuts())
        return None

    def reset_all(self) -> None:
        self._store.reset_shortcuts()
        self._refresh()
        self.shortcuts_changed.emit(self._store.resolved_shortcuts())

    def _demander_sequence(self, action_id: str) -> str | None:
        """Ouvre la capture modale ; `None` si l'utilisateur annule.

        Isolée dans sa propre méthode pour que les tests puissent la
        remplacer sans faire apparaître de fenêtre modale bloquante.
        """
        spec = spec_for(action_id)
        label = spec.label if spec is not None else action_id
        boite = _CaptureDialog(label, self)
        if boite.exec() != QDialog.DialogCode.Accepted:
            return None
        return boite.sequence_portable()

    def _on_row_double_clicked(self, ligne: int, _colonne: int) -> None:
        """Double-clic sur une ligne : capture puis tente l'assignation.

        Une annulation ou un refus n'écrit rien (§ refus total de
        `try_assign`) ; seul un refus affiche un message, une annulation
        est silencieuse.
        """
        action_id = self.rows()[ligne][0]
        sequence = self._demander_sequence(action_id)
        if sequence is None:
            return

        motif = self.try_assign(action_id, sequence)
        if motif is not None:
            # Jamais un `QMessageBox` : Qt le traduit en `NSAlert`
            # natif, qui plante macOS 27 (cf. `dialogs._BoiteSimple`).
            show_message(self, "Shortcut refused", motif)
