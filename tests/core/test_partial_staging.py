"""Commiter une partie des changements d'un fichier — `git add -p`.

Demandé par l'utilisateur, et annoncé par le README comme « the biggest
gap ». Commiter un fichier entier force à mélanger deux changements sans
rapport, ou à sortir au terminal — ce qui annule l'intérêt de
l'application.

Le principe : le contenu à commiter se compose depuis **HEAD**, pas
depuis le disque. On part de la version HEAD et on applique uniquement
les hunks retenus ; les autres restent dans l'arbre de travail, non
commités.

La garantie §5 tient sans effort : `commit_selection` bâtit déjà un index
**temporaire en mémoire** et ne touche jamais celui de l'utilisateur.
Aucun index partiel n'est écrit sur disque.
"""

from __future__ import annotations

import subprocess

import pygit2
import pytest

from tortoisepy.core.changes import diff_for
from tortoisepy.core.staging import compose_partial_content

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
def depot(tmp_path):
    """Un fichier de 20 lignes, modifié à DEUX endroits éloignés.

    C'est le cas qui motive la fonctionnalité : deux changements sans
    rapport dans le même fichier, qu'on veut commiter séparément.

        ligne 3  -> modifiée   (hunk 0)
        ligne 18 -> modifiée   (hunk 1)
    """
    w = tmp_path / "w"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    cible = w / "module.py"
    cible.write_text("".join(f"ligne {i}\n" for i in range(1, 21)))
    _git(w, "add", ".")
    _git(w, "commit", "-qm", "base")

    lignes = cible.read_text().splitlines(keepends=True)
    lignes[2] = "LIGNE TROIS MODIFIEE\n"
    lignes[17] = "LIGNE DIX-HUIT MODIFIEE\n"
    cible.write_text("".join(lignes))

    return pygit2.Repository(str(w))


def _hunks(repo, chemin="module.py"):
    return diff_for(repo, chemin).hunks


# --- le cas qui motive la fonctionnalité ---------------------------------


def test_two_distant_changes_give_two_hunks(depot):
    """La prémisse : sans deux hunks, il n'y a rien à choisir."""
    assert len(_hunks(depot)) == 2


def test_keeping_the_first_hunk_only(depot):
    """L'assertion centrale : un seul des deux changements est retenu."""
    contenu = compose_partial_content(depot, "module.py", _hunks(depot)[:1])

    assert "LIGNE TROIS MODIFIEE" in contenu
    assert "LIGNE DIX-HUIT MODIFIEE" not in contenu, (
        "le hunk écarté a été appliqué quand même"
    )
    assert "ligne 18" in contenu, "la version HEAD de la ligne 18 doit rester"


def test_keeping_the_second_hunk_only(depot):
    """Et l'autre sens : le décalage des lignes ne doit rien casser.

    Le piège : écarter le premier hunk décale tout ce qui suit. Appliquer
    le second sans tenir compte de ce décalage produit un fichier
    corrompu — silencieusement.
    """
    contenu = compose_partial_content(depot, "module.py", _hunks(depot)[1:])

    assert "LIGNE DIX-HUIT MODIFIEE" in contenu
    assert "LIGNE TROIS MODIFIEE" not in contenu
    assert "ligne 3" in contenu


def test_keeping_both_hunks_equals_the_working_file(depot):
    """Tout retenir doit redonner le fichier tel qu'il est sur disque.

    C'est la vérification la plus forte : si la composition est juste
    pour l'ensemble, le mécanisme est sain.
    """
    contenu = compose_partial_content(depot, "module.py", _hunks(depot))
    disque = (
        depot.workdir + "module.py"
    )
    with open(disque) as fichier:
        assert contenu == fichier.read()


def test_keeping_no_hunk_gives_the_head_version(depot):
    """Ne rien retenir revient à ne rien commiter pour ce fichier."""
    contenu = compose_partial_content(depot, "module.py", ())

    assert "LIGNE TROIS MODIFIEE" not in contenu
    assert "LIGNE DIX-HUIT MODIFIEE" not in contenu
    assert contenu.count("\n") == 20


# --- lignes ajoutées et supprimées ---------------------------------------


@pytest.fixture
def depot_ajout_suppression(tmp_path):
    """Un hunk qui AJOUTE des lignes, un autre qui en SUPPRIME.

    Une modification simple garde le même nombre de lignes ; ces deux
    cas-là décalent le fichier, et c'est là que les erreurs se nichent.
    """
    w = tmp_path / "w2"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    cible = w / "f.txt"
    cible.write_text("".join(f"L{i}\n" for i in range(1, 21)))
    _git(w, "add", ".")
    _git(w, "commit", "-qm", "base")

    lignes = cible.read_text().splitlines(keepends=True)
    lignes.insert(2, "AJOUTEE A\nAJOUTEE B\n")   # après L2
    del lignes[16]                                # supprime une ligne tardive
    cible.write_text("".join(lignes))

    return pygit2.Repository(str(w))


def test_an_added_hunk_can_be_kept_alone(depot_ajout_suppression):
    """Un hunk qui ajoute des lignes décale tout ce qui suit."""
    hunks = diff_for(depot_ajout_suppression, "f.txt").hunks
    contenu = compose_partial_content(
        depot_ajout_suppression, "f.txt", hunks[:1]
    )

    assert "AJOUTEE A" in contenu
    assert contenu.count("\n") == 22, (
        f"20 lignes + 2 ajoutées attendues, obtenu {contenu.count(chr(10))}"
    )


def test_a_removed_hunk_can_be_kept_alone(depot_ajout_suppression):
    """Un hunk qui supprime : le fichier doit rétrécir d'autant."""
    hunks = diff_for(depot_ajout_suppression, "f.txt").hunks
    contenu = compose_partial_content(
        depot_ajout_suppression, "f.txt", hunks[1:]
    )

    assert contenu.count("\n") == 19, (
        f"20 lignes - 1 supprimée attendues, obtenu {contenu.count(chr(10))}"
    )
    assert "AJOUTEE A" not in contenu


# --- cas limites ---------------------------------------------------------


def test_a_file_absent_from_head_is_refused(tmp_path):
    """Un fichier non suivi n'a pas de version HEAD d'où partir.

    L'interface doit alors garder le tout-ou-rien : composer depuis rien
    n'a pas de sens, et rendre un contenu partiel tromperait.
    """
    w = tmp_path / "neuf"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "base.txt").write_text("a\n")
    _git(w, "add", ".")
    _git(w, "commit", "-qm", "base")
    (w / "nouveau.txt").write_text("neuf\n")

    repo = pygit2.Repository(str(w))
    with pytest.raises(ValueError):
        compose_partial_content(repo, "nouveau.txt", ())


def test_a_file_without_trailing_newline_is_preserved(tmp_path):
    """Ne rien ajouter au fichier de l'utilisateur.

    L'absence de fin de ligne est parfois significative, et git la
    signale explicitement — en ajouter une modifierait le fichier au-delà
    de ce qui a été demandé.
    """
    w = tmp_path / "sansfin"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    cible = w / "f.txt"
    cible.write_text("un\ndeux\ntrois")      # pas de \n final
    _git(w, "add", ".")
    _git(w, "commit", "-qm", "base")
    cible.write_text("un\nDEUX\ntrois")

    repo = pygit2.Repository(str(w))
    hunks = diff_for(repo, "f.txt").hunks
    contenu = compose_partial_content(repo, "f.txt", hunks)

    assert contenu == "un\nDEUX\ntrois", f"contenu altéré : {contenu!r}"


def test_the_repository_is_not_modified(depot):
    """§7.0 : composer est une lecture, rien ne doit bouger.

    Ni l'index de l'utilisateur, ni les refs, ni le fichier sur disque.
    """
    index_avant = [e.path for e in depot.index]
    refs_avant = {r: str(depot.references[r].target) for r in depot.references}
    with open(depot.workdir + "module.py") as fichier:
        disque_avant = fichier.read()

    compose_partial_content(depot, "module.py", _hunks(depot)[:1])

    assert [e.path for e in depot.index] == index_avant
    assert {
        r: str(depot.references[r].target) for r in depot.references
    } == refs_avant
    with open(depot.workdir + "module.py") as fichier:
        assert fichier.read() == disque_avant, "le disque a été modifié"


def test_hunks_out_of_order_are_handled(depot):
    """Les hunks peuvent arriver dans n'importe quel ordre.

    L'interface les donne dans l'ordre d'affichage, mais rien ne le
    garantit — et les appliquer à l'envers corromprait le fichier.
    """
    hunks = _hunks(depot)
    contenu = compose_partial_content(
        depot, "module.py", (hunks[1], hunks[0])
    )

    assert "LIGNE TROIS MODIFIEE" in contenu
    assert "LIGNE DIX-HUIT MODIFIEE" in contenu


# --- le décalage : le piège central -------------------------------------


@pytest.fixture
def depot_decalage(tmp_path):
    """Un hunk PRÉCOCE qui change le nombre de lignes, un hunk TARDIF.

    Sans cela, l'ordre d'application n'a aucune importance : des hunks
    qui remplacent 6 lignes par 6 laissent les positions inchangées.
    Trouvé par mutation — appliquer du début vers la fin, ou ne pas
    trier du tout, passait inaperçu.

    Ici le premier hunk ajoute 3 lignes : tout ce qui suit est décalé, et
    appliquer le second à sa position d'origine écraserait les mauvaises
    lignes.
    """
    w = tmp_path / "decalage"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    cible = w / "f.txt"
    cible.write_text("".join(f"L{i}\n" for i in range(1, 31)))
    _git(w, "add", ".")
    _git(w, "commit", "-qm", "base")

    lignes = cible.read_text().splitlines(keepends=True)
    lignes[25] = "TARDIF MODIFIE\n"                       # L26
    lignes.insert(2, "PRECOCE A\nPRECOCE B\nPRECOCE C\n")  # +3 lignes
    cible.write_text("".join(lignes))

    return pygit2.Repository(str(w))


def test_an_early_insertion_does_not_shift_a_later_hunk(depot_decalage):
    """L'assertion qui manquait : les deux hunks, l'un décalant l'autre.

    Si l'application ne part pas de la fin, le hunk tardif écrit aux
    mauvaises lignes et le fichier est corrompu **en silence**.
    """
    hunks = diff_for(depot_decalage, "f.txt").hunks
    assert len(hunks) == 2, "le dépôt doit produire deux hunks"

    contenu = compose_partial_content(depot_decalage, "f.txt", hunks)

    with open(depot_decalage.workdir + "f.txt") as fichier:
        assert contenu == fichier.read(), (
            "tout retenir doit redonner le fichier du disque"
        )


def test_the_later_hunk_lands_on_the_right_lines(depot_decalage):
    """Vérification ligne à ligne, pour nommer la corruption si elle revient."""
    hunks = diff_for(depot_decalage, "f.txt").hunks
    contenu = compose_partial_content(depot_decalage, "f.txt", hunks)
    lignes = contenu.splitlines()

    assert lignes[2:5] == ["PRECOCE A", "PRECOCE B", "PRECOCE C"]
    # L26 d'origine, décalée de 3 par l'insertion précoce.
    assert lignes[28] == "TARDIF MODIFIE", (
        f"le hunk tardif a atterri au mauvais endroit : {lignes[26:31]}"
    )
    assert lignes[-1] == "L30", "la fin du fichier a été abîmée"


def test_keeping_only_the_later_hunk_after_a_shift(depot_decalage):
    """Et le cas inverse : écarter le hunk précoce.

    Le fichier garde alors ses 30 lignes, avec la seule modification
    tardive — exactement ce que `git add -p` produirait.
    """
    hunks = diff_for(depot_decalage, "f.txt").hunks
    contenu = compose_partial_content(depot_decalage, "f.txt", hunks[1:])
    lignes = contenu.splitlines()

    assert len(lignes) == 30, f"{len(lignes)} lignes au lieu de 30"
    assert "PRECOCE A" not in contenu
    assert lignes[25] == "TARDIF MODIFIE"


# --- jusqu'au commit -----------------------------------------------------


def test_committing_only_one_hunk(depot):
    """Le bout de la chaîne : `git add -p` puis `git commit`.

    Le commit ne doit porter QUE le hunk retenu ; l'autre modification
    reste dans l'arbre de travail, prête pour un commit suivant.
    """
    from tortoisepy.core.operations import commit_selection

    hunks = _hunks(depot)
    resultat = commit_selection(
        depot, ("module.py",), "fix: seulement le premier bloc",
        partial={"module.py": hunks[:1]},
    )

    assert resultat.success, resultat.git_error

    commite = depot.revparse_single("HEAD").tree["module.py"]
    contenu = depot.get(commite.id).data.decode()
    assert "LIGNE TROIS MODIFIEE" in contenu
    assert "LIGNE DIX-HUIT MODIFIEE" not in contenu, (
        "le hunk écarté a été commité quand même"
    )


def test_the_other_hunk_survives_in_the_working_tree(depot):
    """Ce qui n'est pas commité ne doit pas être perdu.

    C'est la garantie qui rend la fonctionnalité utilisable : on commite
    un morceau, on garde le reste sous la main.
    """
    from tortoisepy.core.operations import commit_selection

    commit_selection(
        depot, ("module.py",), "fix: premier bloc",
        partial={"module.py": _hunks(depot)[:1]},
    )

    with open(depot.workdir + "module.py") as fichier:
        disque = fichier.read()
    assert "LIGNE DIX-HUIT MODIFIEE" in disque, (
        "le hunk non commité a disparu de l'arbre de travail"
    )


def test_a_second_commit_takes_the_rest(depot):
    """Et l'enchaînement : deux commits propres au lieu d'un fourre-tout."""
    from tortoisepy.core.operations import commit_selection

    commit_selection(
        depot, ("module.py",), "fix: premier bloc",
        partial={"module.py": _hunks(depot)[:1]},
    )
    second = commit_selection(depot, ("module.py",), "refactor: second bloc")

    assert second.success, second.git_error
    commite = depot.revparse_single("HEAD").tree["module.py"]
    contenu = depot.get(commite.id).data.decode()
    assert "LIGNE TROIS MODIFIEE" in contenu
    assert "LIGNE DIX-HUIT MODIFIEE" in contenu


def test_without_partial_the_whole_file_is_committed(depot):
    """Le cas courant ne change pas : sans hunks, tout le fichier passe.

    Le piège serait qu'ajouter l'option modifie le chemin éprouvé.
    """
    from tortoisepy.core.operations import commit_selection

    resultat = commit_selection(depot, ("module.py",), "tout le fichier")

    assert resultat.success, resultat.git_error
    commite = depot.revparse_single("HEAD").tree["module.py"]
    contenu = depot.get(commite.id).data.decode()
    assert "LIGNE TROIS MODIFIEE" in contenu
    assert "LIGNE DIX-HUIT MODIFIEE" in contenu


def test_a_partial_file_not_selected_is_ignored(depot):
    """Un fichier décoché reste décoché, quels que soient ses hunks.

    La case par fichier garde le dernier mot (demandé par
    l'utilisateur) : l'inverse serait déroutant.
    """
    from tortoisepy.core.operations import commit_selection

    (lambda p: open(p, "a").write("\n"))(depot.workdir + "autre.txt")
    resultat = commit_selection(
        depot, ("autre.txt",), "autre fichier",
        partial={"module.py": _hunks(depot)[:1]},
    )

    assert resultat.success, resultat.git_error
    commite = depot.revparse_single("HEAD").tree["module.py"]
    contenu = depot.get(commite.id).data.decode()
    assert "LIGNE TROIS MODIFIEE" not in contenu, (
        "un fichier non coché a été commité via `partial`"
    )


def test_the_user_index_is_left_alone(depot):
    """§5 : l'index préparé au terminal ne doit pas bouger."""
    from tortoisepy.core.operations import commit_selection

    avant = [(e.path, str(e.id)) for e in depot.index]

    commit_selection(
        depot, ("module.py",), "partiel",
        partial={"module.py": _hunks(depot)[:1]},
    )

    assert [(e.path, str(e.id)) for e in depot.index] == avant
