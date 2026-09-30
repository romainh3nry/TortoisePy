"""Panneau des commits — révèle ce que la compression masque (§4.2.1).

Double-cliquer un nœud affiche les commits que son arête entrante compresse :
exactement ce qu'annonce son étiquette (« 40 commits »), plus le commit du
nœud lui-même.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QStyledItemDelegate,
    QHeaderView,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from tortoisepy.core.commits import CommitInfo
from tortoisepy.ui import theme

COLUMNS = ("Commit", "Message", "Auteur", "Date")
"""Le message d'abord : c'est la colonne qu'on lit. Reléguée en dernier,
elle sortait du champ dès que le panneau était un peu étroit."""

MERGE_COLOR = QColor(110, 110, 150)
"""Les commits de merge sont teintés : ils structurent l'historique."""

HISTORY_LIMIT = 500
"""Doit correspondre à la limite de `core.commits._history`.

Au-delà, le panneau affiche « 500+ » : annoncer un nombre rond comme s'il
était exact laisserait croire que la branche s'arrête là."""

OWN_BORDER = QColor(200, 130, 20)
"""Couleur du cadre entourant les commits ajoutés par la branche cliquée.

Le panneau montre TOUT l'historique : sans marque, rien ne distinguerait
l'apport de la branche du travail hérité.

Deux approches ont été essayées et mesurées avant celle-ci :

- **Fond jaune pâle** : contraste 1,06 avec le fond blanc, imperceptible.
  Il recouvrait en outre le bleu de sélection, dont Qt garde le texte
  blanc — la ligne sélectionnée devenait illisible.
- **Texte grisé** pour les commits hérités : lisible sur fond blanc
  (3,36) mais pas sur une ligne sélectionnée (1,10), un `foreground`
  explicite primant sur la couleur de sélection.

Un cadre ne touche ni au fond ni à la couleur du texte : il reste visible
quel que soit l'état de la ligne."""

OWN_BORDER_WIDTH = 2.0


OWN_ROLE = Qt.ItemDataRole.UserRole + 1
"""Rôle portant « ce commit vient-il de la branche cliquée ? »."""

UNPUSHED_ROLE = Qt.ItemDataRole.UserRole + 2
"""Rôle portant « ce commit est-il encore absent du serveur ? ».

Même patron que `OWN_ROLE` : une marque dit d'où vient le commit, l'autre
où il en est côté remote — les deux coexistent sans se gêner."""


class OwnCommitDelegate(QStyledItemDelegate):
    """Encadre les commits ajoutés par la branche cliquée.

    Le cadre est tracé APRÈS le rendu normal, donc par-dessus le fond de
    sélection : il reste visible que la ligne soit sélectionnée ou non.
    Les bords verticaux ne sont tracés qu'aux extrémités, pour que le
    cadre entoure la ligne entière et non chaque cellule.
    """

    def paint(self, painter, option, index) -> None:
        super().paint(painter, option, index)

        model = index.model()
        if not _is_own(model, index.row(), index.parent()):
            return

        # Un cadre unique autour du BLOC, pas autour de chaque ligne : les
        # bords horizontaux ne sont tracés qu'aux extrémités du groupe.
        first = not _is_own(model, index.row() - 1, index.parent())
        last = not _is_own(model, index.row() + 1, index.parent())

        rect = QRectF(option.rect)
        inset = OWN_BORDER_WIDTH / 2.0
        rect = rect.adjusted(
            0.0, inset if first else 0.0, 0.0, -inset if last else 0.0
        )

        painter.save()
        painter.setPen(QPen(OWN_BORDER, OWN_BORDER_WIDTH))

        if first:
            painter.drawLine(rect.topLeft(), rect.topRight())
        if last:
            painter.drawLine(rect.bottomLeft(), rect.bottomRight())

        # Les bords verticaux courent sur toute la hauteur du bloc, donc
        # sur chaque ligne, mais seulement aux colonnes extrêmes.
        if index.column() == 0:
            painter.drawLine(rect.topLeft(), rect.bottomLeft())
        if index.column() == model.columnCount() - 1:
            painter.drawLine(rect.topRight(), rect.bottomRight())

        painter.restore()


def _is_own(model, row: int, parent) -> bool:
    """Le commit de cette ligne vient-il de la branche cliquée ?

    Hors des limites du modèle, la réponse est « non » : cela fait
    naturellement de la première et de la dernière ligne du groupe les
    extrémités du cadre.
    """
    if row < 0 or row >= model.rowCount(parent):
        return False
    return bool(model.index(row, 0, parent).data(OWN_ROLE))


class CommitPanel(QWidget):
    """Liste les commits d'un nœud, dans un volet latéral."""

    commit_selected = Signal(str)

    commit_activated = Signal(str)
    """Double-clic sur un commit — la fenêtre principale ouvre son détail."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self._title = QLabel("Double-cliquez un nœud pour voir ses commits")
        self._title.setWordWrap(True)
        font = self._title.font()
        font.setBold(True)
        self._title.setFont(font)

        # `None` = aucun filtre ; un ensemble = ne montrer que ces OID.
        self._filtre: set | None = None

        self._tree = QTreeWidget()
        self._tree.setColumnCount(len(COLUMNS))
        self._tree.setHeaderLabels(COLUMNS)
        self._tree.setRootIsDecorated(False)
        # Désactivé : les lignes alternées masqueraient le fond des
        # commits propres à la branche.
        self._tree.setAlternatingRowColors(False)
        self._tree.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._tree.setFont(QFont(theme.NODE_FONT_FAMILY, 11))
        self._tree.itemSelectionChanged.connect(self._on_selection)
        self._tree.itemDoubleClicked.connect(self._on_double_click)
        self._tree.setItemDelegate(OwnCommitDelegate(self._tree))

        header = self._tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)

        self.setMinimumWidth(420)

        # Le champ vit dans le panneau, et non dans la barre d'outils :
        # il prend ainsi exactement la largeur de la liste qu'il filtre,
        # et suit le splitter quand on la redimensionne (demandé par
        # l'utilisateur). Dans la barre, il flottait à droite sans rapport
        # visuel avec ce sur quoi il agit.
        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("Search message, author or SHA…")
        self.search_field.setClearButtonEnabled(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.search_field)
        layout.addWidget(self._title)
        layout.addWidget(self._tree)

    def filter_to(self, oids) -> int:
        """Masque les commits absents de `oids`. Rend le nombre affiché.

        Masquer plutôt que recharger : les lignes portent déjà leur OID,
        leur état « propre à la branche » et leur marque de non-poussé —
        les reconstruire les perdrait, et coûterait un nouveau parcours
        de l'historique.

        `oids` vide **n'efface pas** le filtre : c'est « aucun résultat ».
        Passer `None` le lève.
        """
        visibles = 0
        garde = None if oids is None else set(oids)

        for index in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(index)
            oid = item.data(0, Qt.ItemDataRole.UserRole)
            montrer = garde is None or oid in garde
            item.setHidden(not montrer)
            visibles += int(montrer)

        self._filtre = garde
        return visibles

    def visible_count(self) -> int:
        """Lignes actuellement affichées — le filtre étant appliqué."""
        return sum(
            1
            for i in range(self._tree.topLevelItemCount())
            if not self._tree.topLevelItem(i).isHidden()
        )

    def show_commits(
        self,
        label: str,
        commits: tuple[CommitInfo, ...],
        unpushed: frozenset[str] = frozenset(),
    ) -> None:
        """Remplit le panneau pour un nœud donné."""
        self._tree.clear()

        count = len(commits)
        own = sum(1 for c in commits if c.own)
        plural = "" if count == 1 else "s"

        # L'historique est borné (§ CommitInfo) : au-delà, dire « sur 500 »
        # ferait croire que la branche n'en a pas davantage.
        truncated = count >= HISTORY_LIMIT
        total = f"{count}+" if truncated else str(count)

        if own and own < count:
            # Dire les deux nombres : « 4 sur 26 » se comprend mieux que
            # « 26 commits » quand seuls 4 viennent de cette branche.
            titre = (
                f"{label} — {own} commit{'' if own == 1 else 's'} "
                f"sur {total}"
            )
        else:
            titre = f"{label} — {total} commit{plural}"

        # Compte séparé du « own » : un commit peut être hérité ET non
        # poussé (branche qui n'a jamais publié son historique).
        non_pousses = sum(1 for c in commits if c.oid in unpushed)
        if non_pousses:
            titre += f" — {non_pousses} non poussé{'s' if non_pousses > 1 else ''}"

        self._title.setText(titre)

        for commit in commits:
            is_unpushed = commit.oid in unpushed
            oid_text = (
                f"↑ {commit.short_oid}" if is_unpushed else commit.short_oid
            )
            item = QTreeWidgetItem(
                [
                    oid_text,
                    commit.summary,
                    commit.author_name,
                    f"{commit.when:%d/%m/%y}",
                ]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, commit.oid)
            item.setToolTip(1, commit.message)

            # Le cadre est dessiné par `OwnCommitDelegate`, qui lit ce
            # drapeau. Passer par les données plutôt que par un style de
            # cellule garde le rendu indépendant de l'état de sélection.
            item.setData(0, OWN_ROLE, commit.own)
            item.setData(0, UNPUSHED_ROLE, is_unpushed)

            if commit.is_merge:
                for column in range(len(COLUMNS)):
                    item.setForeground(column, MERGE_COLOR)

            self._tree.addTopLevelItem(item)

        # Le panneau vient d'être reconstruit : sans cela, changer de nœud
        # pendant une recherche afficherait tout, alors que le champ est
        # encore rempli et le graphe encore surligné.
        if self._filtre is not None:
            self.filter_to(self._filtre)

        if commits:
            self._tree.setCurrentItem(self._tree.topLevelItem(0))

    def clear(self) -> None:
        self._tree.clear()
        self._title.setText("Double-cliquez un nœud pour voir ses commits")

    def count(self) -> int:
        return self._tree.topLevelItemCount()

    def title(self) -> str:
        return self._title.text()

    def is_unpushed(self, oid: str) -> bool:
        """Le commit affiché sous cet oid porte-t-il la marque « non poussé » ?"""
        for index in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(index)
            if item.data(0, Qt.ItemDataRole.UserRole) == oid:
                return bool(item.data(0, UNPUSHED_ROLE))
        return False

    def selected_oid(self) -> str | None:
        item = self._tree.currentItem()
        if item is None:
            return None
        return item.data(0, Qt.ItemDataRole.UserRole)

    def _on_selection(self) -> None:
        oid = self.selected_oid()
        if oid is not None:
            self.commit_selected.emit(oid)

    def _on_double_click(self, item, column) -> None:
        oid = item.data(0, Qt.ItemDataRole.UserRole)
        if oid is not None:
            self.commit_activated.emit(oid)
