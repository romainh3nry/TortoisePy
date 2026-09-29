"""Opérations Git du menu contextuel — §7.3, §7.7.

Chaque fonction retourne un `OperationResult` et ne lève jamais : le
décorateur `guarded` convertit toute exception (§7.6).

Ce fichier ne couvre que la classe « simples » de §7.7. Les opérations
interactives (merge, rebase, cherry-pick, revert) et destructrices (reset)
viennent en tâche 4.
"""

from __future__ import annotations

import os
import stat
import subprocess

import pygit2
from pygit2.enums import FileMode

from tortoisepy.core.credentials import credentials_for, is_https
from tortoisepy.core.model import Oid
from tortoisepy.core.results import OperationResult, failed, guarded, succeeded

# Un push traverse le réseau : large, mais pas infini — une application
# graphique ne doit jamais rester suspendue sans issue.
_PUSH_TIMEOUT = 300


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

    # Un rebase ne s'abandonne PAS ainsi. `state_cleanup()` supprime
    # `.git/rebase-merge` et `reset(HARD)` remet la HEAD détachée sur
    # elle-même : la branche n'est jamais rattachée, et comme les
    # métadonnées ont disparu, `abort_rebase` ne peut plus rien
    # récupérer. Vérifié : l'utilisateur restait sur `## HEAD (no
    # branch)` après qu'on lui ait annoncé « rebase abandonné ».
    # C'est le défaut de la phase 8 que §5.4 interdit ; on délègue.
    if state.operation_in_progress == "rebase":
        from tortoisepy.core.rebase import abort_rebase

        return abort_rebase(repo)

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

    HTTPS demande à Git ses propres identifiants. Contrairement à ce que
    supposait la version précédente, **libgit2 ne consulte pas** le
    gestionnaire d'identifiants : un push HTTPS échouait sur « remote
    authentication required but no callback set » (signalé sur le dépôt
    `portfolio`). Passer par `git credential` règle le cas sur toutes les
    plateformes, puisque c'est Git qui choisit son backend.
    """
    if is_https(url):
        found = credentials_for(url)
        if found is not None:
            return pygit2.UserPass(found.username, found.password)
        return None

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


# --- Commit d'une sélection (§5, §6.1) ----------------------------------


@guarded("Commit")
def commit_selection(
    repo: pygit2.Repository, paths: tuple[str, ...], message: str
) -> OperationResult:
    """Commite les fichiers indiqués, sans toucher à l'index de l'utilisateur.

    Le commit est bâti sur un index **temporaire en mémoire** : décocher un
    fichier l'exclut du commit, mais ce que l'utilisateur a préparé au
    terminal reste intact (§5).
    """
    text = message.strip()
    if not text:
        return failed("Commit", "empty commit message")

    selected = tuple(p for p in paths if p)
    if not selected:
        return failed("Commit", "nothing selected")

    unborn = repo.head_is_unborn
    index = pygit2.Index()

    if not unborn:
        # Partir du dernier commit : tout ce qui n'est pas coché reste tel
        # quel, au lieu de disparaître du nouvel arbre.
        index.read_tree(repo.revparse_single("HEAD").tree)

    workdir = repo.workdir or ""
    for path in selected:
        full = os.path.join(workdir, path)
        # lexists (pas exists) : un symlink cassé doit rester committable
        # comme symlink, pas être pris pour un fichier supprimé.
        if os.path.lexists(full):
            # Un index détaché ne lit pas le disque : le blob doit être
            # créé explicitement (vérifié).
            blob = repo.create_blob_fromworkdir(path)
            # lstat (pas stat) : ne pas suivre le lien, sinon un symlink
            # serait vu comme sa cible et perdrait son mode LINK.
            info = os.lstat(full)
            if stat.S_ISLNK(info.st_mode):
                mode = FileMode.LINK
            elif info.st_mode & stat.S_IXUSR:
                mode = FileMode.BLOB_EXECUTABLE
            else:
                mode = FileMode.BLOB
            index.add(pygit2.IndexEntry(path, blob, mode))
        elif not unborn and path in [e.path for e in index]:
            index.remove(path)  # fichier supprimé
        else:
            return failed("Commit", f"file not found: {path}")

    tree = index.write_tree(repo)
    signature = _signature(repo)
    parents = [] if unborn else [repo.head.target]

    oid = repo.create_commit(
        "HEAD", signature, signature, text, tree, parents
    )

    # Un `git commit` termine l'opération en cours : il efface
    # `REVERT_HEAD`, `MERGE_MSG` et consorts. Sans ce nettoyage, git
    # croirait le revert toujours en cours après son propre commit, et
    # l'interface continuerait de griser checkout et merge.
    # Signalé sur le dépôt `portfolio` : le revert était commité ET poussé,
    # mais `REVERT_HEAD` traînait encore.
    if repo.state() != pygit2.enums.RepositoryState.NONE:
        try:
            repo.state_cleanup()
        except pygit2.GitError:
            # Le commit est acquis : ne pas le transformer en échec pour
            # un nettoyage de métadonnées raté.
            pass

    count = len(selected)
    plural = "" if count == 1 else "s"
    return succeeded(f"Committed {count} file{plural} — {str(oid)[:8]}")


# --- Push (§7.7, classe « simples ») -------------------------------------


class PushCallbacks(pygit2.RemoteCallbacks):
    """Suit un push : progression de l'envoi et refus du serveur.

    Distincte de `FetchCallbacks` pour deux raisons vérifiées sur
    pygit2 1.20 :

    - la progression du push passe par `push_transfer_progress`, avec un
      argument de plus que `transfer_progress` (celle du fetch) ;
    - le refus du serveur passe par `push_update_reference` et **ne lève
      pas**. Sans le lire, un push refusé serait annoncé comme réussi.
    """

    def __init__(self, url: str, on_progress=None):
        super().__init__(credentials=_credentials(url))
        self._on_progress = on_progress
        self.rejections: list[tuple[str, str]] = []

    def push_transfer_progress(
        self, objects_pushed: int, total_objects: int, bytes_pushed: int
    ) -> None:
        if self._on_progress is not None:
            self._on_progress(objects_pushed, total_objects)

    def push_update_reference(self, refname: str, message: str | None) -> None:
        # `message is None` vaut acceptation — vérifié sur un push réussi.
        if message is not None:
            self.rejections.append((refname, message))


def _push_with_lease(
    repo: pygit2.Repository, branch: str, remote_name: str
) -> OperationResult:
    """Pousse en forçant, **le bail arbitré par le serveur**.

    Délégué au `git` du système, et non à pygit2 : le vrai
    `--force-with-lease` transmet au serveur la valeur qu'on **attend**
    pour la ref, et c'est le serveur qui refuse si elle a bougé. libgit2
    1.20 ne sait pas exprimer cela — son refspec `+` force sans
    condition.

    Vérifié, et c'est la raison de ce détour : une vérification faite
    côté client puis suivie d'un `+` laisse une fenêtre de course. Un
    collègue qui pousse dans cet intervalle voyait son commit **détruit**
    alors que le bail venait d'être jugé valide. Avec `git`, le même
    scénario est refusé (« stale info ») et son travail survit.

    Le projet appelle déjà `git` en sous-processus pour les identifiants
    (`core/credentials.py`) : le précédent existe.
    """
    try:
        resultat = subprocess.run(
            ["git", "push", "--force-with-lease", remote_name, branch],
            cwd=repo.workdir or str(repo.path),
            capture_output=True,
            text=True,
            timeout=_PUSH_TIMEOUT,
            # Sans cela, git poserait une question sur un terminal qui
            # n'existe pas dans une application graphique, et l'appel
            # resterait suspendu (même raison que dans `credentials.py`).
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except subprocess.TimeoutExpired:
        # `repository_changed=True` : un `git push` interrompu a pu
        # terminer côté serveur **et** avancer la ref de suivi locale.
        # Annoncer l'inverse supprimerait le rafraîchissement qui le
        # montrerait, et l'affichage mentirait sur l'état du dépôt.
        return failed(
            "Push",
            f"push to '{remote_name}' timed out after "
            f"{_PUSH_TIMEOUT}s",
            repository_changed=True,
        )
    except OSError as erreur:
        return failed("Push", f"cannot run git: {erreur}",
                      repository_changed=False)

    if resultat.returncode == 0:
        return succeeded(f"Pushed {branch} to {remote_name} (forced)")

    detail = (resultat.stderr or resultat.stdout or "").strip()
    if "stale info" in detail:
        # Le message brut de git nomme des refs ; celui-ci dit quoi faire.
        return failed(
            "Push",
            f"'{remote_name}/{branch}' has moved since your last fetch — "
            "someone else pushed. Fetch before forcing.",
            repository_changed=False,
        )
    return failed("Push", detail or "push failed",
                  repository_changed=False)


def _default_remote(repo: pygit2.Repository, branch: str) -> str | None:
    """Remote vers lequel pousser cette branche.

    L'ordre compte : `repo.remotes.names()` est alphabétique, donc prendre
    le premier pousserait vers `aaa-upstream` plutôt que vers `origin`
    (vérifié) — un danger réel sur le schéma classique du fork, où
    `origin` est le dépôt de l'utilisateur et un autre remote celui
    d'autrui. On suit d'abord le suivi configuré de la branche, qui est
    l'intention explicite de l'utilisateur ; `origin` par convention
    ensuite ; l'ordre alphabétique seulement en dernier recours.
    """
    try:
        upstream = repo.branches[branch].upstream
        if upstream is not None and upstream.remote_name:
            return upstream.remote_name
    except (KeyError, pygit2.GitError):
        pass

    names = list(repo.remotes.names())
    if "origin" in names:
        return "origin"
    return names[0] if names else None


@guarded("Push")
def push_branch(
    repo: pygit2.Repository,
    remote_name: str | None = None,
    on_progress=None,
    force_with_lease: bool = False,
) -> OperationResult:
    """Pousse la branche courante vers son remote.

    `force_with_lease` réécrit la branche distante, **mais seulement si
    elle est encore là où notre dernier fetch l'a vue** : on remplace son
    propre historique, jamais celui d'un autre. `--force` inconditionnel
    n'existe nulle part dans cette application (D15) — c'est lui, et non
    le forçage en soi, que la phase 7 excluait.

    Un rebase réécrit les commits : sans cela, la branche ne peut plus
    être poussée du tout (vérifié : « cannot push non-fastforwardable
    reference »).
    """
    if repo.head_is_unborn or repo.head_is_detached:
        return failed("Push", "no branch to push (detached or unborn HEAD)")

    branch = repo.head.shorthand

    if remote_name:
        name = remote_name
    else:
        name = _default_remote(repo, branch)
    if name is None:
        return failed("Push", "no remote configured")

    remote = repo.remotes[name]

    if force_with_lease:
        # Confié à `git` : lui seul sait faire arbitrer le bail par le
        # serveur. Le refspec « + » de libgit2 forcerait sans condition
        # et détruirait le travail d'un tiers arrivé entre-temps.
        #
        # **Placé avant les garde-fous pygit2 ci-dessous, à dessein** :
        # ils protègent d'un segfault de libgit2 sur un remote
        # `pushurl`-only, que ce chemin ne touche pas. Vérifié : `git`
        # pousse très bien dans cette configuration, alors que le refus
        # invoquait une limite de pygit2 dans un chemin sans pygit2.
        return _push_with_lease(repo, branch, remote.name)

    # `push_url` prime sur `url` pour l'identifiant passé à `PushCallbacks`
    # (donc à `_credentials`) : un remote push-only laisse `url` à `None`.
    push_url = remote.push_url or remote.url
    if push_url is None:
        return failed("Push", f"remote '{remote.name}' has no push URL")

    # Vérifié sur pygit2 1.20 : quand `remote.url` est `None` (remote
    # configuré avec seulement `pushurl`), `git_remote_push` plante par un
    # segfault côté libgit2 — un `NoneType`/`GitError` ne suffirait pas à
    # s'en protéger, un `try/except` Python ne rattrape pas un segfault.
    # Le `git` en ligne de commande gère ce cas sans problème ; c'est une
    # limite de pygit2/libgit2, pas de tortoisePy. On refuse donc avant
    # d'appeler `remote.push()`, plutôt que de risquer de faire planter
    # tout le processus (et l'interface graphique avec).
    if remote.url is None:
        return failed(
            "Push",
            f"remote '{remote.name}' has no fetch URL (pushurl-only "
            "remotes are not supported: pygit2/libgit2 1.20 crashes on "
            "push in this configuration)",
        )

    callbacks = PushCallbacks(push_url, on_progress)

    # Construit depuis la branche courante : coder « master » en dur
    # échouerait sur un dépôt cloné récemment, qui est sur « main ».
    # **Aucun « + » ici** : ce chemin ne force jamais (D15).
    remote.push(
        [f"refs/heads/{branch}:refs/heads/{branch}"],
        callbacks=callbacks,
    )

    # `remote.push()` n'a pas levé, mais le serveur a pu refuser la ref :
    # annoncer un succès ici serait un mensonge.
    if callbacks.rejections:
        detail = "; ".join(
            f"{_short_ref(ref)}: {message}"
            for ref, message in callbacks.rejections
        )
        return failed("Push", detail)

    return succeeded(f"Pushed {branch} to {remote.name}")
