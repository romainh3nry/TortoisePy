"""Trouver les projets Git d'un dossier de travail.

Demandé par l'utilisateur : choisir un répertoire de projets, puis
lister dans un menu déroulant tous les projets qu'il contient.

Le piège d'entrée, et la raison d'un module séparé : `find_repository`
(dans `cli.py`) s'appuie sur `pygit2.discover_repository`, qui **remonte**
l'arborescence comme le fait Git. Appelée sur chaque sous-dossier d'un
workdir lui-même versionné, elle « trouverait » partout le dépôt parent
et la liste serait entièrement fausse. La détection doit donc regarder
le dossier LUI-MÊME, sans jamais remonter.

Profondeur : deux niveaux (choix de l'utilisateur), pour couvrir les
arborescences rangées par client — `~/Projets/client/leur-projet`.
"""

from __future__ import annotations

import os

import pytest

from tortoisepy.core.projects import find_projects


def _depot(chemin) -> None:
    """Crée un dépôt minimal : seul `.git` compte pour la détection."""
    chemin.mkdir(parents=True, exist_ok=True)
    (chemin / ".git").mkdir()


# --- le cas nominal -----------------------------------------------------


def test_a_folder_of_projects_is_listed(tmp_path):
    """La demande, telle quelle : les projets du dossier choisi."""
    _depot(tmp_path / "alpha")
    _depot(tmp_path / "beta")

    trouves = find_projects(str(tmp_path))

    assert [p.name for p in trouves] == ["alpha", "beta"]


def test_the_results_are_sorted(tmp_path):
    """Un menu doit être lisible : l'ordre du disque ne l'est pas.

    `iterdir` rend les entrées dans l'ordre du système de fichiers,
    qui n'est ni alphabétique ni stable d'une machine à l'autre.
    """
    for nom in ("zeta", "alpha", "Mu", "beta"):
        _depot(tmp_path / nom)

    noms = [p.name for p in find_projects(str(tmp_path))]

    assert noms == sorted(noms, key=str.lower), f"ordre inattendu : {noms}"


def test_each_project_carries_its_full_path(tmp_path):
    """Le nom sert à l'affichage, le chemin à l'ouverture."""
    _depot(tmp_path / "alpha")

    projet = find_projects(str(tmp_path))[0]

    assert projet.path == str(tmp_path / "alpha")
    assert projet.name == "alpha"


# --- ce qui NE doit pas être listé --------------------------------------


def test_a_folder_without_git_is_ignored(tmp_path):
    """Choix de l'utilisateur : masquer ce qui ne s'ouvre pas.

    Un menu qui propose ce qui ne marche pas fait cliquer pour
    apprendre un échec évitable.
    """
    _depot(tmp_path / "projet")
    (tmp_path / "documents").mkdir()
    (tmp_path / "images").mkdir()

    assert [p.name for p in find_projects(str(tmp_path))] == ["projet"]


def test_loose_files_are_ignored(tmp_path):
    """Un fichier n'est pas un projet, même nommé comme un dépôt."""
    _depot(tmp_path / "projet")
    (tmp_path / "notes.txt").write_text("x")
    (tmp_path / "autre.git").write_text("x")

    assert [p.name for p in find_projects(str(tmp_path))] == ["projet"]


def test_a_git_file_counts_as_a_repository(tmp_path):
    """Un worktree ou un submodule porte un FICHIER `.git`, pas un dossier.

    Le piège : tester `.git` avec `is_dir()` les exclurait tous, alors
    que ce sont de vrais dépôts que l'application sait ouvrir.
    """
    (tmp_path / "worktree").mkdir()
    (tmp_path / "worktree" / ".git").write_text("gitdir: /ailleurs/.git\n")

    assert [p.name for p in find_projects(str(tmp_path))] == ["worktree"]


def test_hidden_folders_are_skipped(tmp_path):
    """`.cache`, `.Trash` et consorts ne sont pas des projets.

    Sans cette exclusion, un `~/Projets/.git` — le workdir lui-même
    versionné — se listerait comme un de ses propres enfants.
    """
    _depot(tmp_path / "projet")
    _depot(tmp_path / ".cache")

    assert [p.name for p in find_projects(str(tmp_path))] == ["projet"]


# --- la profondeur, choisie par l'utilisateur ---------------------------


def test_projects_are_found_two_levels_down(tmp_path):
    """Les arborescences rangées par client (choix de l'utilisateur)."""
    _depot(tmp_path / "client" / "leur-projet")
    _depot(tmp_path / "direct")

    noms = sorted(p.name for p in find_projects(str(tmp_path)))

    # L'imbriqué porte son parent : voir
    # `test_a_nested_project_carries_a_readable_name`.
    assert noms == ["client/leur-projet", "direct"]


def test_the_scan_stops_at_the_third_level(tmp_path):
    """Deux niveaux, et pas plus.

    Sans limite, un dossier contenant des `node_modules` ou des
    dépendances vendorisées rendrait le scan très lent pour rien.
    """
    _depot(tmp_path / "a" / "b" / "trop-profond")

    assert find_projects(str(tmp_path)) == ()


def test_a_repository_is_not_searched_for_sub_projects(tmp_path):
    """On arrête de descendre dès qu'un `.git` est trouvé.

    Un dépôt ne contient pas d'autres projets à lister : ses
    sous-modules et ses dossiers de dépendances n'ont rien à faire
    dans le menu, et les parcourir coûterait cher sur un gros projet.
    """
    _depot(tmp_path / "projet")
    _depot(tmp_path / "projet" / "vendor-interne")

    assert [p.name for p in find_projects(str(tmp_path))] == ["projet"]


def test_a_nested_project_carries_a_readable_name(tmp_path):
    """Deux projets de même nom sous deux clients doivent se distinguer.

    Afficher deux fois « api » dans le menu rendrait le choix
    impossible : le nom porte donc son dossier parent.
    """
    _depot(tmp_path / "client-a" / "api")
    _depot(tmp_path / "client-b" / "api")

    noms = sorted(p.name for p in find_projects(str(tmp_path)))

    assert noms == ["client-a/api", "client-b/api"], noms


# --- robustesse : le dossier peut avoir disparu -------------------------


def test_a_missing_folder_yields_nothing(tmp_path):
    """Un workdir sur un disque externe débranché ne doit pas lever.

    L'application doit pouvoir le dire à l'utilisateur, pas s'arrêter.
    """
    assert find_projects(str(tmp_path / "jamais-cree")) == ()


def test_a_file_given_as_a_folder_yields_nothing(tmp_path):
    fichier = tmp_path / "pas-un-dossier.txt"
    fichier.write_text("x")

    assert find_projects(str(fichier)) == ()


def test_an_empty_path_yields_nothing(tmp_path):
    """Aucun workdir choisi : le cas du premier lancement."""
    assert find_projects("") == ()
    assert find_projects(None) == ()


@pytest.mark.skipif(os.geteuid() == 0, reason="root lit tout")
def test_an_unreadable_folder_is_skipped(tmp_path):
    """Un sous-dossier interdit ne doit pas faire échouer tout le scan.

    Le piège : une `PermissionError` au milieu du parcours priverait
    l'utilisateur de TOUS ses projets, pas seulement de celui-là.
    """
    _depot(tmp_path / "lisible")
    interdit = tmp_path / "interdit"
    interdit.mkdir()
    interdit.chmod(0o000)
    try:
        assert [p.name for p in find_projects(str(tmp_path))] == ["lisible"]
    finally:
        interdit.chmod(0o755)


# --- le scan ne doit RIEN écrire (§7.0) ---------------------------------


def test_the_scan_writes_nothing(tmp_path):
    """Garantie de lecture seule : lister n'est pas ouvrir.

    §7.0 : l'application ne modifie la structure d'un dépôt que sur
    action explicite depuis l'UI. Un scan qui instancierait
    `pygit2.Repository` pourrait écrire des fichiers de verrou sur un
    dépôt abîmé — on se contente donc de regarder le disque.
    """
    _depot(tmp_path / "projet")
    avant = {
        chemin: chemin.stat().st_mtime
        for chemin in tmp_path.rglob("*")
    }

    find_projects(str(tmp_path))

    apres = {
        chemin: chemin.stat().st_mtime
        for chemin in tmp_path.rglob("*")
    }
    assert avant == apres, "le scan a modifié le disque"
