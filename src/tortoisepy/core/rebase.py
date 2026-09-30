"""Rebaser la branche courante sur une autre — phase 9.

Un rebase rejoue les commits un par un : il peut s'interrompre sur un
conflit, être repris, ou abandonné. Contrairement au merge, l'opération
survit entre deux processus — c'est ce qui permet à la fenêtre de
conflits de la piloter.

Sans Qt : `ui/` décide comment présenter tout cela.
"""

from __future__ import annotations

from dataclasses import dataclass

import pygit2
from pygit2.enums import FileStatus, RepositoryState

from tortoisepy.core.results import OperationResult, failed, guarded, succeeded


@dataclass(frozen=True)
class RebaseState:
    in_progress: bool = False
    branch: str | None = None
    """Branche rebasée, telle qu'elle s'appelait au départ."""

    onto_label: str | None = None
    """Nom lisible de la cible — ce que l'interface doit afficher.

    Indispensable : pendant un rebase, `ours` désigne la **cible** et
    `theirs` le commit rejoué, l'inverse du merge. Sans ce nom, les
    boutons ne peuvent pas dire la vérité à l'utilisateur.
    """

    conflicted: tuple[str, ...] = ()


def rebase_targets(repo: pygit2.Repository) -> tuple[str, ...]:
    """Branches sur lesquelles on peut rebaser, triées.

    Locales **et** distantes (D14) : `git rebase origin/main` est courant,
    et imposer un checkout préalable serait une gêne inutile.
    """
    courante = _current_branch_name(repo)

    noms: set[str] = set()
    try:
        noms.update(repo.branches.local)
        noms.update(repo.branches.remote)
    except pygit2.GitError:
        return ()

    # Se rebaser sur soi-même n'a pas de sens.
    noms.discard(courante)
    # `origin/HEAD` est un alias symbolique, pas une cible utile — mais
    # seul CE nom précis doit sauter. `n.endswith("/HEAD")` seul avalerait
    # aussi une vraie branche locale nommée par exemple `feature/HEAD`
    # (vérifié) ; ne retirer que `<remote>/HEAD` pour une remote connue.
    try:
        remotes = set(repo.remotes.names())
    except pygit2.GitError:
        remotes = set()
    noms = {
        n for n in noms
        if not (n.endswith("/HEAD") and n.rsplit("/HEAD", 1)[0] in remotes)
    }
    return tuple(sorted(noms))


def rebase_state(repo: pygit2.Repository) -> RebaseState:
    """Y a-t-il un rebase en cours, et sur quoi ?

    Relu depuis le disque à chaque appel : l'interface vit dans un autre
    contexte que celui qui a démarré le rebase (vérifié).
    """
    if repo.state() not in _REBASE_STATES:
        return RebaseState()

    try:
        rebase = repo.rebase_open()
    except (pygit2.GitError, KeyError, ValueError):
        return RebaseState(in_progress=True)

    conflits: tuple[str, ...] = ()
    if repo.index.conflicts is not None:
        conflits = tuple(
            sorted(
                (ours or theirs).path
                for _, ours, theirs in repo.index.conflicts
                if (ours or theirs) is not None
            )
        )

    return RebaseState(
        in_progress=True,
        branch=_short(rebase.orig_head_name),
        onto_label=_label_for(repo, rebase.onto_id),
        conflicted=conflits,
    )


@guarded("Rebase", changed_on_error=True)
def start_rebase(
    repo: pygit2.Repository, onto: str, branch: str | None = None
) -> OperationResult:
    """Rejoue `branch` par-dessus `onto`. Par défaut, la branche courante.

    **Rejouer une autre branche bascule dessus** — vérifié, et
    `git rebase main feature` fait exactement pareil. L'interface le dit
    à l'avance (D46) plutôt que de le contredire : revenir sur la branche
    de départ s'écarterait de git et ajouterait une écriture au dépôt.

    Un conflit n'est **pas** annulé (D13, qui révise la phase 8) : le
    rebase reste en cours pour être résolu, et `abort_rebase` offre la
    sortie de secours.
    """
    if repo.state() in _REBASE_STATES:
        # HEAD est détachée pendant un rebase : sans cette garde, le test
        # suivant tombait sur `_current_branch_name` → None et répondait
        # « no branch checked out », un message qui ne dit pas ce qui se
        # passe vraiment et n'oriente pas vers `continue_rebase`/`abort_rebase`.
        return failed(
            "Rebase", "a rebase is already in progress",
            repository_changed=False,
        )

    courante = _current_branch_name(repo)
    rejouee = branch or courante
    if rejouee is None:
        return failed(
            "Rebase", "no branch checked out", repository_changed=False
        )
    if onto == rejouee:
        return failed(
            "Rebase", f"'{onto}' is the branch being rebased",
            repository_changed=False,
        )

    a_rejouer = repo.branches.local.get(rejouee) if branch else None
    if branch and a_rejouer is None:
        return failed(
            "Rebase", f"branch '{branch}' not found", repository_changed=False
        )

    reference = _reference_for(repo, onto)
    if reference is None:
        return failed(
            "Rebase", f"branch '{onto}' not found", repository_changed=False
        )

    sale = _uncommitted(repo)
    if sale:
        # Refuser AVANT de toucher au dépôt : un rebase écrase l'arbre.
        return failed(
            "Rebase",
            f"uncommitted changes would be overwritten ({sale})",
            repository_changed=False,
        )

    rebase = repo.rebase_init(
        # `a_rejouer` quand l'utilisateur a désigné une autre branche ;
        # la ref de HEAD sinon, comme depuis la phase 9.
        branch=a_rejouer if a_rejouer is not None else repo.lookup_reference(repo.head.name),
        upstream=None,
        onto=reference,
    )
    return _run(repo, rebase, onto, depart=0)


_INDICE_INTERACTIF = "interactive rebase is not supported"

# Message commun aux deux sorties : un rebase lancé au terminal ne nous
# appartient pas, et le dire est plus utile que de le faire croire cassé.
_LANCE_PAR_GIT = (
    "this rebase was started by git itself and cannot be continued here "
    "(libgit2 does not support the interactive backend); use "
    "'git rebase --continue' or 'git rebase --abort' in a terminal"
)


def _echec_ouverture(erreur: Exception) -> OperationResult:
    """Traduit un `rebase_open()` en échec — deux causes, deux messages.

    Depuis git 2.26 le backend par défaut est « merge/interactive », donc
    `.git/rebase-merge` porte un fichier `interactive` que libgit2 refuse
    d'ouvrir. **Rien n'est abîmé** : c'est le cas normal d'un rebase lancé
    au terminal. Vérifié sur git 2.50.1. Lui répondre que ses métadonnées
    sont endommagées serait une fausse accusation, qui pousserait à des
    réparations destructrices.
    """
    if _INDICE_INTERACTIF in str(erreur).lower():
        return failed("Rebase", _LANCE_PAR_GIT, repository_changed=False)
    return failed(
        "Rebase",
        "rebase metadata is damaged; run 'git rebase --abort' in a terminal",
        repository_changed=True,
    )


@guarded("Rebase", changed_on_error=True)
def continue_rebase(repo: pygit2.Repository) -> OperationResult:
    """Poursuit après résolution. Refuse s'il reste un conflit."""
    if repo.state() not in _REBASE_STATES:
        return failed(
            "Rebase", "no rebase in progress", repository_changed=False
        )

    # Avant de parler de conflits, vérifier qu'on peut seulement ouvrir ce
    # rebase : celui lancé au terminal utilise le backend interactif, que
    # libgit2 refuse. Sans ce contrôle, l'utilisateur recevait « unresolved
    # conflicts remain » puis, après résolution, un autre message encore —
    # sans jamais apprendre la vraie raison.
    try:
        rebase = repo.rebase_open()
    except (pygit2.GitError, KeyError, ValueError, OSError) as erreur:
        return _echec_ouverture(erreur)

    if repo.index.conflicts is not None:
        noms = ", ".join(
            sorted(
                (ours or theirs).path
                for _, ours, theirs in repo.index.conflicts
                if (ours or theirs) is not None
            )
        )
        return failed("Rebase", f"unresolved conflicts remain: {noms}")

    etiquette = _label_for(repo, rebase.onto_id)

    # L'étape courante est résolue : la valider avant de poursuivre. Ce
    # commit compte pour de vrai (sauf s'il est devenu vide) : sans le
    # transmettre à `_run`, le message final annoncerait « 0 commit »
    # alors qu'un commit a bien été rejoué.
    signature = _signature(repo)
    deja_rejoue = 0
    try:
        if rebase.commit(committer=signature) is not None:
            deja_rejoue = 1
    except pygit2.GitError:
        # Rien à commiter : le patch était déjà appliqué en amont.
        pass

    return _run(repo, rebase, etiquette, depart=deja_rejoue)


@guarded("Rebase", changed_on_error=True)
def abort_rebase(repo: pygit2.Repository) -> OperationResult:
    """Restaure la branche dans son état d'avant le rebase.

    **`Rebase.abort()`, pas `abort_operation`** : ce dernier fait
    `state_cleanup()` + `reset(HARD)`, ce qui sur la HEAD détachée d'un
    rebase la remet sur elle-même sans rattacher la branche. Le défaut
    avait été trouvé en phase 8 ; vérifié ici que `Rebase.abort()`
    restaure l'état, la branche et le commit d'origine.
    """
    if repo.state() not in _REBASE_STATES:
        return failed(
            "Rebase", "no rebase in progress", repository_changed=False
        )

    try:
        repo.rebase_open().abort()
    except (pygit2.GitError, KeyError, ValueError, OSError) as erreur:
        # Deux causes distinctes, et une seule est un vrai dégât :
        # soit le rebase vient de `git` (backend interactif, cas normal),
        # soit `rebase-merge` est réellement illisible — et alors même
        # `git rebase --abort` échoue (vérifié en phase 9).
        return _echec_ouverture(erreur)
    return succeeded("Rebase aborted, branch restored")


def _run(repo, rebase, etiquette, depart: int = 0) -> OperationResult:
    """Déroule les opérations restantes jusqu'au conflit ou à la fin.

    `depart` : commits déjà rejoués avant cet appel (le commit de reprise
    de `continue_rebase`), à inclure dans le compte final.
    """
    signature = _signature(repo)
    rejoues = depart

    try:
        for _ in rebase:
            if repo.index.conflicts is not None:
                noms = ", ".join(
                    sorted(
                        (ours or theirs).path
                        for _, ours, theirs in repo.index.conflicts
                        if (ours or theirs) is not None
                    )
                )
                # Laissé EN COURS, exprès : c'est ce qui permet de le
                # résoudre puis de reprendre (D13).
                return failed("Rebase", f"conflicts in: {noms}")

            # `None` signale un commit devenu vide — le patch est déjà
            # en amont. `git rebase` le saute aussi ; ce n'est pas une
            # erreur (vérifié).
            if rebase.commit(committer=signature) is not None:
                rejoues += 1

        rebase.finish(signature)
    except Exception:
        # Ne jamais laisser un rebase à moitié fait sans issue : on le
        # défait avant de laisser l'erreur remonter à `guarded`.
        try:
            rebase.abort()
        except (pygit2.GitError, ValueError):
            pass
        raise

    pluriel = "" if rejoues == 1 else "s"
    return succeeded(f"Rebased {rejoues} commit{pluriel} onto {etiquette}")


_REBASE_STATES = frozenset(
    {
        RepositoryState.REBASE,
        RepositoryState.REBASE_INTERACTIVE,
        RepositoryState.REBASE_MERGE,
    }
)


def _reference_for(repo: pygit2.Repository, nom: str):
    """Référence correspondant à un nom de branche, locale ou distante."""
    for gabarit in ("refs/heads/{}", "refs/remotes/{}"):
        try:
            return repo.lookup_reference(gabarit.format(nom))
        except (KeyError, pygit2.GitError, ValueError):
            continue
    return None


def _label_for(repo: pygit2.Repository, oid) -> str | None:
    """Nom lisible de la cible, à partir de son commit."""
    for nom in list(repo.branches.local) + list(repo.branches.remote):
        try:
            if repo.branches[nom].target == oid:
                return nom
        except (KeyError, pygit2.GitError):
            continue
    return str(oid)[:8]


def _short(refname: str | None) -> str | None:
    if not refname:
        return None
    for prefixe in ("refs/heads/", "refs/remotes/"):
        if refname.startswith(prefixe):
            return refname[len(prefixe):]
    return refname


def _current_branch_name(repo: pygit2.Repository) -> str | None:
    if repo.head_is_unborn or repo.head_is_detached:
        return None
    try:
        return repo.head.shorthand
    except (pygit2.GitError, KeyError):
        return None


def _uncommitted(repo: pygit2.Repository) -> str:
    """Modifications qui empêchent un rebase. Vide s'il n'y en a pas."""
    bloquant = FileStatus.WT_MODIFIED | FileStatus.WT_DELETED
    bloquant |= FileStatus.INDEX_MODIFIED | FileStatus.INDEX_NEW
    bloquant |= FileStatus.INDEX_DELETED | FileStatus.CONFLICTED

    try:
        touches = [p for p, code in repo.status().items() if code & bloquant]
    except pygit2.GitError:
        return ""
    return ", ".join(sorted(touches)[:3])


def _signature(repo: pygit2.Repository) -> pygit2.Signature:
    try:
        return repo.default_signature
    except (KeyError, ValueError):
        return pygit2.Signature("tortoisePy", "tortoisepy@localhost")
