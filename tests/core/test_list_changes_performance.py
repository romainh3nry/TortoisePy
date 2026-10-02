"""`list_changes` ne doit pas recalculer le diff une fois par fichier.

Signalé par l'utilisateur : la fenêtre de commit mettait « plusieurs
minutes » à s'ouvrir sur un gros dépôt, et re-gelait au clic sur un
fichier.

Mesuré sur 300 fichiers modifiés :

    list_changes    14452 ms
    _is_binary x50   1323 ms  ->  26.5 ms par fichier
    extrapole a 300  7939 ms

Cause : `_is_binary` appelait `_patch_for`, qui recalcule le diff
COMPLET du dépôt. Appelé une fois par fichier, le diff entier était donc
calculé autant de fois qu'il y a de fichiers — un coût quadratique.

`diff_for` d'un seul fichier coûte 24 ms : ce n'est pas le diff qui est
lent, c'est de le refaire 300 fois.
"""

from __future__ import annotations

import subprocess
import time

import pygit2
import pytest

from tortoisepy.core.changes import list_changes


def _git(chemin, *args):
    subprocess.run(
        ["git", "-C", str(chemin), *args], check=False, capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
            "PATH": "/usr/bin:/bin:/usr/local/bin",
        },
    )


@pytest.fixture
def beaucoup_de_fichiers(tmp_path):
    """200 fichiers modifiés — l'ordre de grandeur d'un vrai dépôt."""
    w = tmp_path / "w"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    for i in range(200):
        (w / f"f{i}.txt").write_text("origine\n")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "base")
    for i in range(200):
        (w / f"f{i}.txt").write_text("modifie\n")
    return pygit2.Repository(str(w))


def test_the_diff_is_computed_once(beaucoup_de_fichiers, monkeypatch):
    """L'assertion centrale : un seul calcul de diff, pas un par fichier.

    C'est elle qui empêche le retour du coût quadratique, quelle que
    soit la machine — un seuil en millisecondes serait fragile.
    """
    from tortoisepy.core import changes

    appels = []
    vrai = changes._diff_du_depot

    def compte(repo, **kw):
        appels.append(1)
        return vrai(repo, **kw)

    changes._cache_diff = None          # cache froid, pour compter
    monkeypatch.setattr(changes, "_diff_du_depot", compte)
    resultat = list_changes(beaucoup_de_fichiers)

    assert len(resultat) == 200
    assert len(appels) == 1, (
        f"le diff a été calculé {len(appels)} fois pour 200 fichiers"
    )


def test_it_stays_fast(beaucoup_de_fichiers):
    """Garde-fou grossier : 200 fichiers en moins d'une seconde.

    Avant correction, l'extrapolation donnait ~8 s rien que pour
    `_is_binary`.
    """
    debut = time.perf_counter()
    list_changes(beaucoup_de_fichiers)
    ecoule = time.perf_counter() - debut

    assert ecoule < 1.0, f"{ecoule:.1f} s pour 200 fichiers"


def test_binary_files_are_still_detected(tmp_path):
    """La correction ne doit pas perdre l'information."""
    w = tmp_path / "w"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "texte.txt").write_text("du texte\n")
    (w / "binaire.dat").write_bytes(bytes(range(256)) * 10)
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "base")
    (w / "texte.txt").write_text("du texte modifié\n")
    (w / "binaire.dat").write_bytes(bytes(reversed(range(256))) * 10)

    par_chemin = {
        c.path: c for c in list_changes(pygit2.Repository(str(w)))
    }
    assert par_chemin["binaire.dat"].is_binary is True
    assert par_chemin["texte.txt"].is_binary is False


def test_untracked_files_are_listed(tmp_path):
    """Un fichier jamais commité doit apparaître (garantie existante)."""
    w = tmp_path / "w"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "a.txt").write_text("a\n")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "base")
    (w / "nouveau.txt").write_text("jamais commité\n")

    chemins = {c.path for c in list_changes(pygit2.Repository(str(w)))}
    assert "nouveau.txt" in chemins


def test_an_empty_repository_is_handled(tmp_path):
    """Un dépôt sans commit ne doit pas lever."""
    w = tmp_path / "vide"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "a.txt").write_text("a\n")

    chemins = {c.path for c in list_changes(pygit2.Repository(str(w)))}
    assert "a.txt" in chemins


# --- Le clic sur un fichier ne doit pas repayer le diff complet ---------


def test_diff_for_reuses_the_cached_diff(beaucoup_de_fichiers, monkeypatch):
    """Signalé par l'utilisateur : « ça freeze quand je clique sur le
    change dans la fenêtre du commit ».

    `diff_for` appelait `_patch_for`, qui recalcule le diff COMPLET du
    dépôt — pour un seul fichier. Mesuré sur 300 fichiers : 68 ms par
    clic, et ça croît avec la taille du dépôt.
    """
    from tortoisepy.core import changes

    appels = []
    vrai = changes._diff_du_depot

    def compte(repo, **kw):
        appels.append(1)
        return vrai(repo, **kw)

    monkeypatch.setattr(changes, "_diff_du_depot", compte)

    for i in range(10):
        changes.diff_for(beaucoup_de_fichiers, f"f{i}.txt")

    assert len(appels) <= 1, (
        f"le diff a été recalculé {len(appels)} fois pour 10 clics"
    )


def test_the_cache_follows_the_working_tree(beaucoup_de_fichiers, tmp_path):
    """Un cache qui ne s'invalide pas montrerait un diff périmé —
    pire qu'un diff lent."""
    from tortoisepy.core import changes

    repo = beaucoup_de_fichiers
    avant = changes.diff_for(repo, "f0.txt")
    lignes_avant = sum(len(h.lines) for h in avant.hunks)

    chemin = __import__("pathlib").Path(repo.workdir) / "f0.txt"
    chemin.write_text("encore une autre version\nsur deux lignes\n")

    apres = changes.diff_for(repo, "f0.txt")
    lignes_apres = sum(len(h.lines) for h in apres.hunks)

    assert lignes_apres != lignes_avant, (
        "le diff en cache n'a pas suivi la modification du fichier"
    )


# --- SHOW_UNTRACKED_CONTENT : payé seulement quand il sert --------------


def test_listing_does_not_read_untracked_content(monkeypatch, tmp_path):
    """Mesuré sur un dépôt réel : 57,7 s pour UN seul fichier modifié.

    `SHOW_UNTRACKED_CONTENT` fait lire le contenu de chaque fichier non
    suivi du dépôt. Sur un projet avec `node_modules` ou des caches, cela
    représente des centaines de milliers de fichiers — pour dresser une
    liste qui n'en a pas besoin.

    Lister les fichiers n'a besoin que de leurs noms et de leur nature ;
    le contenu ne sert qu'à afficher le diff d'UN fichier.
    """
    from tortoisepy.core import changes
    from pygit2.enums import DiffOption

    w = tmp_path / "w"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "a.txt").write_text("a\n")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "base")
    (w / "a.txt").write_text("modifie\n")

    vus = []
    vrai = changes._diff_du_depot

    def espion(repo, *, contenu_non_suivi=True):
        vus.append(contenu_non_suivi)
        return vrai(repo, contenu_non_suivi=contenu_non_suivi)

    monkeypatch.setattr(changes, "_diff_du_depot", espion)
    changes.list_changes(pygit2.Repository(str(w)))

    assert vus, "aucun diff calculé"
    assert not any(vus), (
        "la liste a demandé le contenu des fichiers non suivis"
    )


def test_an_untracked_file_still_shows_its_diff(tmp_path):
    """Le contenu reste disponible AU CLIC, là où il sert vraiment."""
    from tortoisepy.core.changes import diff_for

    w = tmp_path / "w"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "a.txt").write_text("a\n")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "base")
    (w / "nouveau.txt").write_text("ligne une\nligne deux\n")

    diff = diff_for(pygit2.Repository(str(w)), "nouveau.txt")
    lignes = [l.content for h in diff.hunks for l in h.lines]
    assert "ligne une" in lignes, lignes


def test_binary_detection_survives_for_tracked_files(tmp_path):
    """Un binaire SUIVI doit rester détecté sans le drapeau coûteux."""
    from tortoisepy.core.changes import list_changes

    w = tmp_path / "w"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "image.dat").write_bytes(bytes(range(256)) * 10)
    (w / "texte.txt").write_text("du texte\n")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "base")
    (w / "image.dat").write_bytes(bytes(reversed(range(256))) * 10)
    (w / "texte.txt").write_text("autre texte\n")

    par_chemin = {
        c.path: c for c in list_changes(pygit2.Repository(str(w)))
    }
    assert par_chemin["image.dat"].is_binary is True
    assert par_chemin["texte.txt"].is_binary is False


# --- Deux diffs valent mieux qu'un ---------------------------------------


def test_the_diff_combines_index_and_workdir(tmp_path):
    """Mesuré sur un dépôt réel de grande taille :

        tree.diff_to_index(index)     5.9 ms
        index.diff_to_workdir()     431.8 ms
                                    ────────
                                      438 ms

        tree.diff_to_workdir()     5851.6 ms   <- 13x plus lent

    `diff_to_workdir` depuis l'ARBRE est pathologiquement lent : il
    recompare tout l'arbre contre le disque. Passer par l'index — ce que
    fait `git status` lui-même, en 492 ms — donne le même résultat.

    Ce test vérifie le RÉSULTAT, pas la vitesse : un seuil en
    millisecondes serait fragile d'une machine à l'autre.
    """
    from tortoisepy.core.changes import list_changes

    w = tmp_path / "w"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "modifie.txt").write_text("origine\n")
    (w / "supprime.txt").write_text("a supprimer\n")
    (w / "intact.txt").write_text("ne bouge pas\n")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "base")

    (w / "modifie.txt").write_text("nouvelle version\n")
    (w / "supprime.txt").unlink()
    (w / "nouveau.txt").write_text("jamais commité\n")
    (w / "indexe.txt").write_text("ajouté à l'index\n")
    _git(w, "add", "indexe.txt")

    chemins = {c.path for c in list_changes(pygit2.Repository(str(w)))}

    assert "modifie.txt" in chemins, chemins
    assert "supprime.txt" in chemins, chemins
    assert "nouveau.txt" in chemins, chemins
    assert "indexe.txt" in chemins, chemins
    assert "intact.txt" not in chemins, "un fichier intact ne doit pas figurer"


def test_a_staged_then_modified_file_appears_once(tmp_path):
    """Le piège de la fusion de deux diffs : un fichier indexé PUIS
    modifié apparaît dans les deux, il ne doit pas être dupliqué."""
    from tortoisepy.core.changes import list_changes

    w = tmp_path / "w"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "f.txt").write_text("origine\n")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "base")

    (w / "f.txt").write_text("version indexée\n")
    _git(w, "add", "f.txt")
    (w / "f.txt").write_text("version du disque\n")

    chemins = [c.path for c in list_changes(pygit2.Repository(str(w)))]
    assert chemins.count("f.txt") == 1, chemins


def test_diff_for_still_shows_the_working_version(tmp_path):
    """Le diff affiché doit refléter le DISQUE, pas l'index.

    C'est ce que l'utilisateur s'apprête à commiter s'il stage tout.
    """
    from tortoisepy.core.changes import diff_for

    w = tmp_path / "w"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "f.txt").write_text("origine\n")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "base")
    (w / "f.txt").write_text("texte du disque\n")

    diff = diff_for(pygit2.Repository(str(w)), "f.txt")
    lignes = [l.content for h in diff.hunks for l in h.lines]
    assert any("texte du disque" in l for l in lignes), lignes
