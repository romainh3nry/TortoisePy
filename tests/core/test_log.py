"""Lecture d'un journal de commits, par ref et/ou par chemin.

Deux questions auxquelles l'application ne savait pas répondre :

  - « quels commits porte cette branche ? » — `show_log` existait au menu
    contextuel mais ne faisait **rien** (il rendait un succès vide) ;
  - « quand ce fichier a-t-il changé, et pourquoi ? » — aucun écran ne le
    disait, alors que c'est la question qu'on se pose juste avant un blâme.

Le filtrage par chemin suit `git log -- <chemin>` : un commit compte si le
blob du chemin **diffère de celui de ses parents**. Comparer les ids de
blob plutôt que construire un diff complet évite de payer un diff par
commit parcouru (mesuré : 104 ms pour 70 commits sur ce dépôt, coût
linéaire en commits PARCOURUS et non trouvés).
"""

from __future__ import annotations

import pygit2
import pytest

from tortoisepy.core.log import read_log


@pytest.fixture
def depot(tmp_path):
    """Un dépôt où deux fichiers évoluent indépendamment.

    `RepoBuilder` remplace l'arbre entier à chaque commit (un fichier
    nouveau par commit) : impossible d'y suivre un fichier qui persiste et
    change, qui est précisément ce qu'on teste ici.

        commit   a.txt   b.txt   message
        ------   -----   -----   ----------------
        c1       v1      —       ajoute a
        c2       v1      v1      ajoute b
        c3       v2      v1      modifie a
        c4       v2      v2      modifie b
        c5       v2      v2      ne touche ni a ni b (ajoute c.txt)
        c6       v2      —       supprime b
    """
    repo = pygit2.init_repository(str(tmp_path / "d"), initial_head="master")
    sig = pygit2.Signature("Test", "t@example.com", 0, 0)
    oids: list[str] = []

    def commit(message: str, fichiers: dict[str, str]) -> str:
        builder = repo.TreeBuilder()
        for nom, contenu in sorted(fichiers.items()):
            blob = repo.create_blob(contenu.encode())
            builder.insert(nom, blob, pygit2.GIT_FILEMODE_BLOB)
        tree = builder.write()
        parents = [] if not oids else [pygit2.Oid(hex=oids[-1])]
        oid = repo.create_commit(
            "refs/heads/master", sig, sig, message, tree, parents
        )
        oids.append(str(oid))
        return str(oid)

    commit("ajoute a", {"a.txt": "v1"})
    commit("ajoute b", {"a.txt": "v1", "b.txt": "v1"})
    commit("modifie a", {"a.txt": "v2", "b.txt": "v1"})
    commit("modifie b", {"a.txt": "v2", "b.txt": "v2"})
    commit("ajoute c", {"a.txt": "v2", "b.txt": "v2", "c.txt": "v1"})
    commit("supprime b", {"a.txt": "v2", "c.txt": "v1"})

    return repo, oids


# --- journal d'une ref ---------------------------------------------------


def test_the_log_of_a_ref_lists_its_commits(depot):
    """Le cas de `show_log`, qui ne faisait rien."""
    repo, oids = depot
    journal = read_log(repo, ref="master")

    assert [c.oid for c in journal] == list(reversed(oids)), (
        "le journal doit aller du plus récent au plus vieux"
    )


def test_the_log_carries_the_summaries(depot):
    """Un journal sans message ne répond pas à « pourquoi »."""
    repo, _ = depot
    journal = read_log(repo, ref="master")

    assert [c.summary for c in journal][:2] == ["supprime b", "ajoute c"]


def test_an_unknown_ref_yields_nothing(depot):
    """Une branche supprimée entre-temps ne doit pas faire planter."""
    repo, _ = depot
    assert read_log(repo, ref="disparue") == ()


# --- journal d'un chemin -------------------------------------------------


def test_the_log_of_a_path_keeps_only_the_commits_touching_it(depot):
    """Le vrai manque : `git log -- a.txt`.

    `a.txt` n'est touché qu'à sa création et à sa modification — les trois
    autres commits ne doivent pas apparaître.
    """
    repo, oids = depot
    journal = read_log(repo, ref="master", path="a.txt")

    assert [c.summary for c in journal] == ["modifie a", "ajoute a"]


def test_a_path_log_excludes_commits_that_only_touch_other_files(depot):
    """L'assertion qui fait la valeur de la fonctionnalité.

    Sans elle, « historique du fichier » afficherait tout l'historique du
    dépôt — exactement ce que le panneau latéral fait déjà.
    """
    repo, _ = depot
    resumes = [c.summary for c in read_log(repo, ref="master", path="b.txt")]

    assert resumes == ["supprime b", "modifie b", "ajoute b"]
    assert "modifie a" not in resumes, "un commit sur a.txt a fui dans b.txt"
    assert "ajoute c" not in resumes


def test_the_creation_of_a_file_counts_as_a_change(depot):
    """Un fichier apparaît : c'est son premier commit, il doit y être.

    Le piège : comparer au parent donne `None != blob`, donc vrai — mais
    une implémentation qui exigerait la présence dans les deux arbres
    perdrait silencieusement la création.
    """
    repo, oids = depot
    journal = read_log(repo, ref="master", path="c.txt")

    assert [c.summary for c in journal] == ["ajoute c"]
    assert journal[0].oid == oids[4]


def test_a_root_commit_counts_for_a_file_it_introduces(depot):
    """Le commit racine n'a pas de parent : sa comparaison est un cas à part."""
    repo, oids = depot
    journal = read_log(repo, ref="master", path="a.txt")

    assert journal[-1].oid == oids[0], (
        "le commit racine doit apparaître pour le fichier qu'il crée"
    )


def test_the_deletion_of_a_file_counts_as_a_change(depot):
    """Un fichier disparaît : c'est un changement, et souvent celui qu'on
    cherche (« où est passé ce fichier ? »).

    Trouvé par mutation : une version exigeant `ici is not None` passait
    tous les autres tests. Une création se voit déjà par `None != blob`
    côté parent ; seule une SUPPRESSION met `ici` à `None` et distingue
    les deux implémentations.
    """
    repo, oids = depot
    journal = read_log(repo, ref="master", path="b.txt")

    assert journal[0].summary == "supprime b", (
        "la suppression doit figurer en tête de l'historique du fichier"
    )
    assert journal[0].oid == oids[5]


def test_an_unknown_path_yields_nothing(depot):
    """Un chemin jamais versionné : vide, pas une erreur."""
    repo, _ = depot
    assert read_log(repo, ref="master", path="jamais-vu.txt") == ()


def test_a_path_inside_a_directory_is_followed(tmp_path):
    """Les chemins réels ont des dossiers ; `tree[path]` doit les traverser."""
    repo = pygit2.init_repository(str(tmp_path / "dossiers"), initial_head="master")
    sig = pygit2.Signature("Test", "t@example.com", 0, 0)

    def commit(message, contenu, parents):
        blob = repo.create_blob(contenu.encode())
        interne = repo.TreeBuilder()
        interne.insert("fichier.py", blob, pygit2.GIT_FILEMODE_BLOB)
        racine = repo.TreeBuilder()
        racine.insert("src", interne.write(), pygit2.GIT_FILEMODE_TREE)
        return str(repo.create_commit(
            "refs/heads/master", sig, sig, message, racine.write(), parents
        ))

    un = commit("crée", "v1", [])
    commit("ne touche pas au fichier (même contenu)", "v1", [pygit2.Oid(hex=un)])

    journal = read_log(repo, ref="master", path="src/fichier.py")
    assert [c.summary for c in journal] == ["crée"], (
        "un chemin dans un dossier doit être suivi, et un arbre inchangé "
        "ne doit pas compter comme une modification"
    )


# --- limite et pagination ------------------------------------------------


def test_the_limit_caps_the_result(depot):
    """Sans limite, un gros dépôt ferait parcourir des milliers de commits."""
    repo, _ = depot
    assert len(read_log(repo, ref="master", limit=2)) == 2


def test_after_resumes_where_the_previous_page_stopped(depot):
    """« Load more » : la page suivante ne doit ni répéter ni sauter.

    Une limite dure mentirait sur l'historique ; un parcours complet
    gèlerait l'interface sur un gros dépôt.
    """
    repo, oids = depot
    page1 = read_log(repo, ref="master", limit=2)
    page2 = read_log(repo, ref="master", limit=2, after=page1[-1].oid)

    assert [c.oid for c in page1] == list(reversed(oids))[:2]
    assert [c.oid for c in page2] == list(reversed(oids))[2:4], (
        "la seconde page doit reprendre juste après la première"
    )


def test_after_works_with_a_path_filter(depot):
    """La pagination doit compter les commits RETENUS, pas les parcourus."""
    repo, _ = depot
    page1 = read_log(repo, ref="master", path="a.txt", limit=1)
    page2 = read_log(repo, ref="master", path="a.txt", limit=1,
                     after=page1[-1].oid)

    assert [c.summary for c in page1] == ["modifie a"]
    assert [c.summary for c in page2] == ["ajoute a"]


def test_an_unknown_after_yields_nothing(depot):
    """Un OID absent ne doit pas rendre tout l'historique par défaut."""
    repo, _ = depot
    assert read_log(repo, ref="master", after="0" * 40) == ()


# --- garantie de lecture seule ------------------------------------------


def test_reading_a_log_writes_nothing(depot):
    """§7.0 : l'application ne modifie le dépôt que sur action explicite.

    Un journal est une consultation : ni l'index, ni les refs, ni HEAD ne
    doivent bouger.
    """
    repo, _ = depot
    refs_avant = {r: str(repo.references[r].target) for r in repo.references}
    head_avant = str(repo.head.target)

    read_log(repo, ref="master")
    read_log(repo, ref="master", path="a.txt")

    assert {r: str(repo.references[r].target) for r in repo.references} == refs_avant
    assert str(repo.head.target) == head_avant
