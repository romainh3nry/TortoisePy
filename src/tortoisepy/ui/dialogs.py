"""Saisies, confirmations et messages d'erreur — §7.5, §9.

La décision de confirmer vit dans `confirmation_for`, une fonction pure :
elle dit s'il faut demander, avec quel texte et quelle gravité. Les widgets
ne font que l'afficher. Cela rend la règle testable sans interaction.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics, QGuiApplication


def copy_to_clipboard(text: str) -> None:
    """Met `text` dans le presse-papier.

    Partagée par les trois fenêtres qui copient quelque chose : le
    graphe, le détail d'un commit et les conflits. Elle vivait en
    méthode privée de `MainWindow`, donc inatteignable depuis les deux
    autres.

    Un presse-papier absent (environnement sans affichage) est ignoré en
    silence : l'action est un confort, et lever ici ferait échouer une
    opération par ailleurs réussie.
    """
    presse_papier = QGuiApplication.clipboard()
    if presse_papier is not None:
        presse_papier.setText(text)

from PySide6.QtWidgets import (
    QCheckBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
)

from tortoisepy.core.credentials import Credentials
from tortoisepy.core.results import OperationResult
from tortoisepy.core.state import RepositoryState

RESET_MODES = ("soft", "mixed", "hard")

_RESET_DESCRIPTIONS = {
    "soft": "move the branch, keep index and working tree",
    "mixed": "move the branch, reset index, keep working tree",
    "hard": "move the branch and DISCARD local changes",
}

_DIRTY_SENSITIVE = {"checkout_branch", "merge_branch", "cherry_pick"}
"""Opérations qui touchent l'arbre de travail : à confirmer s'il est sale."""


@dataclass(frozen=True)
class ConfirmationRequest:
    title: str
    message: str
    destructive: bool


def confirmation_for(
    action: str,
    target: str,
    state: RepositoryState,
    mode: str | None = None,
) -> ConfirmationRequest | None:
    """Faut-il confirmer cette action ? `None` si elle peut s'exécuter.

    Le message nomme toujours ce qui est en jeu (§7.5) : « confirmer ? »
    sans contexte ne permet pas de décider.
    """
    if action == "reset_to" and mode == "hard":
        return ConfirmationRequest(
            title="Reset — destructive",
            message=(
                f"git reset --hard: move "
                f"{state.head_branch or 'HEAD'} to {target}.\n\n"
                "Uncommitted changes will be lost for good, along with "
                "any commit no longer reachable from another branch."
            ),
            destructive=True,
        )

    if action == "abort_operation":
        # `abort_operation` fait `state_cleanup()` + `reset(HARD)` : tout
        # ce qui n'est pas commité disparaît. Le piège de la phase 11
        # était d'avoir posé `needs_confirmation` dans le menu sans
        # brancher ici — le drapeau ne protégeait rien.
        quoi = state.operation_in_progress or "the conflicts"
        return ConfirmationRequest(
            title=f"Abort {quoi} — destructive",
            message=(
                f"The working tree is reset to {state.head_branch or 'HEAD'}.\n\n"
                "Conflict resolutions and uncommitted changes to tracked "
                "files are discarded, and cannot be recovered.\n\n"
                "Untracked files are left alone."
            ),
            destructive=True,
        )

    if action == "drop_stash":
        return ConfirmationRequest(
            title="Drop stash — destructive",
            message=(
                f"git stash drop {target}\n\n"
                "The stashed changes are deleted without being restored, "
                "and cannot be recovered."
            ),
            destructive=True,
        )

    if action == "delete_remote_branch":
        return ConfirmationRequest(
            title="Delete remote branch — destructive",
            message=(
                # `target` vaut « origin/feature » : on le sépare pour
                # afficher la commande réellement exécutée, et non une
                # forme approchante que l'utilisateur ne retrouverait pas.
                f"git push {target.split('/', 1)[0]} --delete "
                f"{target.split('/', 1)[-1]}\n\n"
                "The branch is removed from the shared server. Others "
                "will lose it on their next fetch, and you cannot undo "
                "this on your own. Any local branch of the same name is "
                "kept."
            ),
            destructive=True,
        )

    if action == "delete_branch":
        return ConfirmationRequest(
            title="Delete branch",
            message=(
                f"git branch -d {target}\n\n"
                "Commits referenced only by this branch will become "
                "unreachable."
            ),
            destructive=True,
        )

    if action == "revert_commit":
        return ConfirmationRequest(
            title="Revert commit",
            message=(
                f"git revert {target}\n\n"
                "History is not rewritten: a new commit undoes the "
                "changes."
            ),
            destructive=False,
        )

    dirty = state.has_unstaged_changes or state.has_staged_changes
    if dirty and action in _DIRTY_SENSITIVE:
        return ConfirmationRequest(
            title="Uncommitted changes",
            message=(
                "The working tree has uncommitted changes.\n\n"
                f"Running this operation on {target} may overwrite them, "
                "or fail outright."
            ),
            destructive=False,
        )

    return None


def error_text(result: OperationResult) -> tuple[str, str]:
    """Titre et corps d'un dialogue d'erreur — §9, trois parties.

    Le message de libgit2 est transmis mot pour mot : une reformulation
    approximative nuirait à qui connaît Git.
    """
    title = "Operation failed"
    body = f"{result.summary} did not complete."

    if result.git_error:
        body += f"\n\nGit says:\n{result.git_error}"

    return title, body


def ask_name(parent, title: str, label: str, default: str = "") -> str | None:
    """Demande un nom. `None` si l'utilisateur annule."""
    name, accepted = QInputDialog.getText(parent, title, label, text=default)
    if not accepted:
        return None
    name = name.strip()
    return name or None


def _largeur_pour(noms, widget) -> int:
    """Largeur nécessaire pour afficher le plus long de ces noms.

    Bornée : un nom pathologique ne doit pas produire une fenêtre plus
    large que l'écran. Plancher pour qu'un dépôt aux noms courts garde
    un champ de taille normale.
    """
    metriques = QFontMetrics(widget.font())
    requis = max(
        (metriques.horizontalAdvance(nom) for nom in noms), default=0
    )
    # La marge couvre le cadre, le padding interne et le curseur.
    return max(320, min(requis + 40, 900))


def _branch_completer(choices) -> QCompleter:
    """Complète sur n'importe quelle partie du nom.

    `MatchContains` plutôt que le préfixe : saisir « main » doit proposer
    `origin/main` autant que `main`, sinon les branches distantes sont
    introuvables sans taper « origin/ » d'abord.
    """
    noms = list(choices)
    completer = QCompleter(noms)
    completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    completer.setFilterMode(Qt.MatchFlag.MatchContains)
    completer.setCompletionMode(
        QCompleter.CompletionMode.PopupCompletion
    )

    # Le popup se cale par défaut sur la largeur du CHAMP, pas sur celle
    # de la fenêtre : signalé par l'utilisateur, la liste proposait
    # « CRM-3933_rate_li… » et deux fois « origin/CRM-3933_… », rendant
    # indistinguables des branches au préfixe commun. Choisir la mauvaise
    # cible de rebase n'est pas une erreur anodine.
    #
    # La largeur suit le CONTENU : une valeur fixe généreuse règlerait ce
    # dépôt-ci et donnerait une liste absurde sur un dépôt aux noms courts.
    if noms:
        popup = completer.popup()
        metriques = QFontMetrics(popup.font())
        requis = max(metriques.horizontalAdvance(nom) for nom in noms)
        # La marge couvre le cadre, le padding et l'ascenseur éventuel.
        popup.setMinimumWidth(requis + 40)

    return completer


_LIBELLE_BRANCHE = "Branch:"
_LIBELLE_CIBLE = "Onto:"
"""Libellés des deux champs. Nommés pour qu'un test les fixe."""


class RebaseDialog(QDialog):
    """Deux champs : la branche rejouée, et celle par-dessus laquelle.

    Le besoin vient d'un piège d'interface signalé par l'utilisateur :
    cliquer droit sur une branche puis « Rebase… » rejouait la branche
    **courante**, pas celle qu'on avait cliquée. Rien dans le geste ne le
    laissait deviner.
    """

    def __init__(
        self,
        parent,
        current_branch: str | None,
        local_branches,
        targets,
    ):
        super().__init__(parent)
        self.setWindowTitle("Rebase")

        self._current = current_branch
        # Rejouer une branche distante n'a pas de sens : elle n'est pas à
        # nous. La cible, elle, peut en être une (D14, phase 9).
        self._locales = list(local_branches)
        self._cibles = list(targets)

        self._replay = QLineEdit(current_branch or "")
        self._replay.setCompleter(_branch_completer(self._locales))
        self._replay.textChanged.connect(self._on_change)
        # Le curseur se place en fin de texte, et la vue le suit : le
        # champ affichait « 935-2fa-email-login » au lieu de
        # « feature/CRM-3935-2fa-email-login » (signalé, capture à
        # l'appui). C'est le DÉBUT du nom qui l'identifie — le préfixe
        # `feature/` ou `origin/` — donc on ramène la vue au début.
        self._replay.setCursorPosition(0)

        self._target = QLineEdit()
        self._target.setCompleter(_branch_completer(self._cibles))
        self._target.textChanged.connect(self._on_change)

        # Un nom de branche entier doit tenir sans défiler : sinon on ne
        # relit pas ce qu'on a saisi avant de valider un rebase.
        for champ in (self._replay, self._target):
            champ.setMinimumWidth(_largeur_pour(
                self._locales + self._cibles, champ
            ))

        # N'apparaît que si la branche rejouée n'est pas la courante :
        # toujours visible, il deviendrait invisible.
        self._warning = QLabel()
        self._warning.setWordWrap(True)
        self._warning.setVisible(False)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.button(
            QDialogButtonBox.StandardButton.Ok
        ).setText("Rebase")
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)

        # Largeur de DÉPART, pas un minimum : sans elle Qt réduisait la
        # fenêtre au plus petit de ses champs (~300 px mesurés), et les
        # noms longs étaient tronqués avant même d'ouvrir la liste.
        # `resize` plutôt que `setMinimumWidth` pour que la fenêtre reste
        # rétrécissable sur un petit écran.
        # `sizeHint` tient compte des largeurs minimales posées
        # ci-dessus ; le plancher couvre le cas d'un dépôt aux noms
        # courts, où une fenêtre minuscule paraîtrait cassée.
        self.resize(max(640, self.sizeHint().width()), self.sizeHint().height())

        form = QFormLayout(self)
        # « Branch » plutôt que « Replay » (demandé par l'utilisateur) :
        # « Replay » décrivait bien le geste — un rebase rejoue des
        # commits — mais le mot n'existe pas dans la CLI git, et
        # TortoiseGit, dont cette application est un clone, dit
        # « Branch ». « Onto » est gardé : c'est le mot de git
        # (`git rebase --onto`), et « Upstream » désignerait d'habitude
        # la branche de suivi distante, pas la cible d'un rebase.
        form.addRow(_LIBELLE_BRANCHE, self._replay)
        form.addRow(_LIBELLE_CIBLE, self._target)
        form.addRow(self._warning)
        form.addRow(self._buttons)

        self._on_change()

    def showEvent(self, event) -> None:
        """Aligne les listes sur leurs champs au moment de l'affichage.

        Le complèteur est construit avant que le champ ait sa largeur
        finale : la régler dans `_branch_completer` garantit que les noms
        longs tiennent, mais laisse une liste plus étroite que son champ
        quand les noms sont courts (mesuré : 228 px sous un champ de
        488 px), ce qui est bancal.

        Ici, la mise en page est faite et les largeurs sont connues.
        """
        super().showEvent(event)
        for champ in (self._replay, self._target):
            completeur = champ.completer()
            if completeur is None:
                continue
            popup = completeur.popup()
            popup.setMinimumWidth(
                max(popup.minimumWidth(), champ.width())
            )

    # --- lecture -------------------------------------------------------

    def replayed(self) -> str | None:
        """Branche à rejouer, ou `None` si la saisie n'en désigne aucune."""
        saisie = self._replay.text().strip()
        return saisie if saisie in set(self._locales) else None

    def target(self) -> str | None:
        saisie = self._target.text().strip()
        return saisie if saisie in set(self._cibles) else None

    def field_labels(self) -> tuple[str, str]:
        """Les deux libellés, dans l'ordre d'affichage."""
        return (_LIBELLE_BRANCHE, _LIBELLE_CIBLE)

    def replay_field(self) -> QLineEdit:
        """Le champ de la branche rejouée (libellé « Branch »).

        Le nom interne reste « replay » : il dit ce que la branche SUBIT
        — elle est rejouée — là où le libellé dit ce qu'elle EST.
        """
        return self._replay

    def target_field(self) -> QLineEdit:
        """Le champ « Onto »."""
        return self._target

    def replay_choices(self) -> tuple[str, ...]:
        return tuple(self._locales)

    def target_choices(self) -> tuple[str, ...]:
        return tuple(self._cibles)

    def switch_warning(self) -> str:
        """Avertissement affiché, ou chaîne vide s'il n'y a pas lieu.

        Lu sur le texte et non sur `isVisible()` : un widget d'une
        fenêtre jamais affichée n'est pas « visible » pour Qt, ce qui
        rendrait la méthode intestable — et masquerait un vrai défaut
        derrière une limite de l'environnement.
        """
        return self._warning.text()

    def is_valid(self) -> bool:
        rejouee, cible = self.replayed(), self.target()
        return bool(rejouee) and bool(cible) and rejouee != cible

    # --- écriture ------------------------------------------------------

    def set_replayed(self, name: str) -> None:
        self._replay.setText(name)

    def set_target(self, name: str) -> None:
        self._target.setText(name)

    # --- interne -------------------------------------------------------

    def _on_change(self) -> None:
        rejouee = self.replayed()

        montrer = rejouee is not None and rejouee != self._current
        # Vérifié : `git rebase main feature` bascule aussi sur
        # `feature`. On le dit à l'avance plutôt que de surprendre.
        self._warning.setText(
            f"⚠ You will end up on « {rejouee} » after the rebase."
            if montrer
            else ""
        )
        self._warning.setVisible(montrer)

        self._buttons.button(
            QDialogButtonBox.StandardButton.Ok
        ).setEnabled(self.is_valid())


def ask_branch(
    parent, title: str, label: str, choices, default: str = ""
) -> str | None:
    """Demande une branche, avec autocomplétion. `None` si annulé.

    Refuse une saisie qui ne correspond à aucune branche connue : laisser
    passer un nom libre produirait une erreur de libgit2 que l'utilisateur
    ne saurait pas interpréter.
    """
    # Figé une fois : `choices` peut être un générateur, et il est lu
    # deux fois — pour l'autocomplétion puis pour la vérification. Épuisé
    # par la première lecture, il ferait rejeter jusqu'aux branches
    # valides, silencieusement, comme si l'utilisateur avait annulé.
    connues = list(choices)

    dialogue = QInputDialog(parent)
    dialogue.setWindowTitle(title)
    dialogue.setLabelText(label)
    dialogue.setTextValue(default)
    dialogue.setInputMode(QInputDialog.InputMode.TextInput)

    champ = dialogue.findChild(QLineEdit)
    if champ is not None:
        champ.setCompleter(_branch_completer(connues))

    if dialogue.exec() != QInputDialog.DialogCode.Accepted:
        return None

    saisie = dialogue.textValue().strip()
    if saisie not in set(connues):
        return None
    return saisie


def ask_reset_mode(parent) -> str | None:
    """Demande le mode de réinitialisation. `None` si annulé."""
    labels = [f"{mode} — {_RESET_DESCRIPTIONS[mode]}" for mode in RESET_MODES]
    choice, accepted = QInputDialog.getItem(
        parent, "Reset mode", "Mode:", labels, 1, False
    )
    if not accepted:
        return None
    return choice.split(" — ", 1)[0]


def ask_pull_strategy(parent, state) -> str | None:
    """Merge ou rebase ? `None` si l'utilisateur annule (§5).

    Posée seulement quand les deux côtés ont avancé. Le rebase est le seul
    des deux à réécrire des commits déjà faits : on le dit, plutôt que de
    laisser l'utilisateur le découvrir après coup.
    """
    choices = [
        "Merge — keep both histories, add a merge commit",
        "Rebase — replay your commits on top (rewrites them)",
    ]
    choice, accepted = QInputDialog.getItem(
        parent,
        "Pull",
        (
            f"{state.branch} and {state.remote_name}/{state.branch} have "
            f"both moved on\n"
            f"({state.incoming} incoming, {state.outgoing} local).\n\n"
            "How should they be combined?"
        ),
        choices,
        0,
        False,
    )
    if not accepted:
        return None
    return "merge" if choice.startswith("Merge") else "rebase"


def ask_credentials(parent, url: str) -> tuple[Credentials | None, bool]:
    """Demande identifiant et mot de passe. `(None, False)` si annulé.

    Le second élément dit si l'utilisateur veut les mémoriser — c'est Git
    qui les rangera (trousseau macOS, Credential Manager Windows…),
    jamais tortoisePy : aucun secret n'est écrit par cette application.

    Appelé seulement quand `git credential` ne connaît rien pour cette
    URL ; le cas courant ne montre aucune fenêtre.
    """
    dialog = QDialog(parent)
    dialog.setWindowTitle("Authentication required")

    user = QLineEdit()
    password = QLineEdit()
    # `Password` masque la saisie ; sans cela le mot de passe s'afficherait
    # en clair à l'écran.
    password.setEchoMode(QLineEdit.EchoMode.Password)
    remember = QCheckBox("Remember (stored by Git, not by tortoisePy)")
    remember.setChecked(True)

    layout = QFormLayout(dialog)
    layout.addRow(QLabel(f"Sign in to {url}"))
    layout.addRow("Username:", user)
    layout.addRow("Password / token:", password)
    layout.addRow(remember)

    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok
        | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addRow(buttons)

    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None, False

    name, secret = user.text().strip(), password.text()
    if not name or not secret:
        return None, False
    return Credentials(username=name, password=secret), remember.isChecked()


def confirm(parent, request: ConfirmationRequest) -> bool:
    """Affiche la confirmation. Vrai si l'utilisateur accepte.

    Le bouton par défaut est « Annuler » : sur une action destructrice,
    une validation réflexe ne doit pas suffire.
    """
    box = QMessageBox(parent)
    box.setIcon(
        QMessageBox.Icon.Warning
        if request.destructive
        else QMessageBox.Icon.Question
    )
    box.setWindowTitle(request.title)
    box.setText(request.title)
    box.setInformativeText(request.message)
    box.setStandardButtons(
        QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel
    )
    box.setDefaultButton(QMessageBox.StandardButton.Cancel)
    return box.exec() == QMessageBox.StandardButton.Ok


def show_error(parent, result: OperationResult) -> None:
    title, body = error_text(result)
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle(title)
    box.setText(title)
    box.setInformativeText(body)
    box.exec()


def show_message(parent, title: str, message: str) -> None:
    QMessageBox.information(parent, title, message)
