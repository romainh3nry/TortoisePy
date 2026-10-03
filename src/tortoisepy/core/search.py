"""Chercher un commit dans tout l'historique — phase 13.

**Les commits ne sont pas les nœuds.** Vérifié : 3 000 commits se
réduisent à 10 nœuds, la compression du graphe faisant son travail. Une
recherche qui n'examinerait que les nœuds raterait 99,7 % des commits ;
on parcourt donc l'historique, et l'interface surligne le nœud porteur.
"""

from __future__ import annotations

import pygit2

from tortoisepy.core.model import Oid, RefType


def search_commits(repo: pygit2.Repository, motif: str) -> tuple[str, ...]:
    """OID des commits dont le message, l'auteur ou le SHA correspond.

    Un seul champ pour les trois critères : obliger à en choisir un
    avant de taper ferait réfléchir l'utilisateur à la place de l'outil.

    Sans casse, sauf pour le SHA où seul le préfixe compte.

    Un motif vide ne rend **rien** plutôt que tout : il sert à effacer
    le surlignage, et surligner l'intégralité du graphe n'apprendrait
    rien.
    """
    recherche = motif.strip().lower()
    if not recherche:
        return ()

    try:
        if repo.head_is_unborn:
            return ()
        depart = repo.head.target
    except (pygit2.GitError, KeyError, ValueError):
        return ()

    trouves: list[str] = []
    try:
        for commit in repo.walk(depart, pygit2.GIT_SORT_TOPOLOGICAL):
            oid = str(commit.id)
            if (
                recherche in commit.message.lower()
                or recherche in commit.author.name.lower()
                or oid.startswith(recherche)
            ):
                trouves.append(oid)
    except (pygit2.GitError, KeyError, ValueError):
        return tuple(trouves)

    return tuple(trouves)


def matching_branches(graph, motif: str) -> tuple[Oid, ...]:
    """OID des nœuds portant une branche dont le nom contient `motif`.

    Demandé par l'utilisateur : chercher une branche par mot-clé et
    centrer la vue dessus, puis naviguer entre les résultats.

    **Les nœuds, pas les branches.** Un nœud portant `login` et
    `origin/login` est UNE destination : sans déduplication, appuyer sur
    Entrée semblerait ne rien faire, puisqu'on « naviguerait » vers le
    nœud déjà centré.

    **Seules les branches.** Inclure les tags rendrait la navigation
    imprévisible sur un dépôt qui en compte des centaines — mesuré sur
    un dépôt réel, 413 tags pour 710 refs.

    L'ordre suit celui du graphe, donc il est stable d'un appel à
    l'autre : naviguer en boucle l'exige.
    """
    recherche = motif.strip().lower()
    if not recherche or graph is None:
        return ()

    branches = {RefType.LOCAL_BRANCH, RefType.REMOTE_BRANCH}
    trouves: list[Oid] = []
    for noeud in graph.nodes:
        if any(
            ref.type in branches and recherche in ref.name.lower()
            for ref in noeud.refs
        ):
            trouves.append(noeud.oid)
    return tuple(trouves)
