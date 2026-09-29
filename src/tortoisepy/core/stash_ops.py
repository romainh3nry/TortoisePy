"""Mettre son travail de côté, et le reprendre — phase 11.

`core/stashes.py` dessine les stashes dans le graphe ; ce module agit
dessus. Séparés à dessein : l'un sert l'affichage, l'autre écrit.

**Chaque stash est désigné par son OID, jamais par son index.** Les index
glissent — retirer `stash@{0}` fait de l'ancien `stash@{1}` le nouveau
`stash@{0}` (vérifié). Entre l'affichage du graphe et le clic, la liste
peut avoir changé : agir par index appliquerait alors un autre stash que
celui montré, sans rien signaler.

Aucune opération n'emploie `changed_on_error` : contrairement au merge ou
au rebase, qui peuvent modifier le dépôt **puis** échouer, libgit2 refuse
un stash inapplicable **avant** d'y toucher — vérifié, le dépôt reste à
`state() == 0`, le stash survit et le fichier local est intact. Annoncer
un changement là où il n'y en a eu aucun provoquerait un rafraîchissement
pour rien.
"""

from __future__ import annotations

import pygit2

from tortoisepy.core.results import OperationResult, failed, guarded, succeeded

_ABSENT = "this stash no longer exists — the list changed since it was shown"


def index_of(repo: pygit2.Repository, oid: str) -> int | None:
    """Position actuelle du stash portant cet OID, ou `None`.

    Relue à chaque appel : c'est tout l'intérêt de passer par l'OID.
    """
    try:
        entries = repo.listall_stashes()
    except (AttributeError, pygit2.GitError):
        return None
    for index, entry in enumerate(entries):
        if str(entry.commit_id) == str(oid):
            return index
    return None


def _signature(repo: pygit2.Repository) -> pygit2.Signature:
    """Signature de l'utilisateur, ou un pis-aller.

    Un dépôt sans `user.name` configuré ne doit pas faire échouer un
    stash : Git lui-même s'en passe pour cette opération locale.

    **Vérifié** : un `user.name` vide lève `InvalidError('failed to parse
    signature')`, qui hérite de `GitError` — le `except` ci-dessous la
    couvre donc. Ne pas resserrer sur `KeyError` seul.
    """
    try:
        return repo.default_signature
    except (KeyError, pygit2.GitError):
        return pygit2.Signature("tortoisePy", "tortoisepy@localhost")


@guarded("Stash")
def stash_changes(
    repo: pygit2.Repository, message: str | None = None
) -> OperationResult:
    """Met de côté les modifications, y compris les fichiers non suivis.

    `include_untracked=True` (D17) : vérifié, sans lui un dossier ne
    contenant que des fichiers neufs répond « nothing to stash » alors
    que l'utilisateur a bien du travail en cours.
    """
    oid = repo.stash(
        _signature(repo), message=message or None, include_untracked=True
    )
    return succeeded(f"Stashed as {str(oid)[:8]}")


@guarded("Stash")
def apply_stash(repo: pygit2.Repository, oid: str) -> OperationResult:
    """Restaure le contenu du stash **sans** le retirer.

    Garder le stash est la raison d'être d'`Apply` face à `Pop` : on peut
    l'appliquer ailleurs, sur une autre branche par exemple.
    """
    index = index_of(repo, oid)
    if index is None:
        return failed("Stash", _ABSENT, repository_changed=False)
    repo.stash_apply(index)
    return succeeded("Stash applied")


@guarded("Stash")
def pop_stash(repo: pygit2.Repository, oid: str) -> OperationResult:
    """Restaure le contenu, puis retire le stash.

    En cas d'échec, **le stash survit** (vérifié) — c'est ce qui rend ce
    geste sans danger.
    """
    index = index_of(repo, oid)
    if index is None:
        return failed("Stash", _ABSENT, repository_changed=False)
    repo.stash_pop(index)
    return succeeded("Stash popped")


@guarded("Stash")
def drop_stash(repo: pygit2.Repository, oid: str) -> OperationResult:
    """Retire le stash **sans** rien restaurer.

    Le seul geste qui détruit du travail sans le rendre : l'interface le
    fait confirmer.
    """
    index = index_of(repo, oid)
    if index is None:
        return failed("Stash", _ABSENT, repository_changed=False)
    repo.stash_drop(index)
    return succeeded("Stash dropped")
