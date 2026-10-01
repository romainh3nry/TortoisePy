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

from dataclasses import replace
from typing import Any, Callable

import pygit2

from tortoisepy.core.model import Oid, Ref, RefType


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


def _oid_de_head(repo: pygit2.Repository) -> Oid | None:
    try:
        if repo.head_is_unborn:
            return None
        return str(repo.head.target)
    except (pygit2.GitError, KeyError, ValueError):
        return None


def structural_fingerprint(repo: pygit2.Repository) -> tuple:
    """Ce qui change la TOPOLOGIE du graphe — HEAD exclu.

    Mesuré sur un dépôt réel de 713 refs : `build_graph` coûte 2185 ms,
    et un simple checkout le relançait entièrement alors que les arêtes
    étaient identiques au bit près. Seule la ref `HEAD` se déplaçait d'un
    nœud à l'autre.

    HEAD est donc retiré de cette empreinte, et sa position est replacée
    après coup par `rehome_head` — à une exception près, traitée par
    `head_is_structural` : en HEAD détachée, HEAD peut désigner un commit
    qu'aucune branche ne porte, et il AJOUTE alors un nœud (mesuré : le
    graphe passe de 1 à 2 nœuds). Le réutiliser perdrait ce nœud.
    """
    try:
        refs = tuple(
            sorted(
                (r.name, str(r.target))
                for r in repo.references.objects
                if r.name != "HEAD"
            )
        )
    except (pygit2.GitError, KeyError, ValueError):
        return (object(),)

    return (refs, int(repo.state()))


def head_is_structural(repo: pygit2.Repository, empreinte: tuple) -> bool:
    """HEAD désigne-t-il un commit qu'aucune autre ref ne porte ?

    Vrai en HEAD détachée sur un commit du milieu de l'historique : HEAD
    est alors le seul à le rendre significatif, et le graphe ne peut pas
    être réutilisé tel quel.

    L'empreinte déjà calculée est réutilisée plutôt que de reparcourir
    les refs : mesuré sur 692 refs, chaque parcours coûte 64 ms, et les
    refaire doublait le coût du chemin rapide.
    """
    oid = _oid_de_head(repo)
    if oid is None:
        return False

    refs = empreinte[0] if empreinte else ()
    if refs and isinstance(refs[0], tuple):
        return not any(cible == oid for _, cible in refs)

    # Empreinte dégradée (dépôt illisible) : on ne prend aucun risque.
    return True


def rehome_head(graphe: Any, repo: pygit2.Repository) -> Any:
    """Replace la ref `HEAD` sur le nœud courant, sans rien reconstruire.

    C'est ce qui rend le cache utilisable après un checkout : la
    topologie est conservée, seule l'étiquette bouge. Un graphe figé sur
    l'ancien nœud serait plus rapide mais FAUX — pire qu'un graphe lent.
    """
    oid = _oid_de_head(repo)
    if oid is None:
        return graphe

    # Le cache est générique (`Any`) : les tests y rangent des valeurs
    # qui ne sont pas des graphes. Sans ce garde-fou, `rehome_head` y
    # cherchait `.nodes` et levait.
    if not hasattr(graphe, "nodes"):
        return graphe

    deja_bon = any(
        noeud.oid == oid and any(r.type is RefType.HEAD for r in noeud.refs)
        for noeud in graphe.nodes
    )
    if deja_bon:
        return graphe

    cible = next((n for n in graphe.nodes if n.oid == oid), None)
    if cible is None:
        # HEAD ne tombe sur aucun nœud connu : le graphe en cache ne
        # convient pas. L'appelant reconstruira.
        return None

    head_ref = Ref("HEAD", RefType.HEAD, oid)
    noeuds = tuple(
        replace(
            noeud,
            refs=(
                tuple(r for r in noeud.refs if r.type is not RefType.HEAD)
                + ((head_ref,) if noeud.oid == oid else ())
            ),
        )
        for noeud in graphe.nodes
    )
    return replace(graphe, nodes=noeuds)


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
        self,
        repo: pygit2.Repository,
        build: Callable[[pygit2.Repository], Any],
        options_key: tuple | None = None,
    ) -> Any:
        """Rend le graphe, en le reconstruisant seulement si nécessaire.

        `options_key` couvre ce que l'empreinte du dépôt ignore : les
        filtres d'affichage. Basculer le filtre de tags ne change aucune
        ref, donc aucune empreinte — sans cette clé, le cache rendrait le
        graphe précédent et l'interface ne bougerait pas.

        L'empreinte **exclut HEAD** : un checkout ne change que lui, et
        reconstruire coûtait 2185 ms sur un dépôt réel de 713 refs pour
        un graphe aux arêtes identiques. La ref `HEAD` est replacée par
        `rehome_head`, sauf quand elle est structurante (HEAD détachée
        sur un commit sans branche), auquel cas on reconstruit.
        """
        structurelle = (structural_fingerprint(repo), options_key)
        reutilisable = (
            self._graphe is not None
            and structurelle == self._empreinte
            and not head_is_structural(repo, structurelle[0])
        )

        if reutilisable:
            # La topologie n'a pas bougé : on déplace seulement `HEAD`.
            # Mesuré sur 713 refs, cela remplace 2185 ms de reconstruction.
            replace_ = rehome_head(self._graphe, repo)
            if replace_ is not None:
                self._graphe = replace_
                return replace_
            # `None` : HEAD ne tombe sur aucun nœud connu — on reconstruit.

        graphe = build(repo)
        self._empreinte = structurelle
        self._graphe = graphe
        return graphe

    def invalidate(self) -> None:
        """Force la reconstruction au prochain appel.

        Utile après une opération dont on sait qu'elle change le graphe,
        sans attendre que l'empreinte le prouve.
        """
        self._empreinte = None
        self._graphe = None
