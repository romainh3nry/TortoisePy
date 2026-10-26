"""Plusieurs dossiers de projets, pas un seul.

Demandé par l'utilisateur : « possible de pouvoir ajouter plusieurs
répertoires de projet ? »

Un seul dossier ne couvre pas un usage courant — des projets perso
d'un côté, professionnels de l'autre, parfois un disque externe.

Le piège, mesuré avant d'écrire : deux dossiers contenant chacun un
dépôt « api » donnaient deux entrées **indiscernables** dans le menu,
et `topy -s api` proposait deux lignes identiques. Le projet avait
déjà résolu ce problème un niveau plus bas — un « api » dans deux
sous-dossiers s'affiche « client-a/api » — et la même idée s'applique
aux racines.

Décision de l'utilisateur : **préfixer seulement en cas de
collision**. « vti » reste « vti » ; seuls les homonymes portent leur
dossier.
"""

from __future__ import annotations

import os
import subprocess

import pytest

from tortoisepy.core.projects import find_projects_in, search_projects


def run_git(path, *args):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
    }
    return subprocess.run(
        ["git", *args], cwd=path, env=env, capture_output=True, text=True
    )


def _depot(chemin):
    chemin.mkdir(parents=True, exist_ok=True)
    run_git(chemin, "init", "-q", "-b", "main")
    return chemin


@pytest.fixture
def deux_dossiers(tmp_path):
    """Deux racines, un homonyme « api » dans chacune."""
    perso = tmp_path / "perso"
    boulot = tmp_path / "boulot"
    _depot(perso / "api")
    _depot(perso / "blog")
    _depot(boulot / "api")
    _depot(boulot / "crm")
    return str(perso), str(boulot)


# --- le cas demandé -----------------------------------------------------


def test_projects_from_several_folders_are_gathered(deux_dossiers):
    """Le besoin : voir les projets de tous les dossiers."""
    trouves = find_projects_in(deux_dossiers)

    chemins = {p.path for p in trouves}
    assert len(chemins) == 4, f"{len(chemins)} projets au lieu de 4"
    for attendu in ("perso/api", "perso/blog", "boulot/api", "boulot/crm"):
        assert any(c.endswith(attendu) for c in chemins), (
            f"« {attendu} » manquant : {sorted(chemins)}"
        )


def test_a_single_folder_behaves_exactly_as_before(tmp_path):
    """Un seul dossier : rien ne change.

    C'est la garantie qui protège l'usage actuel. Les noms ne doivent
    pas se mettre à porter un préfixe parce que le code sait désormais
    gérer plusieurs racines.
    """
    racine = tmp_path / "Projects"
    _depot(racine / "vti")
    _depot(racine / "crm-equipment")

    noms = [p.name for p in find_projects_in([str(racine)])]

    assert noms == ["crm-equipment", "vti"]


def test_no_prefix_when_names_do_not_collide(tmp_path):
    """Deux dossiers sans homonyme : les noms restent nus.

    Décision de l'utilisateur. Préfixer systématiquement rendrait
    « vti » en « perso/vti » sans qu'aucune ambiguïté ne l'exige.
    """
    perso, boulot = tmp_path / "perso", tmp_path / "boulot"
    _depot(perso / "vti")
    _depot(boulot / "crm")

    noms = sorted(p.name for p in find_projects_in([str(perso), str(boulot)]))

    assert noms == ["crm", "vti"]


# --- le piège mesuré ----------------------------------------------------


def test_colliding_names_carry_their_folder(deux_dossiers):
    """LE cas qui a dicté la conception.

    Mesuré avant d'écrire : la simple concaténation donnait
    ['api', 'blog', 'api', 'crm'] — deux « api » que rien ne
    distingue, ni dans le menu ni dans `topy -s`.
    """
    trouves = find_projects_in(deux_dossiers)
    noms = sorted(p.name for p in trouves)

    assert "api" not in noms, (
        f"un « api » nu subsiste, donc deux entrées identiques : {noms}"
    )
    assert "perso/api" in noms
    assert "boulot/api" in noms


def test_only_the_colliding_names_are_prefixed(deux_dossiers):
    """Les voisins non ambigus gardent leur nom court.

    Le piège de la correction : préfixer tout le dossier dès qu'une
    seule collision s'y produit.
    """
    noms = sorted(p.name for p in find_projects_in(deux_dossiers))

    assert "blog" in noms, f"« blog » a été préfixé sans raison : {noms}"
    assert "crm" in noms, f"« crm » a été préfixé sans raison : {noms}"


def test_a_prefixed_name_stays_findable(deux_dossiers):
    """`topy -s api` doit encore trouver les deux, et les distinguer.

    Préfixer ne doit pas rendre un projet introuvable par son nom
    court : la recherche porte sur le nom complet, qui contient
    toujours « api ».
    """
    trouves = search_projects(find_projects_in(deux_dossiers), "api")

    assert len(trouves) == 2
    assert len({p.name for p in trouves}) == 2, (
        "les deux résultats portent le même libellé"
    )
    assert len({p.path for p in trouves}) == 2


# --- les cas limites ----------------------------------------------------


def test_an_unreadable_folder_does_not_hide_the_others(tmp_path):
    """Un disque débranché ne doit pas priver de tout.

    C'est la raison d'être de plusieurs dossiers : si l'un tombe, les
    autres restent. Une exception propagée les perdrait tous.
    """
    bon = tmp_path / "bon"
    _depot(bon / "vti")
    absent = str(tmp_path / "jamais-cree")

    trouves = find_projects_in([absent, str(bon)])

    assert [p.name for p in trouves] == ["vti"]


def test_no_folder_gives_no_project(tmp_path):
    """Aucun dossier configuré : un tuple vide, pas une erreur."""
    assert find_projects_in([]) == ()
    assert find_projects_in(None) == ()


def test_the_same_folder_twice_is_not_duplicated(tmp_path):
    """Ajouter deux fois le même dossier ne double pas la liste.

    L'utilisateur peut le faire sans s'en rendre compte — et chaque
    projet apparaîtrait deux fois, avec un préfixe absurde puisque les
    « collisions » seraient le dépôt avec lui-même.
    """
    racine = tmp_path / "Projects"
    _depot(racine / "vti")

    trouves = find_projects_in([str(racine), str(racine)])

    assert [p.name for p in trouves] == ["vti"]


def test_a_folder_inside_another_does_not_duplicate(tmp_path):
    """Un dossier et son parent, tous deux configurés.

    Cas réel : on ajoute `~/Projects`, puis `~/Projects/clients`. Les
    dépôts du second seraient trouvés deux fois.
    """
    racine = tmp_path / "Projects"
    _depot(racine / "clients" / "api")

    trouves = find_projects_in([str(racine), str(racine / "clients")])

    chemins = [p.path for p in trouves]
    assert len(chemins) == len(set(chemins)), (
        f"doublons : {chemins}"
    )


def test_a_nested_folder_names_the_closest_root(tmp_path):
    """Le préfixe vient du dossier le plus PROCHE, pas du plus large.

    Trouvé par mutation. Avec `~/Projects` et `~/Projects/clients`
    tous deux configurés, un homonyme sous le second doit porter
    « clients » : « Projects » ne distinguerait rien, puisque les deux
    dépôts en viennent.
    """
    racine = tmp_path / "Projects"
    clients = racine / "clients"
    _depot(racine / "api")          # directement sous Projects
    _depot(clients / "api")         # sous Projects/clients

    trouves = find_projects_in([str(racine), str(clients)])
    noms = sorted(p.name for p in trouves)

    assert "clients/api" in noms, (
        f"le préfixe ne nomme pas le dossier le plus proche : {noms}"
    )
    assert len(set(noms)) == len(noms), f"libellés en double : {noms}"


def test_the_order_is_stable_across_folders(deux_dossiers):
    """Tri global, pas dossier par dossier.

    Concaténer les listes triées donnerait ['api', 'blog', 'api',
    'crm'] : l'ordre repartirait de zéro à chaque dossier, et le menu
    paraîtrait désordonné.
    """
    noms = [p.name for p in find_projects_in(deux_dossiers)]

    assert noms == sorted(noms, key=str.lower), (
        f"l'ordre n'est pas global : {noms}"
    )
