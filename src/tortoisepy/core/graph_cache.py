"""Éviter de reconstruire un graphe qui n'a pas changé — phase 13.

`build_graph` coûte **330 ms sur 3 000 commits**, et 97 % de ce temps
part dans un parcours complet de l'historique (mesuré). Or la plupart
des rafraîchissements — ceux que déclenche le surveillant de fichiers —
n'apportent aucun changement de refs : tout ce travail est refait pour
un résultat identique.

L'empreinte, elle, coûte **0,4 ms**. C'est cet écart de trois ordres de
grandeur qui rend le cache rentable dès le premier rafraîchissement
inutile.
"""

from __future__ import annotations

from typing import Any, Callable

import pygit2


def repo_fingerprint(repo: pygit2.Repository) -> tuple:
    """Ce qui, en changeant, change le graphe affiché.

    Les refs **et** HEAD **et** l'état : une opération en cours ou un
    changement de branche courante modifient l'affichage sans qu'aucune
    ref n'ait forcément bougé. Un cache qui les ignorerait montrerait un
    graphe faux — pire qu'un graphe lent.
    """
    try:
        refs = tuple(
            sorted((r.name, str(r.target)) for r in repo.references.objects)
        )
    except (pygit2.GitError, KeyError, ValueError):
        # Un dépôt illisible ne doit pas faire planter l'affichage : on
        # rend une empreinte unique, qui force la reconstruction.
        return (object(),)

    if repo.head_is_unborn:
        tete: str | None = None
    elif repo.head_is_detached:
        tete = str(repo.head.target)
    else:
        tete = repo.head.shorthand

    return (refs, tete, int(repo.state()))


class GraphCache:
    """Garde le dernier graphe construit, tant que le dépôt n'a pas bougé.

    En mémoire seulement, le temps de la session : persister sur disque
    demanderait d'invalider correctement entre deux lancements, et §7.0
    interdit d'écrire dans le dépôt.
    """

    def __init__(self) -> None:
        self._empreinte: tuple | None = None
        self._graphe: Any = None

    def get(
        self, repo: pygit2.Repository, build: Callable[[pygit2.Repository], Any]
    ) -> Any:
        """Rend le graphe, en le reconstruisant seulement si nécessaire."""
        empreinte = repo_fingerprint(repo)
        if self._graphe is not None and empreinte == self._empreinte:
            return self._graphe

        graphe = build(repo)
        self._empreinte = empreinte
        self._graphe = graphe
        return graphe

    def invalidate(self) -> None:
        """Force la reconstruction au prochain appel.

        Utile après une opération dont on sait qu'elle change le graphe,
        sans attendre que l'empreinte le prouve.
        """
        self._empreinte = None
        self._graphe = None
