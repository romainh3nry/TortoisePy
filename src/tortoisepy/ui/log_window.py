"""Fenêtre de journal : les commits d'une branche, ou d'un fichier.

Une seule fenêtre pour les deux usages, parce que la liste, la recherche
et le rendu sont communs — seule la source change :

  - une **ref** : ce que `show_log` promettait au menu contextuel sans
    jamais rien afficher (il rendait un succès vide) ;
  - un **chemin** : « quand ce fichier a-t-il changé, et pourquoi ? »,
    question qu'aucun écran ne savait traiter et qu'on se pose juste
    avant un blâme.

La lecture part en **arrière-plan** dès cette première version, loader
compris. Mesuré : 104 ms pour 70 commits sur ce dépôt, coût linéaire en
commits PARCOURUS et non trouvés — un fichier peu touché paie le parcours
complet. Sur un dépôt de plusieurs milliers de commits, cela se compte en
secondes, et ce serait le gel déjà signalé trois fois par l'utilisateur.

Fenêtre de **consultation** : elle ne modifie rien (§7.0).
"""

from __future__ import annotations

import pygit2
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tortoisepy.core.commits import CommitInfo
from tortoisepy.core.log import DEFAULT_LIMIT, read_log
from tortoisepy.ui.tasks import BackgroundTask, CallableWorker

COLONNES = ("Commit", "Message", "Auteur", "Date")
"""Mêmes colonnes que le panneau latéral : une seule grammaire à apprendre."""

COULEUR_MERGE = QColor(110, 110, 150)
"""Un merge est grisé, comme dans le panneau."""


class LogWindow(QMainWindow):
    """Les commits d'une ref et/ou d'un chemin, paginés."""

    commit_activated = Signal(str)
    """OID du commit activé : la fenêtre appelante ouvre son détail."""

    def __init__(
        self,
        repository: pygit2.Repository,
        *,
        ref: str | None = None,
        path: str | None = None,
        until: str | None = None,
        page_size: int = DEFAULT_LIMIT,
        parent=None,
    ):
        super().__init__(parent)
        self.repository = repository
        self.ref = ref
        self.path = path
        # Borne le parcours — « git log A..B » : les commits de B que A
        # n'a pas. Sert à « Show log of differences », qui sinon
        # afficherait tout l'historique comme « Show log ».
        self.until = until
        self.page_size = page_size

        # Les commits déjà lus, gardés en mémoire : la recherche filtre
        # cette liste au lieu de relire le dépôt, sinon chaque frappe
        # coûterait un parcours complet.
        self._charges: list[CommitInfo] = []

        # La tâche en cours, gardée pour que Python ne collecte ni le fil
        # ni son ouvrier pendant l'exécution (piège QThread connu).
        self._task: BackgroundTask | None = None

        self._message = QLabel()
        self._message.setWordWrap(True)
        self._message.hide()

        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("Filtrer les messages…")
        self.search_field.setClearButtonEnabled(True)
        # `returnPressed` ET `textChanged` : le filtrage est local, donc
        # assez rapide pour suivre la frappe (vérifié par un test qui
        # interdit toute relecture du dépôt).
        self.search_field.textChanged.connect(self.apply_search)

        self._commits = QTreeWidget()
        self._commits.setColumnCount(len(COLONNES))
        self._commits.setHeaderLabels(COLONNES)
        self._commits.setRootIsDecorated(False)
        self._commits.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._commits.itemActivated.connect(
            lambda item, _colonne: self._activer(item)
        )

        # Signalé par l'utilisateur : « les colonnes ont l'air très
        # courtes et empêchent de voir l'ensemble du message ». Qt donne
        # par défaut la même largeur à toutes, alors que seul le message
        # est de longueur imprévisible — les trois autres (abrégé sur 8
        # caractères, auteur, date au format court) ont une taille
        # connue. Le message absorbe donc le reste, comme dans le panneau
        # latéral, dont cette fenêtre avait oublié la convention.
        entete = self._commits.header()
        # `setStretchLastSection(False)` est indispensable : par défaut Qt
        # fait absorber toute la place restante à la DERNIÈRE colonne,
        # malgré son `ResizeToContents`. Mesuré avant correction, la
        # colonne Date prenait 372 px pour afficher « 04/10/25 », ne
        # laissant que 373 px au message sur une fenêtre de 900.
        entete.setStretchLastSection(False)
        entete.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        entete.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        entete.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        entete.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)      # indéterminé : durée inconnue
        self.progress.setMaximumWidth(180)
        self.progress.setTextVisible(True)
        self.progress.hide()

        self.more_button = QPushButton("Load more")
        self.more_button.clicked.connect(self.load_more)
        self.more_button.hide()

        bas = QHBoxLayout()
        bas.addWidget(self.more_button)
        bas.addWidget(self.progress)
        bas.addStretch(1)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.search_field)
        layout.addWidget(self._message)
        layout.addWidget(self._commits)
        layout.addLayout(bas)
        self.setCentralWidget(central)
        self.resize(900, 600)

        self.setWindowTitle(self._titre())
        self._charger(premiere_page=True)

    # --- lecture -------------------------------------------------------

    def load_more(self) -> None:
        """Lit la page suivante et l'ajoute à la liste."""
        self._charger(premiere_page=False)

    def _charger(self, *, premiere_page: bool) -> None:
        """Lance la lecture en arrière-plan.

        `after` reprend au dernier commit déjà lu : ni répétition, ni
        saut. Une limite dure mentirait sur l'historique ; un parcours
        complet gèlerait l'interface.
        """
        if self._task is not None and self._task.is_running():
            return

        apres = None if premiere_page else (
            self._charges[-1].oid if self._charges else None
        )
        # Une page de plus que demandé : la présence d'un (n+1)-ième
        # commit est ce qui dit s'il reste quelque chose à lire. Sans ce
        # commit-témoin, « Load more » resterait offert pour une page
        # vide, ou disparaîtrait alors qu'il reste de l'historique.
        demande = self.page_size + 1

        def lire():
            return read_log(
                self.repository,
                ref=self.ref,
                path=self.path,
                limit=demande,
                after=apres,
                until=self.until,
            )

        def afficher(resultat):
            self.progress.hide()
            if isinstance(resultat, Exception):
                self._dire(f"Lecture impossible : {resultat}")
                return

            reste = len(resultat) > self.page_size
            if premiere_page:
                self._charges = list(resultat[: self.page_size])
            else:
                self._charges.extend(resultat[: self.page_size])

            self.more_button.setVisible(reste)
            self._remplir()

        self.progress.setFormat("Lecture du journal…")
        self.progress.show()
        self._task = BackgroundTask(CallableWorker(lire), self)
        self._task.finished.connect(afficher)
        self._task.start()

    # --- affichage -----------------------------------------------------

    def apply_search(self) -> None:
        """Filtre les commits DÉJÀ lus sur leur message.

        Purement local : relire le dépôt à chaque frappe rendrait le champ
        inutilisable sur un gros dépôt, alors que la liste est en mémoire.
        """
        self._remplir()

    def _remplir(self) -> None:
        motif = self.search_field.text().strip().lower()
        visibles = [
            commit for commit in self._charges
            if not motif or motif in commit.message.lower()
        ]

        self._commits.clear()
        for commit in visibles:
            item = QTreeWidgetItem([
                commit.short_oid,
                commit.summary,
                commit.author_name,
                f"{commit.when:%d/%m/%y}",
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, commit.oid)
            item.setToolTip(1, commit.message)
            if commit.is_merge:
                for colonne in range(len(COLONNES)):
                    item.setForeground(colonne, COULEUR_MERGE)
            self._commits.addTopLevelItem(item)

        if not self._charges:
            # Une liste vide et muette est indiscernable d'un défaut — le
            # même constat avait été fait sur le blâme d'un fichier vide.
            self._dire(
                f"Aucun commit ne touche « {self.path} »." if self.path
                else "Aucun commit à afficher."
            )
        else:
            self._message.hide()

        if visibles:
            self._commits.setCurrentItem(self._commits.topLevelItem(0))

    def _dire(self, texte: str) -> None:
        self._message.setText(texte)
        self._message.show()

    def _titre(self) -> str:
        """La source doit figurer au titre, sinon la fenêtre ne se relit pas."""
        if self.until:
            return f"Log — {self.until[:8]} … {(self.ref or 'HEAD')[:8]}"
        if self.path and self.ref:
            return f"Log — {self.path} @ {self.ref}"
        if self.path:
            return f"Log — {self.path}"
        return f"Log — {self.ref or 'HEAD'}"

    def _activer(self, item: QTreeWidgetItem) -> None:
        oid = item.data(0, Qt.ItemDataRole.UserRole)
        if oid:
            self.commit_activated.emit(oid)

    # --- fermeture -----------------------------------------------------

    def closeEvent(self, event) -> None:
        """Attend la tâche avant de rendre la fenêtre.

        Sans cette attente, fermer pendant la lecture détruirait le
        `QThread` en pleine exécution — « QThread: Destroyed while thread
        is still running », le défaut déjà corrigé sur la fenêtre
        principale puis sur celle de commit.
        """
        self._arreter_la_tache()
        super().closeEvent(event)

    def __del__(self) -> None:
        """Dernier recours : la fenêtre peut être DÉTRUITE sans être fermée.

        Reproduit (abort du processus, pas une simple erreur) : une fenêtre
        de journal ouverte depuis le détail d'un commit est détruite avec
        son parent Qt, sans que `closeEvent` passe. Si la lecture tourne
        encore, le `QThread` meurt en pleine exécution et Qt abandonne le
        processus.

        En usage réel, cela se produit en ouvrant un historique puis en
        fermant aussitôt la fenêtre qui l'a ouvert — d'autant plus
        probable que la lecture est longue, donc sur un gros dépôt.

        Enveloppé largement : pendant la destruction de l'interpréteur,
        les attributs et même les modules peuvent avoir disparu, et une
        exception levée dans `__del__` est de toute façon ignorée.
        """
        try:
            self._arreter_la_tache()
        except Exception:   # noqa: BLE001 — rien à rattraper à ce stade
            pass

    def _arreter_la_tache(self) -> None:
        """Demande l'arrêt du fil, puis l'attend.

        `stop()` laisse l'opération en cours finir : on ne coupe pas une
        lecture au milieu, on cesse seulement de traiter la suite.
        `getattr` parce qu'un double de test n'a pas forcément la méthode.
        """
        tache = self._task
        if tache is None:
            return
        self._task = None
        arreter = getattr(tache, "stop", None)
        if callable(arreter):
            arreter(10_000)
