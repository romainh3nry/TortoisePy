"""Résultat structuré des opérations — §7.6.

Aucune exception pygit2 ne remonte à l'UI : chaque opération retourne un
`OperationResult`. Le décorateur `guarded` centralise cette conversion,
pour qu'aucune opération ne puisse l'oublier.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import Callable

import pygit2


@dataclass(frozen=True)
class OperationResult:
    success: bool
    repository_changed: bool
    summary: str
    git_error: str | None = None

    @property
    def needs_refresh(self) -> bool:
        """L'affichage ne reflète plus le dépôt — nom explicite pour l'UI."""
        return self.repository_changed


def succeeded(summary: str, repository_changed: bool = True) -> OperationResult:
    """Opération réussie. Par défaut elle a modifié le dépôt ; les rares
    opérations en lecture (copier un hash) passent `False`."""
    return OperationResult(
        success=True,
        repository_changed=repository_changed,
        summary=summary,
        git_error=None,
    )


def failed(
    summary: str, git_error: str, repository_changed: bool = False
) -> OperationResult:
    """Opération échouée.

    `repository_changed` reste indépendant : un merge interrompu par un
    conflit a échoué mais laisse l'index modifié (§7.6).
    """
    return OperationResult(
        success=False,
        repository_changed=repository_changed,
        summary=summary,
        git_error=git_error,
    )


def guarded(summary: str, changed_on_error: bool = False) -> Callable:
    """Convertit toute exception en `OperationResult`.

    `changed_on_error=True` pour les opérations interactives (merge, rebase,
    cherry-pick), qui peuvent modifier le dépôt avant d'échouer.

    Le message de libgit2 est transmis tel quel, jamais reformulé (§9) :
    une paraphrase approximative nuirait à qui connaît Git.
    """

    def decorate(function: Callable[..., OperationResult]) -> Callable:
        @functools.wraps(function)
        def wrapper(*args, **kwargs) -> OperationResult:
            try:
                return function(*args, **kwargs)
            except pygit2.GitError as error:
                return failed(summary, str(error), changed_on_error)
            except Exception as error:
                # Volontairement large : lister les types attendus
                # (KeyError, ValueError, OSError…) laissait passer les
                # autres — une TypeError de pygit2 sur un mauvais argument
                # remontait jusqu'à l'UI, contre la règle de §7.6.
                # `Exception` n'attrape ni KeyboardInterrupt ni SystemExit,
                # qui doivent continuer d'interrompre le programme.
                return failed(
                    summary, f"{type(error).__name__}: {error}", changed_on_error
                )

        return wrapper

    return decorate
