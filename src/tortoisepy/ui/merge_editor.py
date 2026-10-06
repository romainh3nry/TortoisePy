"""Éditeur de fusion : yours | résultat | theirs.

Demandé par l'utilisateur après un rebase dans un dépôt réel, où deux
clés YAML indépendantes — `rate-limit:` et `twoFactorAuth:` — étaient
marquées en conflit parce qu'adjacentes :

    « j'aimerai que les deux blocs qui causent le conflit soient
      présents, sauf qu'en l'état on me propose uniquement l'un ou
      l'autre »

La fenêtre de conflits fait choisir un camp par fichier (D12), ce qui
couvre la majorité des cas. Elle ne couvre pas celui-ci : garder les
deux. D'où cette fenêtre, ouverte à la demande depuis la précédente.

Les deux côtés sont en **lecture seule** : ce sont des références. Les
rendre modifiables laisserait croire qu'on peut y écrire, alors que seule
la colonne du milieu est enregistrée.
"""

from __future__ import annotations

import os

import pygit2
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from tortoisepy.core.conflicts import read_versions, resolve_with_content
from tortoisepy.core.results import failed
from tortoisepy.ui.dialogs import show_error
from tortoisepy.ui import theme

MARQUEURS = ("<<<<<<<", "=======", ">>>>>>>")
"""Marqueurs que git insère dans un fichier en conflit.

git refuse de commiter un fichier qui en contient : le dire ici, où la
correction est à portée, vaut mieux que de le découvrir au commit.
"""


class MergeEditor(QMainWindow):
    """Compose le contenu final d'un fichier en conflit."""

    resolved = Signal(str)
    """Chemin du fichier résolu : la fenêtre appelante se rafraîchit."""

    def __init__(
        self,
        repository: pygit2.Repository,
        path: str,
        *,
        ours_label: str = "Yours",
        theirs_label: str = "Theirs",
        parent=None,
    ):
        super().__init__(parent)
        self.repository = repository
        self.path = path

        versions = read_versions(repository, path)
        self._ours = versions.ours if versions else ""
        self._theirs = versions.theirs if versions else ""

        self.ours_view = self._colonne(self._ours, lecture_seule=True)
        self.theirs_view = self._colonne(self._theirs, lecture_seule=True)

        # Signalé par l'utilisateur : « là c'est tout noir/blanc et on
        # voit mal les changements ». Les mêmes couleurs que la vue des
        # commits, pour n'avoir qu'une grammaire visuelle à apprendre.
        _colorer(self.ours_view, self._ours, self._theirs)
        _colorer(self.theirs_view, self._theirs, self._ours)
        # Le milieu part du FICHIER DE TRAVAIL, marqueurs compris : il
        # porte les parties sans conflit, que l'utilisateur ne doit pas
        # avoir à retaper, et montre où git a vu le désaccord.
        self.result_view = self._colonne(
            self._fichier_de_travail(), lecture_seule=False
        )

        self._labels = (ours_label, "Result", theirs_label)

        # Demandé par l'utilisateur : « des flèches qui permettent de
        # basculer le code d'un côté vers le milieu ». La colonne du
        # milieu est celle qui sera écrite.
        self.ours_arrow = QPushButton("→")
        self.ours_arrow.setToolTip(
            "Envoie la sélection (ou tout le côté) vers le résultat"
        )
        self.ours_arrow.setFixedWidth(32)
        self.ours_arrow.clicked.connect(self.send_ours_to_result)

        self.theirs_arrow = QPushButton("←")
        self.theirs_arrow.setToolTip(
            "Envoie la sélection (ou tout le côté) vers le résultat"
        )
        self.theirs_arrow.setFixedWidth(32)
        self.theirs_arrow.clicked.connect(self.send_theirs_to_result)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        for etiquette, vue, fleche in (
            (self._labels[0], self.ours_view, self.ours_arrow),
            (self._labels[1], self.result_view, None),
            (self._labels[2], self.theirs_view, self.theirs_arrow),
        ):
            splitter.addWidget(_colonne_titree(etiquette, vue, fleche))
        # Le milieu est le plus large : c'est là qu'on travaille.
        splitter.setStretchFactor(1, 2)

        self.both_button = QPushButton("Keep both")
        self.both_button.setToolTip(
            "Garde les deux côtés et retire les marqueurs de conflit"
        )
        self.both_button.clicked.connect(self.keep_both)

        self.ours_button = QPushButton(f"Take {ours_label.lower()}")
        self.ours_button.clicked.connect(self.take_ours)
        self.theirs_button = QPushButton(f"Take {theirs_label.lower()}")
        self.theirs_button.clicked.connect(self.take_theirs)

        self.save_button = QPushButton("Save resolution")
        self.save_button.clicked.connect(self.save)

        boutons = QHBoxLayout()
        boutons.addWidget(self.both_button)
        boutons.addWidget(self.ours_button)
        boutons.addWidget(self.theirs_button)
        boutons.addStretch(1)
        boutons.addWidget(self.save_button)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(splitter)
        layout.addLayout(boutons)
        self.setCentralWidget(central)

        self.setWindowTitle(f"Merge — {path}")
        self.resize(1200, 700)

    # --- composition ---------------------------------------------------

    def keep_both(self) -> None:
        """Retire les marqueurs en gardant les deux côtés.

        Le geste exact demandé par l'utilisateur. On travaille sur le
        fichier de travail — qui contient déjà tout, parties communes
        comprises — en ne retirant que les lignes de marquage. Composer
        à partir des deux blobs perdrait le contexte non conflictuel.
        """
        lignes = [
            ligne for ligne in self.result_view.toPlainText().splitlines()
            if not ligne.startswith(MARQUEURS)
        ]
        self.result_view.setPlainText("\n".join(lignes) + (
            "\n" if lignes else ""
        ))

    def send_ours_to_result(self) -> None:
        """Ajoute au résultat la sélection du côté « ours », ou tout.

        **Ajoute** plutôt que remplace : c'est tout l'intérêt par rapport
        à « Take ours » — composer morceau par morceau, ce qui est le cas
        signalé (deux clés YAML indépendantes à garder toutes les deux).

        Sans sélection, on envoie les lignes **propres** à ce côté — pas
        le côté entier. Les lignes communes sont déjà dans le résultat,
        et les renvoyer les duplique : mesuré sur le fichier réel de
        l'utilisateur, `myMTEmailCreation:` apparaissait deux fois après
        avoir cliqué les deux flèches.

        Ce sont exactement les lignes colorées, donc celles que la vue
        désigne déjà à l'œil.
        """
        self._envoyer(self.ours_view, _propres(self._ours, self._theirs))

    def send_theirs_to_result(self) -> None:
        self._envoyer(self.theirs_view, _propres(self._theirs, self._ours))

    def select_in_ours(self, debut: int, fin: int) -> None:
        """Sélectionne les lignes [debut, fin[ du côté « ours ».

        Point d'entrée des tests : simuler une sélection à la souris
        demanderait des événements que l'environnement sans écran ne
        produit pas.
        """
        _selectionner_lignes(self.ours_view, debut, fin)

    def select_in_theirs(self, debut: int, fin: int) -> None:
        _selectionner_lignes(self.theirs_view, debut, fin)

    def _envoyer(self, vue: QPlainTextEdit, defaut: str) -> None:
        """Place le morceau choisi À LA PLACE de la zone en conflit.

        Signalé par l'utilisateur : « quand on choisit un côté, on a
        encore les >>> qui indiquent le conflit ». Le défaut profond
        était plus large qu'un affichage : ajouter en fin de texte
        laissait LES DEUX camps dans le résultat, plus le bloc choisi.

        Tant que les marqueurs sont là, la première flèche tranche le
        conflit : elle remplace la zone balisée. Ensuite ils ont disparu,
        et la suivante ajoute son bloc à la suite du précédent — ce qui
        permet de garder les deux côtés, le cas qui a motivé cet éditeur.
        """
        morceau = vue.textCursor().selectedText()
        if morceau:
            # Qt sépare les lignes d'une sélection par U+2029, pas par
            # « \n » : les recoller tels quels collerait tout en une
            # ligne (vérifié).
            morceau = morceau.replace("\u2029", "\n")
        else:
            morceau = defaut

        if morceau and not morceau.endswith("\n"):
            morceau += "\n"

        actuel = self.result_view.toPlainText()
        remplace = _remplacer_zone_de_conflit(actuel, morceau)
        if remplace is not None:
            self.result_view.setPlainText(remplace)
            return

        # Plus de marqueurs : on ajoute à la suite du bloc déjà choisi.
        if actuel and not actuel.endswith("\n"):
            actuel += "\n"
        self.result_view.setPlainText(actuel + morceau)

    def take_ours(self) -> None:
        """Repart du camp « ours », quitte à le retoucher ensuite."""
        self.result_view.setPlainText(self._ours)

    def take_theirs(self) -> None:
        self.result_view.setPlainText(self._theirs)

    def column_labels(self) -> tuple[str, str, str]:
        """Les trois en-têtes, dans l'ordre d'affichage."""
        return self._labels

    # --- enregistrement -------------------------------------------------

    def save(self) -> None:
        """Écrit la colonne du milieu et résout le conflit."""
        contenu = self.result_view.toPlainText()

        restants = [m for m in MARQUEURS if m in contenu]
        if restants:
            # git refuserait de commiter ce fichier : le dire maintenant,
            # pendant que la correction est sous les yeux.
            show_error(self, failed(
                "Résolution",
                "Le contenu porte encore des marqueurs de conflit "
                f"({', '.join(restants)}). Retirez-les, ou utilisez "
                "« Keep both »."
            ))
            return

        resultat = resolve_with_content(self.repository, self.path, contenu)
        if not resultat.success:
            show_error(self, resultat)
            return

        self.resolved.emit(self.path)
        self.close()

    # --- interne --------------------------------------------------------

    def _fichier_de_travail(self) -> str:
        """Le fichier tel que git l'a laissé, marqueurs compris.

        Illisible s'il a disparu ou n'est pas du texte : on rend une
        chaîne vide plutôt que de lever, pour que la fenêtre s'ouvre
        quand même et montre au moins les deux côtés.
        """
        chemin = os.path.join(self.repository.workdir or "", self.path)
        try:
            with open(chemin, encoding="utf-8", errors="replace") as fichier:
                return fichier.read()
        except OSError:
            return ""

    def _colonne(self, texte: str, *, lecture_seule: bool) -> QPlainTextEdit:
        vue = QPlainTextEdit()
        vue.setPlainText(texte)
        vue.setReadOnly(lecture_seule)
        # Une police à chasse fixe : l'indentation d'un YAML ou d'un code
        # source est porteuse de sens, et une police proportionnelle la
        # rend illisible.
        vue.setFont(QFont("Menlo", 11))
        vue.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        return vue


def _remplacer_zone_de_conflit(texte: str, morceau: str) -> str | None:
    """Remplace `<<<<<<< … >>>>>>>` par `morceau`. `None` s'il n'y en a pas.

    Les lignes hors conflit sont conservées : elles portent le contexte,
    souvent l'essentiel du fichier, et les perdre obligerait à tout
    retaper.

    Une zone **incomplète** (marqueur d'ouverture sans fermeture, fichier
    tronqué) est laissée telle quelle plutôt que découpée au jugé : mieux
    vaut que l'utilisateur voie un contenu intact et décide lui-même.
    """
    lignes = texte.splitlines()
    debut = fin = None
    for i, ligne in enumerate(lignes):
        if debut is None and ligne.startswith("<<<<<<<"):
            debut = i
        elif debut is not None and ligne.startswith(">>>>>>>"):
            fin = i
            break

    if debut is None or fin is None:
        return None

    avant = lignes[:debut]
    apres = lignes[fin + 1:]
    milieu = morceau.splitlines()

    resultat = avant + milieu + apres
    return "\n".join(resultat) + ("\n" if resultat else "")


def _propres(texte: str, autre: str) -> str:
    """Les lignes de `texte` absentes de `autre`.

    Même règle que `_colorer` : ce qui est propre à un camp est ce qui le
    distingue, et c'est ce que la flèche envoie — les lignes colorées,
    celles que la vue désigne déjà à l'œil.
    """
    communes = set(autre.splitlines())
    gardees = [
        ligne for ligne in texte.splitlines()
        if ligne.strip() and ligne not in communes
    ]
    return "\n".join(gardees) + ("\n" if gardees else "")


def _colorer(vue: QPlainTextEdit, texte: str, autre: str) -> None:
    """Surligne les lignes propres à ce camp.

    Une ligne absente de l'autre camp est ce qui distingue les deux :
    c'est elle qu'on cherche du regard. Les lignes communes restent
    neutres — les surligner attirerait l'œil sur ce qui n'a pas changé,
    et dans un fichier de configuration le commun domine largement.

    Comparaison par **ensemble de lignes**, pas par position : un bloc
    ajouté plus haut décale tout ce qui suit, et une comparaison ligne à
    ligne peindrait alors le fichier entier.

    Les couleurs viennent de `theme.diff_colors()`, donc les mêmes que
    la vue des commits, et elles suivent le thème clair ou sombre.
    """
    couleurs = theme.diff_colors()
    communes = set(autre.splitlines())

    fmt = QTextCharFormat()
    fmt.setBackground(couleurs["added_bg"])
    fmt.setForeground(couleurs["added_fg"])

    curseur = QTextCursor(vue.document())
    curseur.movePosition(QTextCursor.MoveOperation.Start)
    for ligne in texte.splitlines():
        if ligne.strip() and ligne not in communes:
            curseur.movePosition(
                QTextCursor.MoveOperation.EndOfBlock,
                QTextCursor.MoveMode.KeepAnchor,
            )
            curseur.setCharFormat(fmt)
            curseur.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        if not curseur.movePosition(QTextCursor.MoveOperation.NextBlock):
            break


def _selectionner_lignes(vue: QPlainTextEdit, debut: int, fin: int) -> None:
    """Sélectionne les lignes [debut, fin[ d'une vue."""
    curseur = QTextCursor(vue.document())
    curseur.movePosition(QTextCursor.MoveOperation.Start)
    for _ in range(debut):
        curseur.movePosition(QTextCursor.MoveOperation.NextBlock)
    for _ in range(fin - debut):
        curseur.movePosition(
            QTextCursor.MoveOperation.NextBlock,
            QTextCursor.MoveMode.KeepAnchor,
        )
    vue.setTextCursor(curseur)


def _colonne_titree(
    titre: str, vue: QPlainTextEdit, fleche: QPushButton | None = None
) -> QWidget:
    """Une colonne avec son étiquette au-dessus.

    Sans étiquette, on ne sait pas quel côté est lequel — l'utilisateur
    l'avait déjà signalé sur la fenêtre de conflits : « on ne sait pas de
    quelle version appartiennent ces changements ».
    """
    boite = QWidget()
    layout = QVBoxLayout(boite)
    layout.setContentsMargins(0, 0, 0, 0)
    etiquette = QLabel(titre)
    etiquette.setStyleSheet("font-weight: bold;")

    entete = QHBoxLayout()
    entete.addWidget(etiquette)
    entete.addStretch(1)
    if fleche is not None:
        entete.addWidget(fleche)

    layout.addLayout(entete)
    layout.addWidget(vue)
    return boite
