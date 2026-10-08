from tortoisepy.core.results import failed, succeeded
from tortoisepy.core.state import RepositoryState
from tortoisepy.ui.dialogs import (
    ConfirmationRequest,
    confirmation_for,
    error_text,
)


def state(**overrides) -> RepositoryState:
    defaults = dict(
        head_oid="b" * 40,
        head_branch="master",
        detached=False,
        has_unstaged_changes=False,
        has_staged_changes=False,
        has_conflicts=False,
        operation_in_progress=None,
        conflicted_paths=(),
    )
    defaults.update(overrides)
    return RepositoryState(**defaults)


def test_hard_reset_always_needs_confirmation():
    """§7.5 : reset --hard détruit du travail."""
    request = confirmation_for("reset_to", "feature", state(), mode="hard")
    assert request is not None
    assert request.destructive is True


def test_soft_reset_is_not_destructive():
    request = confirmation_for("reset_to", "feature", state(), mode="soft")
    assert request is None or request.destructive is False


def test_branch_deletion_needs_confirmation():
    request = confirmation_for("delete_branch", "feature", state())
    assert request is not None
    assert "feature" in request.message


def test_checkout_on_a_clean_tree_needs_no_confirmation():
    assert confirmation_for("checkout_branch", "feature", state()) is None


def test_checkout_on_a_dirty_tree_warns():
    """§7.5 : toute opération avec des modifications non commitées."""
    request = confirmation_for(
        "checkout_branch", "feature", state(has_unstaged_changes=True)
    )
    assert request is not None
    assert "uncommitted" in request.message.lower()


def test_merge_on_a_dirty_tree_warns():
    request = confirmation_for(
        "merge_branch", "feature", state(has_staged_changes=True)
    )
    assert request is not None


def test_confirmation_names_what_is_lost():
    """Le dialogue doit dire ce qui sera perdu, pas seulement « confirmer ? »."""
    request = confirmation_for("reset_to", "abc1234", state(), mode="hard")
    assert len(request.message) > 30
    assert request.title


def test_creating_a_branch_needs_no_confirmation():
    assert confirmation_for("create_branch", "feature", state()) is None


def test_copying_a_hash_needs_no_confirmation():
    assert confirmation_for("copy_hash", "abc1234", state()) is None


def test_error_text_has_three_parts():
    """§9 : titre, contexte, message Git brut."""
    result = failed(
        "Fusion de « feature »", "1 conflict prevents checkout"
    )
    title, body = error_text(result)
    assert title
    assert "feature" in body
    assert "1 conflict prevents checkout" in body


def test_error_text_never_rewrites_the_git_message():
    """Le message de libgit2 est transmis mot pour mot."""
    raw = "cannot delete the currently checked out branch"
    _, body = error_text(failed("Suppression", raw))
    assert raw in body


def test_error_text_without_git_detail():
    _, body = error_text(failed("Opération", ""))
    assert body


def test_request_is_frozen():
    import pytest

    request = ConfirmationRequest(title="t", message="m", destructive=True)
    with pytest.raises(AttributeError):
        request.destructive = False


def test_the_completer_offers_every_branch(qtbot):
    from tortoisepy.ui.dialogs import _branch_completer

    completer = _branch_completer(["main", "develop", "origin/main"])
    completer.setCompletionPrefix("")
    propositions = {
        completer.completionModel().index(i, 0).data()
        for i in range(completer.completionCount())
    }
    assert {"main", "develop", "origin/main"} <= propositions


def test_the_completer_matches_anywhere_in_the_name(qtbot):
    """Saisir « main » doit aussi proposer « origin/main »."""
    from tortoisepy.ui.dialogs import _branch_completer

    completer = _branch_completer(["main", "develop", "origin/main"])
    completer.setCompletionPrefix("main")
    propositions = {
        completer.completionModel().index(i, 0).data()
        for i in range(completer.completionCount())
    }
    assert propositions == {"main", "origin/main"}


def test_the_completer_ignores_case(qtbot):
    from tortoisepy.ui.dialogs import _branch_completer

    completer = _branch_completer(["Develop"])
    completer.setCompletionPrefix("dev")
    assert completer.completionCount() == 1


def _ask_branch(monkeypatch, saisie, accepte=True, choices=None):
    """Joue `ask_branch` en simulant ce que l'utilisateur tape et clique."""
    from PySide6.QtWidgets import QInputDialog

    from tortoisepy.ui import dialogs

    def exec_simule(self):
        self.setTextValue(saisie)
        return (
            QInputDialog.DialogCode.Accepted
            if accepte
            else QInputDialog.DialogCode.Rejected
        )

    monkeypatch.setattr(QInputDialog, "exec", exec_simule)
    branches = ["main", "develop", "origin/main"] if choices is None else choices
    return dialogs.ask_branch(None, "Rebase", "Onto:", branches)


def test_ask_branch_returns_a_known_branch(qtbot, monkeypatch):
    assert _ask_branch(monkeypatch, "develop") == "develop"


def test_ask_branch_refuses_a_name_it_does_not_know(qtbot, monkeypatch):
    """Un nom libre atteindrait libgit2 et produirait un message opaque."""
    assert _ask_branch(monkeypatch, "nimporte-quoi") is None


def test_ask_branch_refuses_a_name_that_differs_only_by_case(
    qtbot, monkeypatch
):
    """L'autocomplétion ignore la casse ; l'acceptation non — git non plus."""
    assert _ask_branch(monkeypatch, "Main") is None


def test_ask_branch_trims_what_the_user_typed(qtbot, monkeypatch):
    assert _ask_branch(monkeypatch, "  main  ") == "main"


def test_ask_branch_returns_none_when_cancelled(qtbot, monkeypatch):
    assert _ask_branch(monkeypatch, "main", accepte=False) is None


def test_ask_branch_refuses_an_empty_input(qtbot, monkeypatch):
    assert _ask_branch(monkeypatch, "   ") is None


def test_ask_branch_accepts_a_one_shot_iterator(qtbot, monkeypatch):
    """`choices` est lu deux fois : un générateur ne doit pas tout rejeter."""
    branches = (n for n in ["main", "develop"])
    assert _ask_branch(monkeypatch, "develop", choices=branches) == "develop"


# --- Phase 19 : la fenêtre de rebase à deux champs -------------------------


def _fenetre(qtbot, courante="feature", locales=None, cibles=None):
    from tortoisepy.ui.dialogs import RebaseDialog

    f = RebaseDialog(
        None,
        current_branch=courante,
        local_branches=locales or ["feature", "main", "develop"],
        targets=cibles or ["main", "develop", "origin/main"],
    )
    qtbot.addWidget(f)
    return f


def test_the_dialog_preselects_the_current_branch(qtbot):
    """Demandé par l'utilisateur : la courante par défaut, modifiable."""
    f = _fenetre(qtbot)
    assert f.replayed() == "feature"


def test_the_replayed_branch_can_be_changed(qtbot):
    """D45 : c'est la moitié du besoin — pouvoir viser une autre branche."""
    f = _fenetre(qtbot)
    f.set_replayed("develop")
    assert f.replayed() == "develop"


def test_only_local_branches_can_be_replayed(qtbot):
    """Rebaser une branche distante n'a pas de sens : elle n'est pas à nous."""
    f = _fenetre(qtbot, cibles=["main", "origin/main"])
    assert "origin/main" not in f.replay_choices()
    assert "origin/main" in f.target_choices()


def test_the_warning_appears_for_another_branch(qtbot):
    """D46 : vérifié, le rebase bascule sur la branche rejouée."""
    f = _fenetre(qtbot)
    f.set_replayed("develop")
    assert f.switch_warning(), "l'utilisateur doit savoir qu'il changera de branche"
    assert "develop" in f.switch_warning()


def test_no_warning_for_the_current_branch(qtbot):
    """Toujours affiché, l'avertissement deviendrait invisible."""
    f = _fenetre(qtbot)
    f.set_replayed("feature")
    assert f.switch_warning() == ""


def test_an_unknown_name_is_refused(qtbot):
    """Le laisser passer donnerait une erreur libgit2 incompréhensible."""
    f = _fenetre(qtbot)
    f.set_replayed("nexiste-pas")
    assert f.replayed() is None


def test_rebasing_a_branch_onto_itself_is_refused(qtbot):
    f = _fenetre(qtbot)
    f.set_replayed("main")
    f.set_target("main")
    assert f.is_valid() is False


# --- icônes des boîtes de dialogue (crash macOS 27) ---------------------


def test_no_dialog_uses_a_system_standard_icon(qtbot):
    """Signalé : l'app se ferme au checkout sur un Mac sous macOS 27.

    La pile du rapport de crash est sans ambiguïté :

        QDialog::exec() -> -[NSAlert runModal]
          -> CUINamedVectorGlyph _rasterizeImageUsingScaleFactor:
            -> objc_exception_throw   ← abort()

    Qt demande l'icône standard au système ; sur macOS 27 son nouveau
    moteur de rendu (SwiftUI/RenderBox) lève une exception Objective-C
    que personne ne rattrape, et le processus est abandonné.

    Vérifié : les quatre icônes se résolvent sur macOS 15, d'où le
    « ça marche chez moi ». On fournit donc la nôtre.
    """
    from PySide6.QtWidgets import QMessageBox

    from tortoisepy.ui.dialogs import ConfirmationRequest, build_confirmation

    boite = build_confirmation(
        None, ConfirmationRequest("Titre", "Message", destructive=False)
    )
    qtbot.addWidget(boite)

    assert boite.icon() == QMessageBox.Icon.NoIcon, (
        "une icône standard est demandée au système : elle fait planter "
        "macOS 27"
    )


def test_the_dialog_still_shows_an_icon(qtbot):
    """Retirer l'icône système ne doit pas laisser la boîte nue.

    Le piège : corriger le crash en supprimant l'information. Un
    avertissement destructeur doit rester reconnaissable d'un coup
    d'œil.
    """
    from tortoisepy.ui.dialogs import ConfirmationRequest, build_confirmation

    boite = build_confirmation(
        None, ConfirmationRequest("Titre", "Message", destructive=True)
    )
    qtbot.addWidget(boite)

    assert not boite.iconPixmap().isNull(), "la boîte n'a plus d'icône"


def test_a_destructive_dialog_differs_from_a_question(qtbot):
    """Les deux ne doivent pas se ressembler.

    L'utilisateur doit distinguer « on va détruire » de « on demande
    confirmation » sans lire.
    """
    from tortoisepy.ui.dialogs import ConfirmationRequest, build_confirmation

    destructive = build_confirmation(
        None, ConfirmationRequest("T", "M", destructive=True)
    )
    question = build_confirmation(
        None, ConfirmationRequest("T", "M", destructive=False)
    )
    qtbot.addWidget(destructive)
    qtbot.addWidget(question)

    assert (
        destructive.iconPixmap().toImage()
        != question.iconPixmap().toImage()
    )


def test_cancel_remains_the_default(qtbot):
    """Comportement d'origine à préserver (§7.5).

    Sur une action destructrice, une validation réflexe ne doit pas
    suffire.
    """
    from PySide6.QtWidgets import QMessageBox

    from tortoisepy.ui.dialogs import ConfirmationRequest, build_confirmation

    boite = build_confirmation(
        None, ConfirmationRequest("T", "M", destructive=True)
    )
    qtbot.addWidget(boite)

    assert boite.defaultButton() == boite.button(
        QMessageBox.StandardButton.Cancel
    )
