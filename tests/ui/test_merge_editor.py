"""L'éditeur de fusion : yours | résultat | theirs.

Demandé par l'utilisateur, capture à l'appui, après un rebase dans `vti`
où deux clés YAML indépendantes — `rate-limit:` et `twoFactorAuth:` —
étaient marquées en conflit parce qu'adjacentes :

    « j'aimerai que les deux blocs qui causent le conflit soient
      présents, sauf qu'en l'état on me propose uniquement l'un ou
      l'autre »

    « il faudrait qu'on puisse modifier le fichier en question avec une
      colonne avec les modifs yours, une autre les modifs theirs et au
      milieu le fichier final »

Les deux côtés sont en LECTURE SEULE : ce sont des références, et les
rendre modifiables laisserait croire qu'on peut y écrire. Seule la
colonne du milieu s'édite — c'est elle qui sera écrite.
"""

from __future__ import annotations

import os
import subprocess

import pygit2
import pytest

from tortoisepy.ui.merge_editor import MergeEditor

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
    """Le conflit de l'utilisateur, en miniature."""
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

    _git(w, "merge", "autre", check=False)

    repo = pygit2.Repository(str(w))
    assert repo.index.conflicts is not None
    return repo


@pytest.fixture
def editeur(qtbot, depot):
    e = MergeEditor(depot, "conf.yml")
    qtbot.addWidget(e)
    return e


# --- les trois colonnes --------------------------------------------------


def test_the_two_sides_are_shown(editeur):
    """L'assertion centrale : voir les deux, pas choisir entre les deux."""
    assert "rate-limit" in editeur.ours_view.toPlainText()
    assert "twoFactorAuth" in editeur.theirs_view.toPlainText()


def test_the_sides_are_read_only(editeur):
    """Les rendre modifiables laisserait croire qu'on peut y écrire.

    Ce sont des références : seule la colonne du milieu est écrite.
    """
    assert editeur.ours_view.isReadOnly()
    assert editeur.theirs_view.isReadOnly()


def test_the_result_is_editable(editeur):
    """C'est le seul endroit où l'utilisateur compose."""
    assert not editeur.result_view.isReadOnly()


def test_the_columns_are_labelled(editeur):
    """Sans étiquette, on ne sait pas quel côté est lequel.

    L'utilisateur l'avait déjà signalé sur l'ancienne fenêtre : « on ne
    sait pas de quelle version appartiennent ces changements ».
    """
    etiquettes = editeur.column_labels()
    assert len(etiquettes) == 3
    assert any("your" in e.lower() or "mine" in e.lower() for e in etiquettes)
    assert any("their" in e.lower() for e in etiquettes)


# --- point de départ de la composition -----------------------------------


def test_the_result_starts_from_the_conflicted_file(editeur):
    """Le fichier de travail porte déjà les marqueurs de git.

    Partir de là plutôt que du vide : l'utilisateur voit le contexte
    complet, y compris les parties sans conflit, qu'il ne doit surtout
    pas avoir à retaper.
    """
    texte = editeur.result_view.toPlainText()
    assert "commun: 1" in texte, (
        "les parties non conflictuelles doivent être présentes"
    )


def test_the_markers_can_be_cleared(editeur):
    """Un bouton pour retirer les marqueurs en gardant les deux blocs.

    C'est exactement le geste demandé : les deux côtés présents, sans
    les `<<<<<<<` que git a insérés.
    """
    editeur.keep_both()
    texte = editeur.result_view.toPlainText()

    assert "rate-limit" in texte
    assert "twoFactorAuth" in texte
    assert "<<<<<<<" not in texte
    assert "=======" not in texte
    assert ">>>>>>>" not in texte


def test_keeping_both_preserves_the_common_part(editeur):
    """Le piège : ne garder que les blocs en conflit et perdre le reste."""
    editeur.keep_both()
    assert "commun: 1" in editeur.result_view.toPlainText()


# --- insertion depuis un côté -------------------------------------------


def test_a_side_can_be_taken_as_a_whole(editeur):
    """Repartir d'un camp, puis le retoucher, reste utile."""
    editeur.take_ours()
    texte = editeur.result_view.toPlainText()

    assert "rate-limit" in texte
    assert "twoFactorAuth" not in texte


def test_taking_theirs_replaces_the_result(editeur):
    """Et l'autre sens, sans accumuler les deux appels."""
    editeur.take_ours()
    editeur.take_theirs()
    texte = editeur.result_view.toPlainText()

    assert "twoFactorAuth" in texte
    assert "rate-limit" not in texte, "les deux camps se sont accumulés"


# --- enregistrement ------------------------------------------------------


def test_saving_resolves_the_conflict(qtbot, editeur, depot):
    """Le geste final : ce qui est au milieu devient le fichier."""
    from tortoisepy.core.conflicts import list_conflicts

    editeur.result_view.setPlainText("compose a la main\n")
    editeur.save()

    assert list_conflicts(depot) == ()
    chemin = os.path.join(depot.workdir, "conf.yml")
    assert open(chemin).read() == "compose a la main\n"


def test_saving_emits_the_resolution(qtbot, editeur):
    """La fenêtre appelante doit pouvoir se rafraîchir."""
    vus = []
    editeur.resolved.connect(vus.append)

    editeur.result_view.setPlainText("x\n")
    editeur.save()

    assert vus == ["conf.yml"]


def test_saving_with_markers_left_is_refused(qtbot, editeur, monkeypatch):
    """Garder un `<<<<<<<` dans le fichier est presque toujours une erreur.

    git lui-même refuse de commiter un fichier qui en contient. Le dire
    ici, où la correction est à portée, vaut mieux que de laisser
    découvrir l'erreur au commit.
    """
    from tortoisepy.ui import merge_editor as module
    from tortoisepy.core.conflicts import list_conflicts

    avertissements = []
    monkeypatch.setattr(
        module, "show_error", lambda parent, r: avertissements.append(r)
    )

    editeur.result_view.setPlainText(
        "<<<<<<< ours\na\n=======\nb\n>>>>>>> theirs\n"
    )
    editeur.save()

    assert avertissements, "aucun avertissement sur les marqueurs restants"
    assert list_conflicts(editeur.repository) != (), (
        "le conflit a été résolu malgré les marqueurs"
    )


def test_an_empty_result_is_allowed(qtbot, editeur, depot):
    """Vider le fichier est une résolution légitime : tout retirer.

    Le piège : confondre « vide » et « rien saisi », et refuser un geste
    volontaire.
    """
    from tortoisepy.core.conflicts import list_conflicts

    editeur.result_view.setPlainText("")
    editeur.save()

    assert list_conflicts(depot) == ()


# --- cas limites ---------------------------------------------------------


def test_a_path_without_conflict_opens_empty(qtbot, depot):
    """Ouvrir sur un chemin sans conflit ne doit pas planter."""
    editeur = MergeEditor(depot, "jamais-vu.yml")
    qtbot.addWidget(editeur)

    assert editeur.ours_view.toPlainText() == ""
    assert editeur.theirs_view.toPlainText() == ""


def test_the_title_names_the_file(editeur):
    """Plusieurs fichiers peuvent être en conflit : dire lequel on édite."""
    assert "conf.yml" in editeur.windowTitle()


# --- accès depuis la fenêtre de conflits ---------------------------------


def test_the_conflict_window_offers_the_editor(qtbot, depot):
    """L'éditeur doit être atteignable, sinon il n'existe pas."""
    from tortoisepy.ui.conflict_window import ConflictWindow

    fenetre = ConflictWindow(depot)
    qtbot.addWidget(fenetre)

    assert hasattr(fenetre, "edit_button")
    assert fenetre.edit_button.isEnabled(), (
        "le bouton doit être actif quand un conflit reste"
    )


def test_opening_the_editor_targets_the_selected_file(qtbot, depot):
    """Avec plusieurs fichiers, c'est celui qu'on a choisi qu'on édite."""
    from tortoisepy.ui.conflict_window import ConflictWindow

    fenetre = ConflictWindow(depot)
    qtbot.addWidget(fenetre)
    fenetre.select_file("conf.yml")

    fenetre.edit_conflict()

    assert fenetre.merge_editors, "aucun éditeur ouvert"
    assert fenetre.merge_editors[-1].path == "conf.yml"


def test_the_editor_is_retained(qtbot, depot):
    """Sans référence, le ramasse-miettes le ferme aussitôt ouvert."""
    from tortoisepy.ui.conflict_window import ConflictWindow

    fenetre = ConflictWindow(depot)
    qtbot.addWidget(fenetre)
    fenetre.select_file("conf.yml")
    fenetre.edit_conflict()

    assert fenetre.merge_editors[-1].isVisible()


def test_resolving_in_the_editor_refreshes_the_window(qtbot, depot):
    """La liste des conflits doit se vider une fois le fichier résolu."""
    from tortoisepy.ui.conflict_window import ConflictWindow

    fenetre = ConflictWindow(depot)
    qtbot.addWidget(fenetre)
    assert fenetre.file_count() == 1

    fenetre.select_file("conf.yml")
    fenetre.edit_conflict()
    editeur = fenetre.merge_editors[-1]
    editeur.result_view.setPlainText("resolu\n")
    editeur.save()

    assert fenetre.file_count() == 0, (
        "la fenêtre n'a pas été rafraîchie après la résolution"
    )


def test_the_editor_uses_the_side_labels_of_the_window(qtbot, depot):
    """En rebase, « ours » et « theirs » sont inversés par rapport au merge.

    La fenêtre de conflits le sait déjà et nomme ses boutons en
    conséquence. L'éditeur doit hériter de ces mêmes noms, sinon il
    dirait le contraire à deux centimètres d'écart.
    """
    from tortoisepy.ui.conflict_window import ConflictWindow

    fenetre = ConflictWindow(depot)
    qtbot.addWidget(fenetre)
    fenetre.select_file("conf.yml")
    fenetre.edit_conflict()

    etiquettes = fenetre.merge_editors[-1].column_labels()
    assert etiquettes[0] == fenetre.mine_button.text()
    assert etiquettes[2] == fenetre.theirs_button.text()


# --- couleurs et navigation par blocs ------------------------------------


def test_the_differing_lines_are_coloured(qtbot, depot):
    """Signalé par l'utilisateur : « là c'est tout noir/blanc et on voit
    mal les changements ».

    Les lignes propres à un camp prennent les couleurs du diff — les
    mêmes que la vue des commits, pour n'avoir qu'une grammaire visuelle
    à apprendre. Les lignes communes restent neutres : les surligner
    attirerait l'œil sur ce qui n'a pas changé.
    """
    from tortoisepy.ui import theme

    editeur = MergeEditor(depot, "conf.yml")
    qtbot.addWidget(editeur)

    couleurs = theme.diff_colors()
    fonds = _fonds_par_ligne(editeur.ours_view)

    # « rate-limit: » n'existe que de ce côté : il doit être coloré.
    assert couleurs["added_bg"] in fonds.values() or (
        couleurs["removed_bg"] in fonds.values()
    ), "aucune ligne colorée dans la colonne « ours »"


def test_the_common_lines_stay_neutral(qtbot, depot):
    """`commun: 1` est dans les deux camps : rien ne le distingue."""
    editeur = MergeEditor(depot, "conf.yml")
    qtbot.addWidget(editeur)

    fonds = _fonds_par_ligne(editeur.ours_view)
    commune = next(
        (texte for texte in fonds if "commun" in texte), None
    )
    assert commune is not None, "la ligne commune est absente"
    assert fonds[commune] is None, (
        "une ligne présente des deux côtés ne doit pas être surlignée"
    )


def _fonds_par_ligne(vue) -> dict:
    """Le fond de chaque ligne de la vue, indexé par son texte."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QTextCursor

    resultat = {}
    curseur = QTextCursor(vue.document())
    curseur.movePosition(QTextCursor.MoveOperation.Start)
    while True:
        bloc = curseur.block()
        # Le format est lu en SÉLECTIONNANT la ligne : `block.layout()`
        # ne porte pas les formats posés par curseur tant que la vue n'a
        # pas été peinte, ce qui n'arrive jamais en test offscreen.
        lecture = QTextCursor(bloc)
        lecture.select(QTextCursor.SelectionType.LineUnderCursor)
        arriere = lecture.charFormat().background()
        fond = (
            arriere.color()
            if arriere.style() != Qt.BrushStyle.NoBrush
            else None
        )
        resultat[bloc.text()] = fond
        if not curseur.movePosition(QTextCursor.MoveOperation.NextBlock):
            break
    return resultat


def test_both_sides_are_coloured(qtbot, depot):
    """Le piège : ne colorer qu'une colonne et laisser l'autre en noir."""
    from tortoisepy.ui import theme

    editeur = MergeEditor(depot, "conf.yml")
    qtbot.addWidget(editeur)

    # `QColor` n'est pas hachable : on compare sur le nom hexadécimal.
    couleurs = {
        c.name() for c in theme.diff_colors().values() if c is not None
    }
    for nom, vue in (
        ("ours", editeur.ours_view), ("theirs", editeur.theirs_view)
    ):
        fonds = {
            f.name() for f in _fonds_par_ligne(vue).values() if f is not None
        }
        assert fonds & couleurs, f"la colonne « {nom} » n'est pas colorée"


# --- flèches de bascule --------------------------------------------------


def test_arrows_send_a_side_to_the_middle(qtbot, depot):
    """Demandé : « des flèches pour basculer le code d'un côté au milieu ».

    La colonne du milieu est celle qui sera écrite : les flèches
    l'alimentent sans passer par le clavier.
    """
    editeur = MergeEditor(depot, "conf.yml")
    qtbot.addWidget(editeur)

    assert hasattr(editeur, "ours_arrow")
    assert hasattr(editeur, "theirs_arrow")


def test_the_arrow_appends_the_selected_lines(qtbot, depot):
    """Une sélection partielle doit pouvoir être reprise seule.

    C'est tout l'intérêt par rapport à « Take ours » : composer morceau
    par morceau, au lieu de tout remplacer.
    """
    editeur = MergeEditor(depot, "conf.yml")
    qtbot.addWidget(editeur)
    editeur.result_view.setPlainText("debut\n")

    editeur.select_in_ours(1, 2)      # la ligne « rate-limit: »
    editeur.send_ours_to_result()

    texte = editeur.result_view.toPlainText()
    assert texte.startswith("debut"), "le contenu existant a été écrasé"
    assert "rate-limit" in texte, "la sélection n'a pas été reprise"


def test_the_arrow_without_selection_sends_the_specific_lines(qtbot, depot):
    """Sans sélection, la flèche envoie ce qui est PROPRE à ce côté.

    Pas le côté entier : les lignes communes sont déjà dans le résultat,
    et les renvoyer les duplique. Mesuré avant correction sur le fichier
    réel de l'utilisateur, `myMTEmailCreation:` apparaissait deux fois
    après avoir cliqué les deux flèches — rendant le geste inutilisable.

    Ne rien faire ferait croire à un bouton cassé : on envoie donc les
    lignes colorées, celles-là mêmes que la vue désigne à l'œil.
    """
    editeur = MergeEditor(depot, "conf.yml")
    qtbot.addWidget(editeur)
    editeur.result_view.setPlainText("")

    editeur.send_theirs_to_result()

    texte = editeur.result_view.toPlainText()
    assert "twoFactorAuth" in texte
    assert "commun: 1" not in texte, (
        "la ligne commune a été renvoyée : elle sera dupliquée"
    )


def test_both_arrows_do_not_duplicate_the_common_part(qtbot, depot):
    """Le geste complet ne doit rien répéter.

    C'est le cas d'usage central : prendre les deux blocs en conflit,
    sans que le contexte commun apparaisse deux fois.
    """
    editeur = MergeEditor(depot, "conf.yml")
    qtbot.addWidget(editeur)
    editeur.keep_both()

    texte = editeur.result_view.toPlainText()
    assert texte.count("commun: 1") == 1, (
        f"partie commune dupliquée :\n{texte}"
    )


def test_arrows_can_compose_both_sides(qtbot, depot):
    """Le geste complet : prendre un bloc à gauche, un à droite.

    C'est exactement le cas signalé — deux clés YAML indépendantes que
    git marque en conflit parce qu'elles sont adjacentes.
    """
    editeur = MergeEditor(depot, "conf.yml")
    qtbot.addWidget(editeur)
    editeur.result_view.setPlainText("")

    editeur.send_ours_to_result()
    editeur.send_theirs_to_result()

    texte = editeur.result_view.toPlainText()
    assert "rate-limit" in texte
    assert "twoFactorAuth" in texte


# --- les marqueurs disparaissent dès la première flèche ------------------


def test_an_arrow_clears_the_conflict_markers(qtbot, depot):
    """Signalé par l'utilisateur, capture à l'appui : « quand on choisit
    un côté, on a encore les >>> qui indiquent le conflit ».

    Le résultat part du fichier de travail, marqueurs compris — c'est
    voulu, il porte le contexte complet. Mais dès qu'un côté est choisi,
    la zone en conflit est tranchée : garder les marqueurs laisse un
    fichier que git refusera de commiter, et que l'utilisateur doit
    nettoyer à la main.
    """
    editeur = MergeEditor(depot, "conf.yml")
    qtbot.addWidget(editeur)

    editeur.send_ours_to_result()

    texte = editeur.result_view.toPlainText()
    for marqueur in ("<<<<<<<", "=======", ">>>>>>>"):
        assert marqueur not in texte, (
            f"« {marqueur} » subsiste après avoir choisi un côté"
        )


def test_an_arrow_replaces_the_conflict_zone(qtbot, depot):
    """La flèche tranche le conflit, elle n'ajoute pas à la suite.

    Le défaut profond derrière les marqueurs : ajouter en fin de texte
    laissait LES DEUX camps dans le résultat, plus le bloc choisi — un
    contenu incohérent, où le camp écarté restait présent.
    """
    editeur = MergeEditor(depot, "conf.yml")
    qtbot.addWidget(editeur)

    editeur.send_ours_to_result()

    texte = editeur.result_view.toPlainText()
    assert "rate-limit" in texte, "le côté choisi est absent"
    assert "twoFactorAuth" not in texte, (
        "le côté écarté est resté dans le résultat"
    )


def test_the_second_arrow_adds_the_other_side(qtbot, depot):
    """Cliquer les deux flèches garde les deux : c'est le cas signalé.

    La première tranche le conflit, la seconde ajoute l'autre camp au
    même endroit — sans que le contexte commun soit dupliqué.
    """
    editeur = MergeEditor(depot, "conf.yml")
    qtbot.addWidget(editeur)

    editeur.send_ours_to_result()
    editeur.send_theirs_to_result()

    texte = editeur.result_view.toPlainText()
    assert "rate-limit" in texte
    assert "twoFactorAuth" in texte
    assert texte.count("commun: 1") == 1, f"contexte dupliqué :\n{texte}"
    assert "<<<<<<<" not in texte


def test_the_common_context_is_kept_by_an_arrow(qtbot, depot):
    """Trancher le conflit ne doit pas emporter le reste du fichier."""
    editeur = MergeEditor(depot, "conf.yml")
    qtbot.addWidget(editeur)

    editeur.send_ours_to_result()

    assert "commun: 1" in editeur.result_view.toPlainText(), (
        "les lignes hors conflit ont disparu"
    )
