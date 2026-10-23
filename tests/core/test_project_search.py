"""Chercher un dépôt par mot-clé dans le dossier de projets.

Demandé par l'utilisateur : « un paramètre qui permet de faire une
sorte de recherche de dépôt — `topy -s vti` — on affiche les
résultats en CLI sous forme de liste et on permet à l'user de choisir
le dépôt qu'il souhaite ouvrir ».

La recherche vit ici, sans Qt ni terminal : `find_projects` fournit
déjà la liste, il ne reste qu'à la filtrer. L'invite elle-même est
dans `cli.py`, où elle se teste avec une entrée simulée.

Mesuré sur le dossier réel de l'utilisateur, 61 projets :

    « vti »    -> 1 résultat
    « crm »    -> 5
    « deploy » -> 5
    « zzz »    -> 0

Les listes restent donc courtes, ce qui justifie la numérotation
plutôt qu'un menu plein écran — lequel aurait exigé `curses`, absent
de CPython sous Windows.
"""

from __future__ import annotations

import pytest

from tortoisepy.core.projects import Project, search_projects


def _projets(*noms: str) -> tuple[Project, ...]:
    return tuple(
        Project(name=n, path=f"/w/{n}") for n in noms
    )


# --- le cas demandé -----------------------------------------------------


def test_a_keyword_finds_the_matching_project():
    """« topy -s vti » — la demande, mot pour mot."""
    tous = _projets("vti", "airflow", "crm-signature")

    assert [p.name for p in search_projects(tous, "vti")] == ["vti"]


def test_a_partial_keyword_matches():
    """Taper le nom entier n'aurait pas d'intérêt.

    C'est précisément la crainte exprimée : « pas pratique si le
    projet a un nom long ». Mesuré : 15,3 caractères en moyenne sur
    le dossier réel.
    """
    tous = _projets("network-services-api-testing", "vti")

    assert [p.name for p in search_projects(tous, "api")] == [
        "network-services-api-testing"
    ]


def test_several_matches_are_all_returned():
    """L'utilisateur choisira dans la liste.

    « crm » rend 5 résultats sur le dossier réel : c'est le cas
    nominal, pas une exception.
    """
    tous = _projets(
        "crm-equipment", "crm-signature", "airflow", "crm-sign-php-client"
    )

    trouves = search_projects(tous, "crm")

    assert len(trouves) == 3


def test_no_match_returns_nothing():
    """Zéro résultat est un cas ordinaire, pas une erreur.

    L'appelant le dira à l'utilisateur ; lever ici l'obligerait à
    rattraper une exception pour un cas attendu.
    """
    tous = _projets("vti", "airflow")

    assert search_projects(tous, "zzz") == ()


# --- la casse et les séparateurs ---------------------------------------


def test_the_search_ignores_case():
    """On tape vite, et en minuscules.

    Exiger la casse exacte sur `PyCharm` ou `CRM-Signature`
    transformerait un raccourci en devinette.
    """
    tous = _projets("CRM-Signature", "AirFlow")

    assert len(search_projects(tous, "crm")) == 1
    assert len(search_projects(tous, "AIRFLOW")) == 1


def test_a_nested_project_is_found_by_its_leaf_name():
    """Les projets imbriqués portent leur dossier parent.

    `deploy/sre-system` doit se trouver par « sre », sans qu'on ait à
    taper le préfixe — sinon la recherche serait plus longue que le
    chemin.
    """
    tous = _projets("deploy/sre-system", "vti")

    assert [p.name for p in search_projects(tous, "sre")] == [
        "deploy/sre-system"
    ]


def test_the_parent_folder_also_matches():
    """« deploy » doit rendre tous les projets du dossier.

    Mesuré sur le dossier réel : 5 projets sous `deploy/`.
    """
    tous = _projets("deploy/sre-system", "deploy/infra-flux-stg", "vti")

    assert len(search_projects(tous, "deploy")) == 2


# --- l'ordre et la robustesse ------------------------------------------


def test_the_order_is_preserved():
    """L'ordre vient de `find_projects`, trié pour un menu.

    Deux recherches qui numéroteraient différemment feraient taper le
    mauvais chiffre par habitude.
    """
    tous = _projets("crm-a", "crm-b", "crm-c")

    assert [p.name for p in search_projects(tous, "crm")] == [
        "crm-a", "crm-b", "crm-c"
    ]


def test_an_empty_keyword_finds_nothing():
    """`topy -s` sans motif rendrait 61 lignes : illisible.

    Mieux vaut ne rien rendre et laisser l'appelant refuser, que
    noyer le terminal.
    """
    tous = _projets("vti", "airflow")

    assert search_projects(tous, "") == ()
    assert search_projects(tous, "   ") == ()


def test_surrounding_spaces_are_ignored():
    """Une espace collée au motif ne doit pas faire échouer.

    `topy -s " vti"` depuis un script, ou une copie maladroite.
    """
    tous = _projets("vti", "airflow")

    assert [p.name for p in search_projects(tous, "  vti  ")] == ["vti"]


def test_searching_an_empty_list_is_safe():
    """Workdir vide, ou non choisi : aucun projet à filtrer."""
    assert search_projects((), "vti") == ()
