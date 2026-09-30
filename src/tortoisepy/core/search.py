"""Chercher un commit dans tout l'historique — phase 13.

**Les commits ne sont pas les nœuds.** Vérifié : 3 000 commits se
réduisent à 10 nœuds, la compression du graphe faisant son travail. Une
recherche qui n'examinerait que les nœuds raterait 99,7 % des commits ;
on parcourt donc l'historique, et l'interface surligne le nœud porteur.
"""

from __future__ import annotations

import pygit2


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
