"""Marquage des commits significatifs — §6.1 étape 2.

Intention (le contrat, indépendant de l'algorithme) :

    Conserver l'ensemble minimal de commits préservant la connectivité
    topologique entre les refs. Deux refs reliées dans le DAG Git doivent
    le rester dans le graphe compressé, et tout point où l'histoire
    diverge ou converge doit rester visible.
"""

from __future__ import annotations

from collections import defaultdict

import pygit2

from tortoisepy.core.model import Oid, Ref


def _walk_once(repo: pygit2.Repository, tips: set[Oid]) -> list:
    """Un parcours topologique unique alimenté par TOUTES les pointes.

    `walker.push()` ajoute une racine au même parcours. Un walker par pointe
    reparcourrait l'historique commun autant de fois qu'il y a de pointes :
    mesuré sur 200 branches d'une chaîne de 2 000 commits, 201 200 visites
    pour 2 001 commits uniques — une redondance de facteur 101, soit 42 s
    contre 0,25 s ici.

    L'ordre topologique garantit qu'un commit précède ses parents, ce dont
    dépend la propagation des marques dans `_analyse`.
    """
    walker = None

    for tip in sorted(tips):
        try:
            oid = pygit2.Oid(hex=tip)
        except ValueError:
            continue
        try:
            if walker is None:
                walker = repo.walk(oid, pygit2.GIT_SORT_TOPOLOGICAL)
            else:
                walker.push(oid)
        except (pygit2.GitError, ValueError):
            continue

    return list(walker) if walker is not None else []


def _analyse(
    repo: pygit2.Repository, tips: set[Oid]
) -> tuple[dict[Oid, frozenset[Oid]], set[Oid]]:
    """Marquage par pointe et repérage des merges, parents de merges et racines.

    Les deux résultats sortent du même parcours : les calculer séparément
    doublait le coût pour aucun gain de clarté.

    Retourne :
      - pour chaque commit, l'ensemble des pointes qui l'atteignent ;
      - les commits significatifs par leur seule topologie (merges, parents
        directs de merges, racines).
    """
    marks: dict[Oid, set[Oid]] = defaultdict(set)
    topological: set[Oid] = set()

    for commit in _walk_once(repo, tips):
        oid = str(commit.id)

        if oid in tips:
            marks[oid].add(oid)

        parents = commit.parents  # itérés, jamais indexés : octopus > 2
        if not parents:
            topological.add(oid)  # racine
        elif len(parents) >= 2:
            topological.add(oid)  # merge
            topological.update(str(p.id) for p in parents)  # et ses parents

        # Le commit précède ses parents : ses marques leur remontent.
        inherited = marks[oid]
        for parent in parents:
            marks[str(parent.id)] |= inherited

    reach = {oid: frozenset(labels) for oid, labels in marks.items() if labels}
    return reach, topological


def _merge_bases(
    repo: pygit2.Repository, reach: dict[Oid, frozenset[Oid]]
) -> set[Oid]:
    """Ancêtres communs maximaux : les merge-bases.

    Un commun est maximal si aucun de ses enfants n'est commun aux mêmes
    pointes — sinon l'enfant est une base plus proche, et lui seul compte.
    """
    common = {oid for oid, labels in reach.items() if len(labels) >= 2}
    if not common:
        return set()

    children: dict[Oid, set[Oid]] = defaultdict(set)
    for oid in common:
        try:
            commit = repo.get(pygit2.Oid(hex=oid))
        except (pygit2.GitError, ValueError):
            continue
        if commit is None:
            continue
        for parent in commit.parents:
            children[str(parent.id)].add(oid)

    return {
        oid
        for oid in common
        if not any(reach[child] >= reach[oid] for child in children[oid] if child in reach)
    }


def significant_commits(
    repo: pygit2.Repository, refs: tuple[Ref, ...]
) -> set[Oid]:
    """Commits devenant des DisplayNode.

    Un commit est significatif s'il :
      - porte une ref ;
      - est un merge-base (ancêtre commun maximal) ;
      - est un commit de merge, ou le parent direct d'un merge ;
      - est une racine.

    Un seul parcours du DAG produit les deux familles : `_analyse` marque
    l'atteignabilité par pointe et repère au passage merges, parents de
    merges et racines.
    """
    if not refs:
        return set()

    tips = {ref.target for ref in refs}

    reach, topological = _analyse(repo, tips)

    return set(tips) | _merge_bases(repo, reach) | topological
