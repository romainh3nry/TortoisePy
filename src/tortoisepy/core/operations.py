"""Opérations Git du menu contextuel — §7.3, §7.7.

Chaque fonction retourne un `OperationResult` et ne lève jamais : le
décorateur `guarded` convertit toute exception (§7.6).

Ce fichier ne couvre que la classe « simples » de §7.7. Les opérations
interactives (merge, rebase, cherry-pick, revert) et destructrices (reset)
viennent en tâche 4.
"""

from __future__ import annotations

import pygit2

from tortoisepy.core.model import Oid
from tortoisepy.core.results import OperationResult, failed, guarded, succeeded


def _commit(repo: pygit2.Repository, oid: Oid) -> pygit2.Commit:
    """Résout un OID en commit. Lève si inconnu — `guarded` s'en charge."""
    return repo.get(pygit2.Oid(hex=oid)).peel(pygit2.Commit)


@guarded("Création de la branche")
def create_branch(
    repo: pygit2.Repository, name: str, oid: Oid
) -> OperationResult:
    repo.create_branch(name, _commit(repo, oid))
    return succeeded(f"Branche « {name} » créée")


@guarded("Suppression de la branche")
def delete_branch(repo: pygit2.Repository, name: str) -> OperationResult:
    """Refuse la branche courante : le dépôt se retrouverait sans HEAD valide."""
    if not repo.head_is_detached and not repo.head_is_unborn:
        if repo.head.shorthand == name:
            return failed(
                f"Suppression de « {name} »",
                "cannot delete the currently checked out branch",
            )

    branch = repo.branches.local.get(name)
    if branch is None:
        return failed(
            f"Suppression de « {name} »", f"branch '{name}' not found"
        )

    branch.delete()
    return succeeded(f"Branche « {name} » supprimée")


@guarded("Renommage de la branche")
def rename_branch(
    repo: pygit2.Repository, old: str, new: str
) -> OperationResult:
    branch = repo.branches.local.get(old)
    if branch is None:
        return failed(f"Renommage de « {old} »", f"branch '{old}' not found")

    branch.rename(new)
    return succeeded(f"Branche « {old} » renommée en « {new} »")


@guarded("Création du tag")
def create_tag(
    repo: pygit2.Repository, name: str, oid: Oid, message: str | None = None
) -> OperationResult:
    """Tag léger par défaut ; annoté si un message est fourni."""
    commit = _commit(repo, oid)

    if message is None:
        repo.create_reference(f"refs/tags/{name}", commit.id)
    else:
        signature = _signature(repo)
        repo.create_tag(
            name, commit.id, pygit2.enums.ObjectType.COMMIT, signature, message
        )

    return succeeded(f"Tag « {name} » créé")


@guarded("Suppression du tag")
def delete_tag(repo: pygit2.Repository, name: str) -> OperationResult:
    reference = f"refs/tags/{name}"
    if reference not in repo.references:
        return failed(f"Suppression du tag « {name} »", f"tag '{name}' not found")

    repo.references.delete(reference)
    return succeeded(f"Tag « {name} » supprimé")


@guarded("Checkout de la branche")
def checkout_branch(repo: pygit2.Repository, name: str) -> OperationResult:
    branch = repo.branches.local.get(name)
    if branch is None:
        return failed(f"Checkout de « {name} »", f"branch '{name}' not found")

    repo.checkout(branch)
    return succeeded(f"Basculé sur « {name} »")


@guarded("Checkout du commit")
def checkout_commit(repo: pygit2.Repository, oid: Oid) -> OperationResult:
    """Checkout détaché sur un commit précis."""
    commit = _commit(repo, oid)
    repo.checkout_tree(commit)
    repo.set_head(commit.id)
    return succeeded(f"HEAD détaché sur {oid[:8]}")


def _signature(repo: pygit2.Repository) -> pygit2.Signature:
    """Signature du dépôt, avec repli si la configuration est absente."""
    try:
        return repo.default_signature
    except (KeyError, pygit2.GitError):
        return pygit2.Signature("tortoisePy", "tortoisepy@localhost")


# --- Opérations interactives et destructrices (§7.7) ---------------------

from pygit2.enums import MergeAnalysis, ResetMode

_RESET_MODES = {
    "soft": ResetMode.SOFT,
    "mixed": ResetMode.MIXED,
    "hard": ResetMode.HARD,
}


@guarded("Fusion", changed_on_error=True)
def merge_branch(repo: pygit2.Repository, name: str) -> OperationResult:
    """Fusionne une branche dans la branche courante.

    En cas de conflit, le dépôt RESTE modifié : l'index porte les conflits
    et `state()` vaut MERGE. D'où `changed_on_error=True` — l'UI doit
    reconstruire le graphe même après l'échec (§7.6).
    """
    branch = repo.branches.local.get(name)
    if branch is None:
        return failed(f"Fusion de « {name} »", f"branch '{name}' not found")

    analysis, _ = repo.merge_analysis(branch.target)

    if analysis & MergeAnalysis.UP_TO_DATE:
        return succeeded(
            f"« {name} » est déjà fusionnée", repository_changed=False
        )

    repo.merge(branch.target)

    conflicts = _conflicted_paths(repo)
    if conflicts:
        return failed(
            f"Fusion de « {name} »",
            f"conflits sur : {', '.join(conflicts)}",
            repository_changed=True,
        )

    return succeeded(f"« {name} » fusionnée")


@guarded("Abandon de l'opération")
def abort_operation(repo: pygit2.Repository) -> OperationResult:
    """Annule l'opération en cours et restaure l'arbre sur HEAD.

    Équivalent de `merge --abort` : nettoie l'état, puis remet l'arbre de
    travail et l'index dans l'état de HEAD.
    """
    from tortoisepy.core.state import read_state

    state = read_state(repo)
    if state.operation_in_progress is None:
        return failed(
            "Abandon", "no operation in progress", repository_changed=False
        )

    repo.state_cleanup()
    repo.reset(repo.head.target, ResetMode.HARD)
    return succeeded(f"{state.operation_in_progress} abandonné")


@guarded("Réinitialisation", changed_on_error=True)
def reset_to(
    repo: pygit2.Repository, oid: Oid, mode: str = "mixed"
) -> OperationResult:
    """Déplace la branche courante. `mode` vaut soft, mixed ou hard.

    En mode hard, les modifications non commitées sont perdues : l'UI doit
    demander confirmation avant d'appeler (§7.5).
    """
    reset_mode = _RESET_MODES.get(mode)
    if reset_mode is None:
        return failed(
            "Réinitialisation",
            f"unknown reset mode '{mode}' (soft, mixed or hard)",
            repository_changed=False,
        )

    commit = _commit(repo, oid)
    repo.reset(commit.id, reset_mode)
    return succeeded(f"Branche réinitialisée sur {oid[:8]} ({mode})")


@guarded("Cherry-pick", changed_on_error=True)
def cherry_pick(repo: pygit2.Repository, oid: Oid) -> OperationResult:
    """Applique un commit sur la branche courante."""
    commit = _commit(repo, oid)
    repo.cherrypick(commit.id)

    conflicts = _conflicted_paths(repo)
    if conflicts:
        return failed(
            f"Cherry-pick de {oid[:8]}",
            f"conflits sur : {', '.join(conflicts)}",
            repository_changed=True,
        )

    return succeeded(f"Commit {oid[:8]} appliqué")


@guarded("Revert", changed_on_error=True)
def revert_commit(repo: pygit2.Repository, oid: Oid) -> OperationResult:
    """Annule les changements d'un commit par un commit inverse."""
    commit = _commit(repo, oid)
    repo.revert(commit)

    conflicts = _conflicted_paths(repo)
    if conflicts:
        return failed(
            f"Revert de {oid[:8]}",
            f"conflits sur : {', '.join(conflicts)}",
            repository_changed=True,
        )

    return succeeded(f"Commit {oid[:8]} annulé")


def _conflicted_paths(repo: pygit2.Repository) -> tuple[str, ...]:
    """Chemins en conflit après une opération. Vide s'il n'y en a pas."""
    try:
        conflicts = repo.index.conflicts
    except (pygit2.GitError, AttributeError):
        return ()

    if conflicts is None:
        return ()

    paths: set[str] = set()
    for entries in conflicts:
        for entry in entries:
            if entry is not None:
                paths.add(entry.path)
                break

    return tuple(sorted(paths))


OPERATION_CLASSES: dict[str, tuple[str, ...]] = {
    "simple": (
        "create_branch",
        "rename_branch",
        "create_tag",
        "delete_tag",
        "checkout_branch",
        "checkout_commit",
    ),
    "interactive": (
        "merge_branch",
        "cherry_pick",
        "revert_commit",
        "abort_operation",
    ),
    "destructive": (
        "delete_branch",
        "reset_to",
    ),
}
"""Classement de §7.7. L'UI s'en sert pour décider du traitement : exécution
directe, détection d'état intermédiaire, ou confirmation préalable (§7.5)."""


# --- Opérations réseau (§7.7, classe « simples ») -----------------------

def _credentials(url: str):
    """Identifiants pour une URL distante, ou `None` si inutile.

    SSH passe par l'agent : c'est ce qui permet de ne jamais manipuler de
    clé ni de mot de passe. Vérifié sur un dépôt GitLab d'entreprise.
    HTTPS repose sur le gestionnaire d'identifiants de Git, que libgit2
    consulte seul.
    """
    if url.startswith(("git@", "ssh://")):
        return pygit2.KeypairFromAgent("git")
    return None


class FetchCallbacks(pygit2.RemoteCallbacks):
    """Suit un fetch : progression du transfert et refs mises à jour.

    `update_tips` est appelé pour chaque ref créée ou déplacée — c'est ce
    qui permet de dire à l'utilisateur *ce qui* est arrivé, et pas
    seulement que quelque chose est arrivé.
    """

    def __init__(self, url: str, on_progress=None):
        super().__init__(credentials=_credentials(url))
        self._on_progress = on_progress
        self.new_refs: list[str] = []
        self.updated_refs: list[str] = []
        self.received_objects = 0
        self.total_objects = 0

    def transfer_progress(self, stats) -> None:
        self.received_objects = stats.received_objects
        self.total_objects = stats.total_objects
        if self._on_progress is not None:
            self._on_progress(stats.received_objects, stats.total_objects)

    def update_tips(self, refname: str, old, new) -> None:
        # Un OID nul signale une ref qui n'existait pas encore.
        if old is None or str(old) == "0" * 40:
            self.new_refs.append(refname)
        else:
            self.updated_refs.append(refname)


def _short_ref(refname: str) -> str:
    """`refs/remotes/origin/feature` → `origin/feature`, `refs/tags/v1` → `v1`."""
    for prefix in ("refs/remotes/", "refs/tags/", "refs/heads/"):
        if refname.startswith(prefix):
            return refname[len(prefix):]
    return refname


def _describe(callbacks_list: list["FetchCallbacks"]) -> str:
    """Phrase décrivant ce qu'un fetch a rapporté.

    Nommer les refs, pas seulement les compter : « origin/feature,
    v2.1 » renseigne, « 2 refs » beaucoup moins.
    """
    new = [_short_ref(r) for cb in callbacks_list for r in cb.new_refs]
    updated = [_short_ref(r) for cb in callbacks_list for r in cb.updated_refs]

    if not new and not updated:
        return ""

    parts: list[str] = []
    if new:
        shown = ", ".join(sorted(new)[:6])
        more = f" +{len(new) - 6}" if len(new) > 6 else ""
        parts.append(f"new: {shown}{more}")
    if updated:
        shown = ", ".join(sorted(updated)[:6])
        more = f" +{len(updated) - 6}" if len(updated) > 6 else ""
        parts.append(f"updated: {shown}{more}")

    return " — ".join(parts)


@guarded("Fetch")
def fetch_remote(
    repo: pygit2.Repository,
    remote_name: str | None = None,
    on_progress=None,
) -> OperationResult:
    """Met à jour les refs distantes.

    Ne touche ni à l'arbre de travail, ni aux branches locales : c'est
    l'opération réseau la moins risquée. `remote_name` à `None` traite
    tous les remotes configurés.

    `on_progress(received, total)` est appelé pendant le transfert. Il est
    invoqué depuis le fil qui exécute le fetch : un appelant Qt doit donc
    passer par un signal plutôt que toucher à l'interface directement.
    """
    names = (
        [remote_name] if remote_name else list(repo.remotes.names())
    )
    if not names:
        return failed("Fetch", "no remote configured")

    tracked: list[FetchCallbacks] = []
    for name in names:
        remote = repo.remotes[name]
        callbacks = FetchCallbacks(remote.url, on_progress)
        remote.fetch(callbacks=callbacks)
        tracked.append(callbacks)

    label = names[0] if len(names) == 1 else f"{len(names)} remotes"
    changes = _describe(tracked)

    if changes:
        return succeeded(f"Fetched from {label} — {changes}")

    # Aucune ref touchée : le dépôt est déjà à jour, le graphe est inchangé.
    return succeeded(f"{label} already up to date", repository_changed=False)
