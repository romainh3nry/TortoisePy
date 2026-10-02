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
) -> tuple[dict[Oid, int], set[Oid]]:
    """Marquage par pointe et repérage des merges, parents de merges et racines.

    Les deux résultats sortent du même parcours : les calculer séparément
    doublait le coût pour aucun gain de clarté.

    Retourne :
      - pour chaque commit, un MASQUE DE BITS des pointes qui
        l'atteignent (un bit par pointe) ;
      - les commits significatifs par leur seule topologie (merges, parents
        directs de merges, racines).
    """
    # Les marques sont des ENTIERS, un bit par pointe, et non des
    # ensembles d'OID. `a | b` devient une instruction machine là où
    # `set | set` parcourt des chaînes de 40 caractères.
    #
    # Mesuré sur le dépôt de l'utilisateur (671 pointes, 23 676 commits
    # parcourus) : `_analyse` coûtait **878 ms**, l'essentiel des
    # 1042 ms de `significant_commits`, elles-mêmes 87 % de
    # `build_graph`. C'est la technique qui avait déjà fait passer
    # `reduce_transitive_edges` de 4,6 s à 0,04 s en phase 17.
    bit_de = {oid: 1 << index for index, oid in enumerate(sorted(tips))}

    marks: dict[Oid, int] = defaultdict(int)
    topological: set[Oid] = set()

    for commit in _walk_once(repo, tips):
        oid = str(commit.id)

        if oid in tips:
            marks[oid] |= bit_de[oid]

        parents = commit.parents  # itérés, jamais indexés : octopus > 2
        if not parents:
            topological.add(oid)  # racine
        elif len(parents) >= 2:
            topological.add(oid)  # merge
            topological.update(str(p.id) for p in parents)  # et ses parents

        # Le commit précède ses parents : ses marques leur remontent.
        inherited = marks[oid]
        if inherited:
            for parent in parents:
                marks[str(parent.id)] |= inherited

    return {oid: masque for oid, masque in marks.items() if masque}, topological


def _merge_bases(
    repo: pygit2.Repository, reach: dict[Oid, int]
) -> set[Oid]:
    """Ancêtres communs maximaux : les merge-bases.

    Un commun est maximal si aucun de ses enfants n'est commun aux mêmes
    pointes — sinon l'enfant est une base plus proche, et lui seul compte.

    `reach` associe à chaque commit un MASQUE DE BITS des pointes qui
    l'atteignent. `bit_count()` remplace `len(frozenset)`, et l'inclusion
    `enfant ⊇ parent` devient `enfant & parent == parent` — des
    opérations sur entiers, pas des parcours d'ensembles.
    """
    common = {oid for oid, masque in reach.items() if masque.bit_count() >= 2}
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
        if not any(
            reach[child] & reach[oid] == reach[oid]
            for child in children[oid]
            if child in reach
        )
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
