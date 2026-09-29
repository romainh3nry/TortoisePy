"""Saisies, confirmations et messages d'erreur — §7.5, §9.

La décision de confirmer vit dans `confirmation_for`, une fonction pure :
elle dit s'il faut demander, avec quel texte et quelle gravité. Les widgets
ne font que l'afficher. Cela rend la règle testable sans interaction.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtWidgets import (
    QCheckBox,
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
