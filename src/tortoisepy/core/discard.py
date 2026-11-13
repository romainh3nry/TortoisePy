"""Annuler des modifications non commitées, avec un filet.

Demandé par l'utilisateur : « j'aimerai qu'il soit possible d'annuler
les changements depuis le graph — un clic droit sur un changement pour
pouvoir l'annuler unitairement, et un bouton permettant d'annuler tous
les changements en cours ».

C'est la **seule opération de l'application qui détruit du travail
absent de Git**. Un `reset --hard` perd des commits, mais le reflog les
garde 90 jours ; un fichier modifié qu'on annule n'existe nulle part —
ni dans Git, ni dans une corbeille.

D'où le filet, demandé par l'utilisateur : **un stash est posé avant
chaque annulation**, et `git stash pop` ramène tout. Le prix en est un
stash qui s'accumule dans la liste, ce que la confirmation annonce.

Aucun Qt ici : `tests/test_architecture.py` l'interdit à `core/`, et
cela rend l'opération testable sans fenêtre.
"""

from __future__ import annotations

import pygit2

from tortoisepy.core.results import OperationResult, failed, guarded, succeeded

_NON_SUIVI = pygit2.enums.FileStatus.WT_NEW
_IGNORE = pygit2.enums.FileStatus.IGNORED

_SUIVI_ET_MODIFIE = (
    pygit2.enums.FileStatus.WT_MODIFIED
    | pygit2.enums.FileStatus.WT_DELETED
    | pygit2.enums.FileStatus.WT_TYPECHANGE
    | pygit2.enums.FileStatus.WT_RENAMED
    | pygit2.enums.FileStatus.INDEX_MODIFIED
    | pygit2.enums.FileStatus.INDEX_DELETED
    | pygit2.enums.FileStatus.INDEX_TYPECHANGE
    | pygit2.enums.FileStatus.INDEX_RENAMED
    | pygit2.enums.FileStatus.INDEX_NEW
)
"""Ce qu'« annuler » sait défaire : un fichier connu de Git qui a bougé.

`INDEX_NEW` en fait partie : un fichier neuf mais **ajouté à l'index**
a une version dans Git, donc une version à laquelle revenir. Un fichier
jamais ajouté n'en a aucune (voir `_est_annulable`).
"""


def _signature(repo: pygit2.Repository) -> pygit2.Signature:
    """La signature du dépôt, ou celle de l'application à défaut.

    Un dépôt sans `user.name` configuré ne doit pas empêcher de poser le
    filet de sécurité — c'est justement le moment où on en a besoin.
    """
    try:
        return repo.default_signature
    except (KeyError, pygit2.GitError):
        return pygit2.Signature("tortoisePy", "tortoisepy@localhost")


def _est_annulable(statut: int) -> bool:
    """Ce statut désigne-t-il un changement qu'on sait défaire ?

    Les fichiers **non suivis** sont exclus (choix de l'utilisateur) :
    ils n'ont aucune version à restaurer, donc les « annuler »
    reviendrait à les supprimer. C'est ce que `git checkout --` refuse
    de faire, et ce qu'`abort_operation` refuse déjà dans ce projet —
    « Untracked files are left alone ».
    """
    if statut & _IGNORE:
        return False
    if statut & _NON_SUIVI:
        return False
    return bool(statut & _SUIVI_ET_MODIFIE)


def discardable_paths(repo: pygit2.Repository) -> tuple[str, ...]:
    """Les chemins que `discard_all` remettrait à leur état commité.

    Exposé pour que l'interface puisse annoncer **combien** de fichiers
    sont en jeu avant de demander confirmation : « annuler ? » sans
    chiffre ne permet pas de décider.
    """
    return tuple(
        sorted(
            chemin
            for chemin, statut in repo.status().items()
            if _est_annulable(statut)
        )
    )


def _poser_le_filet(repo: pygit2.Repository, quoi: str) -> str:
    """Stash de sécurité, puis remise en place immédiate.

    La séquence compte, et elle a été mesurée. `repo.stash(paths=[…])`
    crée bien un stash ne contenant que ces chemins, mais **vide
    l'arbre de travail entier** : un stash de `a.txt` ramenait aussi
    `b.txt` à son état commité, sans que `b.txt` y figure — son travail
    était perdu pour de bon, sans que rien ne le signale.

    On stashe donc **tout**, puis on réapplique aussitôt : l'arbre de
    travail est inchangé, et le stash reste comme copie de sauvegarde.
    Le checkout qui suit ne touche alors que ce qui est visé.

    `include_untracked=False` : un fichier jamais ajouté n'a pas à
    entrer dans un stash qu'on pose pour pouvoir l'annuler — il ne sera
    pas annulé.
    """
    oid = repo.stash(
        _signature(repo),
        message=f"tortoisePy: avant annulation de {quoi}",
        include_untracked=False,
    )
    # Remet l'arbre de travail tel qu'il était : le stash n'est pas une
    # mise de côté, c'est une copie de sauvegarde.
    repo.stash_apply(0)
    return str(oid)[:8]


@guarded("Discard")
def discard_file(repo: pygit2.Repository, path: str) -> OperationResult:
    """Rend `path` à son état commité, après avoir posé un stash.

    Les fichiers voisins ne sont pas touchés : c'est le piège mesuré de
    ce module, et un test le vérifie.
    """
    statut = repo.status().get(path)

    if statut is None:
        return failed("Discard", f"{path}: no change to discard")

    if statut & _NON_SUIVI:
        return failed(
            f"{path} is untracked — nothing to discard",
            "An untracked file has no committed version to restore. "
            "Delete it yourself if that is what you want.",
        )

    if not _est_annulable(statut):
        return failed("Discard", f"{path}: no change to discard")

    stash = _poser_le_filet(repo, path)
    repo.checkout_head(
        paths=[path], strategy=pygit2.enums.CheckoutStrategy.FORCE
    )
    # La commande de récupération est `checkout`, PAS `stash pop` :
    # mesuré, `pop` échoue sur « 1 conflict prevents checkout » dès
    # qu'un autre fichier du stash est encore modifié — ce qui est le
    # cas habituel d'une annulation unitaire. En ligne de commande,
    # `git stash pop` ne restaure alors rien et garde le stash.
    return succeeded(
        f"Discarded {path} — recover with: "
        f"git checkout stash@{{0}} -- {path}   (stash {stash})"
    )


@guarded("Discard")
def discard_all(repo: pygit2.Repository) -> OperationResult:
    """Rend tous les fichiers suivis à leur état commité.

    Un **seul** stash pour l'ensemble : un par fichier encombrerait la
    liste pour une opération que l'utilisateur voit comme unique.

    Les fichiers non suivis sont laissés en place, comme pour
    l'annulation unitaire.
    """
    chemins = discardable_paths(repo)

    if not chemins:
        # Un arbre où ne restent que des fichiers non suivis n'a rien à
        # annuler : poser un stash et rendre un succès laisserait croire
        # que quelque chose a été fait.
        return failed("Discard", "no tracked change to discard")

    stash = _poser_le_filet(repo, f"{len(chemins)} file(s)")
    repo.checkout_head(
        paths=list(chemins), strategy=pygit2.enums.CheckoutStrategy.FORCE
    )
    # Ici `pop` fonctionne : l'arbre est propre après l'annulation de
    # TOUS les fichiers suivis, donc rien n'entre en conflit.
    return succeeded(
        f"Discarded {len(chemins)} file(s) — recover with: "
        f"git stash pop   (stash {stash})"
    )
