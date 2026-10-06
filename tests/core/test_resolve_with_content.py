"""Résoudre un conflit avec un contenu composé, pas un camp entier.

Signalé par l'utilisateur, capture à l'appui, sur un rebase dans `vti` :
deux clés YAML sans rapport — `rate-limit:` d'un côté, `twoFactorAuth:`
de l'autre — que git marque en conflit parce qu'elles sont adjacentes. La
bonne résolution est de **garder les deux**, or l'application ne
proposait que « Keep ours » ou « Keep theirs ».

C'est la limite que la phase 8 avait posée (D12 : « choisir un camp par
fichier, ni éditeur de fusion »). Elle tient pour les conflits réels,
mais pas pour les blocs simplement voisins — cas fréquent dans un fichier
de configuration, où chaque section est indépendante.

La difficulté technique : `resolve_with` écrit un blob **qui existe
déjà** (celui d'un des deux camps). Un contenu composé à la main
n'existe nulle part dans la base d'objets — il faut le créer.
"""

from __future__ import annotations

import os
import subprocess

import pygit2
import pytest

from tortoisepy.core.conflicts import list_conflicts, resolve_with_content


ENV = {
    "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
    "PATH": "/usr/bin:/bin:/usr/local/bin",
}


def _git(chemin, *args, check=True):
    return subprocess.run(
        ["git", "-C", str(chemin), *args], check=check,
        capture_output=True, env=ENV, text=True,
    )


@pytest.fixture
def depot_en_conflit(tmp_path):
    """Un conflit calqué sur celui de l'utilisateur : deux blocs voisins.

        ours   : ajoute `rate-limit:`     après la ligne commune
        theirs : ajoute `twoFactorAuth:`  au même endroit

    Les deux sont indépendants ; les garder tous les deux est la
    résolution attendue, et aucun des deux camps seul ne convient.
    """
    w = tmp_path / "w"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    conf = w / "conf.yml"

    conf.write_text("commun: 1\n")
    _git(w, "add", ".")
    _git(w, "commit", "-qm", "base")

    _git(w, "checkout", "-qb", "autre")
    conf.write_text("commun: 1\ntwoFactorAuth:\n  enabled: true\n")
    _git(w, "add", ".")
    _git(w, "commit", "-qm", "2fa")

    _git(w, "checkout", "-q", "main")
    conf.write_text("commun: 1\nrate-limit:\n  max: 40000\n")
    _git(w, "add", ".")
    _git(w, "commit", "-qm", "rate limit")

    # Déclenche le conflit sans le résoudre.
    _git(w, "merge", "autre", check=False)

    repo = pygit2.Repository(str(w))
    assert repo.index.conflicts is not None, "le conflit doit exister"
    return repo


FUSION = (
    "commun: 1\n"
    "rate-limit:\n"
    "  max: 40000\n"
    "twoFactorAuth:\n"
    "  enabled: true\n"
)
"""Ce que l'utilisateur veut : les deux blocs, dans l'ordre qu'il choisit."""


# --- le cas signalé ------------------------------------------------------


def test_a_composed_content_resolves_the_conflict(depot_en_conflit):
    """L'assertion centrale : garder les DEUX côtés."""
    resultat = resolve_with_content(depot_en_conflit, "conf.yml", FUSION)

    assert resultat.success, resultat.git_error
    assert list_conflicts(depot_en_conflit) == (), (
        "le fichier doit sortir de la liste des conflits"
    )


def test_the_working_file_holds_the_composed_content(depot_en_conflit):
    """Le disque doit porter le texte voulu, pas un des deux camps."""
    resolve_with_content(depot_en_conflit, "conf.yml", FUSION)

    chemin = os.path.join(depot_en_conflit.workdir, "conf.yml")
    assert open(chemin).read() == FUSION


def test_the_index_holds_the_composed_content(depot_en_conflit):
    """Le fichier doit être STAGÉ avec ce contenu, prêt à être commité.

    Sans cela, le commit de fusion reprendrait un des deux camps et le
    travail de composition serait perdu sans un mot.
    """
    resolve_with_content(depot_en_conflit, "conf.yml", FUSION)

    index = depot_en_conflit.index
    entree = index["conf.yml"]
    assert depot_en_conflit.get(entree.id).data.decode() == FUSION


def test_the_blob_is_created_in_the_object_database(depot_en_conflit):
    """Le contenu composé n'existe nulle part : il faut l'écrire.

    C'est la différence avec `resolve_with`, qui réutilise un blob déjà
    présent. Un oubli ici ferait échouer le commit plus tard, loin de sa
    cause.
    """
    resolve_with_content(depot_en_conflit, "conf.yml", FUSION)

    entree = depot_en_conflit.index["conf.yml"]
    objet = depot_en_conflit.get(entree.id)
    assert objet is not None, "le blob composé n'est pas dans la base"
    assert objet.type == pygit2.enums.ObjectType.BLOB


# --- ce qui ne doit PAS arriver -----------------------------------------


def test_an_unknown_path_is_refused(depot_en_conflit):
    """Un chemin sans conflit ne doit pas être écrit en douce.

    Accepter ici écraserait un fichier que l'utilisateur n'a jamais
    désigné — exactement ce que la garantie de lecture seule interdit.

    Le message est vérifié, pas seulement l'échec : trouvé par mutation,
    retirer la garde laissait quand même le test au vert, parce que
    `del index.conflicts[path]` levait plus loin et que `guarded`
    rattrapait. Le refus était accidentel — il tenait à l'ordre des
    opérations — et un réagencement l'aurait fait disparaître.
    """
    resultat = resolve_with_content(
        depot_en_conflit, "jamais-vu.yml", "peu importe"
    )

    assert not resultat.success
    assert "no conflict on" in (resultat.git_error or ""), (
        f"refus accidentel plutôt que délibéré : {resultat.git_error!r}"
    )
    assert not os.path.exists(
        os.path.join(depot_en_conflit.workdir, "jamais-vu.yml")
    )
    # Et le fichier RÉELLEMENT en conflit n'a pas bougé non plus.
    assert list_conflicts(depot_en_conflit) != ()


def test_resolving_without_a_conflict_is_refused(tmp_path):
    """Hors conflit, cette fonction n'a rien à faire."""
    w = tmp_path / "propre"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "a.txt").write_text("a\n")
    _git(w, "add", ".")
    _git(w, "commit", "-qm", "base")

    resultat = resolve_with_content(pygit2.Repository(str(w)), "a.txt", "x")

    assert not resultat.success
    assert open(w / "a.txt").read() == "a\n", "le fichier a été modifié"


def test_only_the_named_file_is_touched(depot_en_conflit):
    """Résoudre un fichier ne doit rien changer aux autres."""
    autre = os.path.join(depot_en_conflit.workdir, "intact.txt")
    with open(autre, "w") as f:
        f.write("ne pas toucher\n")

    resolve_with_content(depot_en_conflit, "conf.yml", FUSION)

    assert open(autre).read() == "ne pas toucher\n"


# --- contenus particuliers ----------------------------------------------


def test_an_empty_content_is_accepted(depot_en_conflit):
    """Vider le fichier est une résolution légitime : tout retirer.

    Le piège : confondre « contenu vide » et « pas de contenu ». Un test
    qui n'exercerait que du texte non vide laisserait passer un `if not
    contenu: return failed(...)`.
    """
    resultat = resolve_with_content(depot_en_conflit, "conf.yml", "")

    assert resultat.success, resultat.git_error
    chemin = os.path.join(depot_en_conflit.workdir, "conf.yml")
    assert open(chemin).read() == ""
    assert list_conflicts(depot_en_conflit) == ()


def test_a_content_without_trailing_newline_is_kept_as_is(depot_en_conflit):
    """Ne rien ajouter au texte de l'utilisateur.

    Ajouter un saut de ligne « pour bien faire » modifierait un fichier
    dont l'absence de fin de ligne est parfois significative.
    """
    resolve_with_content(depot_en_conflit, "conf.yml", "sans fin de ligne")

    chemin = os.path.join(depot_en_conflit.workdir, "conf.yml")
    assert open(chemin).read() == "sans fin de ligne"


def test_utf8_content_survives(depot_en_conflit):
    """Un fichier de configuration porte souvent des accents."""
    texte = "clé: « valeur accentuée »\n"
    resolve_with_content(depot_en_conflit, "conf.yml", texte)

    chemin = os.path.join(depot_en_conflit.workdir, "conf.yml")
    assert open(chemin, encoding="utf-8").read() == texte


# --- lecture des trois versions -----------------------------------------


def test_the_three_versions_are_readable(depot_en_conflit):
    """L'interface a besoin des deux camps ET de la base pour les montrer."""
    from tortoisepy.core.conflicts import read_versions

    versions = read_versions(depot_en_conflit, "conf.yml")

    assert "rate-limit" in versions.ours, "le camp « ours » est absent"
    assert "twoFactorAuth" in versions.theirs, "le camp « theirs » est absent"
    assert "commun: 1" in versions.ours


def test_reading_versions_of_an_unknown_path_is_empty(depot_en_conflit):
    """Un chemin sans conflit n'a pas de versions à montrer."""
    from tortoisepy.core.conflicts import read_versions

    assert read_versions(depot_en_conflit, "jamais-vu.yml") is None
