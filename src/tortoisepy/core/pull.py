"""Récupérer les changements distants — §3 à §5 de la spec phase 8.

Trois situations, distinguées par `merge_analysis` : rien à faire, simple
avance, ou divergence. Seule la troisième pose une question à
l'utilisateur ; c'est `ui/` qui la pose, pas ce module.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pygit2
from pygit2.enums import MergeAnalysis, ResetMode

from tortoisepy.core.results import OperationResult, failed, guarded, succeeded


class PullKind(Enum):
    UP_TO_DATE = "up_to_date"
    FAST_FORWARD = "fast_forward"
    DIVERGED = "diverged"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class PullState:
    kind: PullKind
    branch: str | None = None
    remote_name: str | None = None
    incoming: int = 0
    """Commits présents en amont et pas ici."""

    outgoing: int = 0
    """Commits présents ici et pas en amont — non nul en cas de divergence."""

    reason: str = ""
    """Pourquoi on ne peut pas récupérer ; vide quand on peut."""


def analyse_pull(repo: pygit2.Repository) -> PullState:
    """Que se passerait-il si on récupérait maintenant ?

    **Purement descriptif** : n'écrit rien, ne fetch pas. L'appelant fetch
    d'abord, sans quoi l'analyse porterait sur une ref périmée (§3).
    """
    branch = _current_branch(repo)
    if branch is None:
        return PullState(PullKind.UNAVAILABLE, reason="no branch checked out")

    upstream = branch.upstream
    if upstream is None:
        return PullState(
            PullKind.UNAVAILABLE,
            branch=branch.branch_name,
            reason="branch has no upstream",
        )

    try:
        analysis, _ = repo.merge_analysis(upstream.target)
        ahead, behind = repo.ahead_behind(branch.target, upstream.target)
    except (pygit2.GitError, KeyError, ValueError):
        return PullState(
            PullKind.UNAVAILABLE,
            branch=branch.branch_name,
            reason="cannot compare with the upstream branch",
        )

    common = {
        "branch": branch.branch_name,
        "remote_name": upstream.remote_name,
        "incoming": behind,
        "outgoing": ahead,
    }

    if analysis & MergeAnalysis.UP_TO_DATE:
        return PullState(PullKind.UP_TO_DATE, **common)
    if analysis & MergeAnalysis.FASTFORWARD:
        return PullState(PullKind.FAST_FORWARD, **common)
    return PullState(PullKind.DIVERGED, **common)


@guarded("Pull")
def pull_fast_forward(repo: pygit2.Repository) -> OperationResult:
    """Amène la branche au niveau de l'amont, sans commit de fusion.

    Vérifié : positionner la ref puis remettre l'arbre à jour suffit — la
    branche rejoint la distante et l'arbre reste propre.
    """
    state = analyse_pull(repo)
    if state.kind is PullKind.UNAVAILABLE:
        return failed("Pull", state.reason)
    if state.kind is PullKind.UP_TO_DATE:
        return succeeded("Already up to date", repository_changed=False)

    in_the_way = _operation_in_the_way(repo)
    if in_the_way is not None:
        return failed("Pull", in_the_way, repository_changed=False)

    blocking = _uncommitted_changes(repo)
    if blocking:
        # Un fast-forward écrase l'arbre : refuser AVANT d'y toucher.
        return failed(
            "Pull",
            f"uncommitted changes would be overwritten ({blocking})",
            repository_changed=False,
        )

    branch = _current_branch(repo)
    target = branch.upstream.target

    reference = repo.lookup_reference(repo.head.name)
    reference.set_target(target)
    repo.checkout_tree(repo.get(target))
    repo.reset(target, ResetMode.HARD)

    plural = "" if state.incoming == 1 else "s"
    return succeeded(
        f"Pulled {state.incoming} commit{plural} from {state.remote_name}"
    )


@guarded("Pull", changed_on_error=True)
def pull_merge(repo: pygit2.Repository) -> OperationResult:
    """Fusionne l'amont dans la branche courante.

    Un conflit n'est **pas** une erreur du programme : il est rapporté comme
    un échec pour que l'interface ouvre la fenêtre de résolution, et le
    dépôt reste en état de fusion, prêt à être résolu ou abandonné.
    """
    state = analyse_pull(repo)
    if state.kind is PullKind.UNAVAILABLE:
        return failed("Pull", state.reason, repository_changed=False)
    if state.kind is PullKind.UP_TO_DATE:
        return succeeded("Already up to date", repository_changed=False)

    in_the_way = _operation_in_the_way(repo)
    if in_the_way is not None:
        return failed("Pull", in_the_way, repository_changed=False)

    blocking = _uncommitted_changes(repo)
    if blocking:
        return failed(
            "Pull",
            f"uncommitted changes would be overwritten ({blocking})",
            repository_changed=False,
        )

    branch = _current_branch(repo)
    target = branch.upstream.target
    repo.merge(target)

    if repo.index.conflicts is not None:
        paths = sorted(
            (ours or theirs).path
            for _, ours, theirs in repo.index.conflicts
            if (ours or theirs) is not None
        )
        return failed("Pull", f"conflicts in: {', '.join(paths)}")

    return _finish_merge(repo, target, state)


@guarded("Pull", changed_on_error=True)
def pull_rebase(repo: pygit2.Repository) -> OperationResult:
    """Rejoue les commits locaux par-dessus l'amont.

    **Réécrit les commits locaux** : l'interface l'annonce avant d'appeler
    (§5). Comme pour la fusion, un conflit est rapporté pour résolution.

    Vérifié : le rebase se démarre avec `rebase_init` — `init_rebase`
    n'existe pas. Vérifié aussi sur pygit2 1.20.1 installé : `Rebase.commit`
    prend bien `committer` (le brief avait raison sur ce point), mais
    `Rebase.finish` prend `signature`, pas `committer` — un `TypeError` sinon,
    qui laisse HEAD détachée en pleine opération.

    En cas de conflit, on **n'abandonne pas l'utilisateur en plein rebase** :
    `abort_operation` (générique, `reset(HARD, head.target)`) ne sait pas
    rattacher une HEAD détachée par un rebase en cours — vérifié : elle reste
    détachée après son appel. Seul `Rebase.abort()` sait le faire proprement.
    Comme la fenêtre de résolution de conflit de la phase 4 est bâtie autour
    du flux de fusion, pas du rebase, on choisit d'abandonner nous-mêmes le
    rebase ici et de renvoyer un message qui l'explique, plutôt que de
    laisser un état que rien dans l'appli ne peut récupérer.
    """
    state = analyse_pull(repo)
    if state.kind is PullKind.UNAVAILABLE:
        return failed("Pull", state.reason, repository_changed=False)
    if state.kind is PullKind.UP_TO_DATE:
        return succeeded("Already up to date", repository_changed=False)

    in_the_way = _operation_in_the_way(repo)
    if in_the_way is not None:
        return failed("Pull", in_the_way, repository_changed=False)

    blocking = _uncommitted_changes(repo)
    if blocking:
        return failed(
            "Pull",
            f"uncommitted changes would be overwritten ({blocking})",
            repository_changed=False,
        )

    branch = _current_branch(repo)
    onto = repo.lookup_reference(branch.upstream.name)
    rebase = repo.rebase_init(
        branch=repo.lookup_reference(repo.head.name),
        upstream=None,
        onto=onto,
    )

    signature = _signature(repo)

    # Tout échec sous ce `try` doit défaire le rebase, pas seulement un
    # conflit : une exception qui s'échapperait laisserait la HEAD détachée
    # au milieu du rejeu, et `abort_operation` — que l'interface appelle
    # génériquement — ne sait pas rattacher une branche. Vérifié : sans
    # cette garde, une panne pendant `commit()` laisse `## HEAD (no branch)`.
    try:
        for _ in rebase:
            if repo.index.conflicts is not None:
                paths = sorted(
                    (ours or theirs).path
                    for _, ours, theirs in repo.index.conflicts
                    if (ours or theirs) is not None
                )
                rebase.abort()
                return failed(
                    "Pull",
                    f"conflicts in: {', '.join(paths)} "
                    "(rebase rolled back, branch restored — try merge instead)",
                    repository_changed=False,
                )
            rebase.commit(committer=signature)

        rebase.finish(signature)
    except Exception:
        # Remettre la branche d'aplomb AVANT de laisser l'erreur remonter :
        # `guarded` la transformera en `OperationResult`, mais lui ne peut
        # pas réparer le dépôt.
        try:
            rebase.abort()
        except (pygit2.GitError, ValueError):
            pass  # rien de mieux à tenter ; l'erreur d'origine prime
        raise

    plural = "" if state.incoming == 1 else "s"
    return succeeded(
        f"Rebased onto {state.incoming} commit{plural} from "
        f"{state.remote_name}"
    )


def _finish_merge(repo, target, state) -> OperationResult:
    """Crée le commit de fusion à deux parents et nettoie l'état.

    `state_cleanup()` est indispensable : sans lui, `MERGE_HEAD` traîne et
    l'interface croit la fusion toujours en cours (leçon de la phase 7).
    """
    signature = _signature(repo)
    tree = repo.index.write_tree()
    repo.create_commit(
        "HEAD",
        signature,
        signature,
        f"Merge branch '{state.remote_name}/{state.branch}'",
        tree,
        [repo.head.target, target],
    )
    repo.state_cleanup()

    plural = "" if state.incoming == 1 else "s"
    return succeeded(
        f"Merged {state.incoming} commit{plural} from {state.remote_name}"
    )


def _operation_in_the_way(repo: pygit2.Repository) -> str | None:
    """Une opération inachevée empêche-t-elle de récupérer ? Sinon `None`.

    Refuser **avant** de toucher au dépôt est vital : relancer un pull
    pendant un conflit est le geste le plus naturel, et libgit2 efface
    `MERGE_HEAD` avant de rejeter la fusion. Les conflits restent alors
    sans `MERGE_HEAD`, donc `conclude_merge` ne peut plus conclure et
    `abort_operation` répond « no operation in progress » : plus aucune
    sortie. Vérifié — c'est exactement le « rester coincé » que cette
    phase existe pour empêcher.
    """
    if repo.index.conflicts is not None:
        return (
            "resolve the conflicts first, or abort the merge "
            "(a pull now would leave the repository unrecoverable)"
        )
    if repo.state() != pygit2.enums.RepositoryState.NONE:
        return "finish or abort the operation in progress first"
    return None


def _uncommitted_changes(repo: pygit2.Repository) -> str:
    """Résumé des modifications non commitées, vide s'il n'y en a pas.

    Les fichiers non suivis ne gênent pas une fusion : seuls comptent les
    fichiers suivis modifiés ou indexés.
    """
    from pygit2.enums import FileStatus

    blocking = FileStatus.WT_MODIFIED | FileStatus.WT_DELETED
    blocking |= FileStatus.INDEX_MODIFIED | FileStatus.INDEX_NEW
    blocking |= FileStatus.INDEX_DELETED
    # `CONFLICTED` (0x8000) doit en faire partie : sans lui, un dépôt en
    # plein conflit se lit comme « propre » et un second pull passe la
    # garde. Vérifié : libgit2 efface alors `MERGE_HEAD` avant d'échouer,
    # les conflits restent, et `abort_operation` répond « no operation in
    # progress » — plus aucune sortie.
    blocking |= FileStatus.CONFLICTED

    try:
        touched = [p for p, code in repo.status().items() if code & blocking]
    except pygit2.GitError:
        return ""
    return ", ".join(sorted(touched)[:3])


def _current_branch(repo: pygit2.Repository):
    if repo.head_is_unborn or repo.head_is_detached:
        return None
    try:
        return repo.branches[repo.head.shorthand]
    except (KeyError, pygit2.GitError):
        return None


def _signature(repo: pygit2.Repository) -> pygit2.Signature:
    try:
        return repo.default_signature
    except (KeyError, ValueError):
        return pygit2.Signature("tortoisePy", "tortoisepy@localhost")
