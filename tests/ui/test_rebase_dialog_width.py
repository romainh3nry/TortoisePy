"""La fenêtre de rebase doit montrer les noms de branche en entier.

Signalé par l'utilisateur, capture à l'appui : la liste proposait
« CRM-3933_rate_li… » et deux fois « origin/CRM-3933_… ». Des branches
qui partagent un préfixe deviennent indistinguables — et choisir la
mauvaise cible de rebase n'est pas une erreur anodine.

Deux causes distinctes, qu'il faut traiter toutes les deux :

  - la **fenêtre** n'avait aucune largeur fixée, donc Qt la réduisait au
    minimum de ses champs ;
  - le **popup** du complèteur se cale par défaut sur la largeur du
    champ, même quand la fenêtre est large.
"""

from __future__ import annotations

import pytest

from tortoisepy.ui.dialogs import RebaseDialog

LONGUES = (
    "CRM-3933_rate_limit",
    "origin/CRM-3933_rate_limit",
    "origin/CRM-3933_rate_limit_bis",
    "feature/CRM-3935-2fa-email-login",
)


@pytest.fixture
def fenetre(qtbot):
    f = RebaseDialog(
        None,
        current_branch="feature/CRM-3935-2fa-email-login",
        local_branches=LONGUES,
        targets=LONGUES,
    )
    qtbot.addWidget(f)
    return f


def test_the_dialog_is_wide_enough_for_long_names(fenetre):
    """L'assertion centrale : la fenêtre ne doit plus se réduire au minimum.

    Mesuré avant correction, elle s'ouvrait autour de 300 px — de quoi
    tronquer « origin/CRM-3933_rate_limit » dès le préfixe du remote.
    """
    assert fenetre.width() >= 520, (
        f"fenêtre trop étroite : {fenetre.width()} px"
    )


def test_the_popup_shows_the_longest_name_in_full(qtbot, fenetre):
    """Le popup se cale sur le CHAMP, pas sur la fenêtre.

    C'est la seconde cause, invisible tant qu'on ne regarde que la
    fenêtre : l'élargir ne suffisait pas, la liste restait étroite.
    """
    from PySide6.QtGui import QFontMetrics

    popup = fenetre.target_field().completer().popup()
    metriques = QFontMetrics(popup.font())
    requis = max(metriques.horizontalAdvance(nom) for nom in LONGUES)

    assert popup.minimumWidth() >= requis, (
        f"popup de {popup.minimumWidth()} px pour {requis} px de texte : "
        "les noms longs seront tronqués"
    )


def test_both_fields_get_the_treatment(qtbot, fenetre):
    """« Replay » souffre du même défaut que « Onto ».

    Le piège : ne corriger que le champ de la capture et laisser
    l'autre tronquer.
    """
    for champ in (fenetre.replay_field(), fenetre.target_field()):
        assert champ.completer().popup().minimumWidth() > 0, (
            "un des deux champs n'a pas de largeur de popup imposée"
        )


def test_short_names_do_not_force_a_huge_popup(qtbot):
    """Un dépôt aux noms courts ne doit pas hériter d'une liste démesurée.

    La largeur suit le contenu : imposer une valeur fixe généreuse
    règlerait la capture mais donnerait une liste absurde ailleurs.
    """
    f = RebaseDialog(
        None, current_branch="main",
        local_branches=("main", "dev"), targets=("main", "dev"),
    )
    qtbot.addWidget(f)

    assert f.target_field().completer().popup().minimumWidth() < 400


def test_the_dialog_can_still_be_resized_down(fenetre):
    """Une largeur de départ, pas un minimum rigide.

    Imposer `setMinimumWidth` empêcherait l'utilisateur de rétrécir la
    fenêtre sur un petit écran.
    """
    fenetre.resize(360, fenetre.height())
    assert fenetre.width() == 360


def test_the_completion_still_works(qtbot, fenetre):
    """Élargir ne doit rien changer au filtrage.

    `MatchContains` : saisir « rate » doit proposer les trois branches
    qui le contiennent, préfixe `origin/` compris.
    """
    completeur = fenetre.target_field().completer()
    completeur.setCompletionPrefix("rate")

    proposes = {
        completeur.completionModel().index(i, 0).data()
        for i in range(completeur.completionCount())
    }
    assert "CRM-3933_rate_limit" in proposes
    assert "origin/CRM-3933_rate_limit" in proposes


def test_the_popup_is_never_narrower_than_its_field(qtbot):
    """Une liste plus étroite que le champ qu'elle complète est bancale.

    `minimumWidth` n'est qu'un plancher : il garantit que les noms longs
    tiennent, pas que la liste s'aligne sur le champ. Mesuré, le popup
    tombait à 228 px sous un champ de 488 px quand les noms étaient
    courts.
    """
    noms = ("CRM-3933_rate_limit", "origin/CRM-3933_rate_limit_bis")
    f = RebaseDialog(
        None, current_branch="main", local_branches=noms, targets=noms
    )
    qtbot.addWidget(f)
    f.show()

    champ = f.target_field()
    popup = champ.completer().popup()

    assert popup.minimumWidth() >= champ.width(), (
        f"popup de {popup.minimumWidth()} px sous un champ de "
        f"{champ.width()} px"
    )


def test_the_fields_are_long_enough_for_a_branch_name(qtbot, fenetre):
    """Demandé par l'utilisateur : « les inputs doivent être plus longs ».

    Un champ doit afficher un nom de branche entier sans défilement, sinon
    on ne relit pas ce qu'on a saisi avant de valider un rebase.
    """
    from PySide6.QtGui import QFontMetrics

    fenetre.show()
    metriques = QFontMetrics(fenetre.replay_field().font())
    requis = max(metriques.horizontalAdvance(nom) for nom in LONGUES)

    for champ in (fenetre.replay_field(), fenetre.target_field()):
        assert champ.width() >= requis + 20, (
            f"champ de {champ.width()} px pour {requis} px de texte"
        )


def test_the_prefilled_name_is_readable_from_its_start(qtbot, fenetre):
    """Le champ « Replay » affichait « 935-2fa-email-login ».

    Signalé par l'utilisateur, capture à l'appui : le texte pré-rempli
    était coupé AU DÉBUT, parce que le curseur se place à la fin et que
    la vue suit le curseur. On voyait donc la queue du nom, alors que
    c'est son début qui l'identifie (`feature/`, `origin/`…).
    """
    fenetre.show()
    champ = fenetre.replay_field()

    assert champ.cursorPosition() == 0, (
        "le curseur en fin de texte fait défiler le champ et masque le "
        "début du nom"
    )


def test_the_fields_are_labelled_branch_and_onto(qtbot, fenetre):
    """« Branch » plutôt que « Replay », demandé par l'utilisateur.

    « Replay » décrivait correctement ce que fait un rebase — rejouer des
    commits — mais le mot n'existe nulle part dans la CLI git, et
    TortoiseGit, dont cette application est un clone, dit « Branch ».

    « Onto » est gardé : c'est le mot de git (`git rebase --onto`), il
    dit la direction, et « Upstream » désignerait d'habitude la branche
    de suivi distante — pas la cible d'un rebase.
    """
    etiquettes = fenetre.field_labels()

    assert etiquettes == ("Branch:", "Onto:"), (
        f"libellés inattendus : {etiquettes}"
    )
