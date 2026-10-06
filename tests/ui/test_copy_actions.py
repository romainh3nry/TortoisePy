"""Copier un nom de branche, copier un chemin de fichier.

Demandé par l'utilisateur : « j'aimerai qu'on puisse copier dans le
presse-papier le nom d'une branche et aussi, dans le menu des
commits/conflits, qu'on puisse copier le chemin d'un fichier ».

L'application savait déjà copier un SHA-1 ; ce sont les deux autres
identifiants qu'on recopie sans cesse à la main — un nom de branche pour
une commande au terminal, un chemin pour l'ouvrir dans l'éditeur.

Rien n'est écrit dans le dépôt : ces actions sont des consultations
(§7.0).
"""

from __future__ import annotations

import subprocess

import pygit2
import pytest

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


# --- copier le nom d'une branche ----------------------------------------


def test_the_graph_menu_offers_to_copy_the_branch_name():
    """L'entrée doit exister, sinon la fonction est inatteignable."""
    from tortoisepy.core.model import DisplayNode, NodeKind, Ref, RefType
    from tortoisepy.core.state import RepositoryState
    from tortoisepy.ui.context_menu import build_menu_model

    noeud = DisplayNode(
        oid="a" * 40,
        kind=NodeKind.REF,
        refs=(Ref(name="develop", type=RefType.LOCAL_BRANCH, target="a" * 40),),
    )
    etat = RepositoryState(
        head_oid="a" * 40, head_branch="develop", detached=False,
        has_unstaged_changes=False, has_staged_changes=False,
        has_conflicts=False, operation_in_progress=None, conflicted_paths=(),
    )

    libelles = [e.label for e in build_menu_model((noeud,), etat)]
    assert any("branch name" in l.lower() for l in libelles), (
        f"aucune entrée pour copier le nom de la branche : {libelles}"
    )


def test_copying_a_branch_name_puts_it_in_the_clipboard():
    """L'assertion qui compte : le texte doit vraiment être copié."""
    from tortoisepy.core.model import DisplayNode, NodeKind, Ref, RefType
    from tortoisepy.core.state import RepositoryState
    from tortoisepy.ui.actions import ActionContext, execute_action

    copie = []
    noeud = DisplayNode(
        oid="a" * 40,
        kind=NodeKind.REF,
        refs=(Ref(name="develop", type=RefType.LOCAL_BRANCH, target="a" * 40),),
    )
    ctx = ActionContext(
        repository=None,
        node=noeud,
        state=RepositoryState(
            head_oid="a" * 40, head_branch="develop", detached=False,
            has_unstaged_changes=False, has_staged_changes=False,
            has_conflicts=False, operation_in_progress=None,
            conflicted_paths=(),
        ),
        copy=copie.append,
    )

    resultat = execute_action("copy_branch_name", ctx)

    assert copie == ["develop"]
    assert resultat is not None and resultat.success
    assert not resultat.repository_changed, "une copie n'écrit rien (§7.0)"


def test_the_chosen_branch_wins_over_the_first_one():
    """Un nœud peut porter plusieurs branches.

    Le piège, déjà rencontré sur ce projet : se rabattre sur la première
    ref rendrait les autres inatteignables — l'utilisateur avait signalé
    exactement ce défaut sur la création de tag.
    """
    from tortoisepy.core.model import DisplayNode, NodeKind, Ref, RefType
    from tortoisepy.core.state import RepositoryState
    from tortoisepy.ui.actions import ActionContext, execute_action

    copie = []
    noeud = DisplayNode(
        oid="a" * 40,
        kind=NodeKind.REF,
        refs=(
            Ref(name="develop", type=RefType.LOCAL_BRANCH, target="a" * 40),
            Ref(name="feature/x", type=RefType.LOCAL_BRANCH, target="a" * 40),
        ),
    )
    ctx = ActionContext(
        repository=None,
        node=noeud,
        state=RepositoryState(
            head_oid="a" * 40, head_branch="develop", detached=False,
            has_unstaged_changes=False, has_staged_changes=False,
            has_conflicts=False, operation_in_progress=None,
            conflicted_paths=(),
        ),
        copy=copie.append,
        chosen_branch="feature/x",
    )

    execute_action("copy_branch_name", ctx)

    assert copie == ["feature/x"], (
        "la branche désignée par le menu doit primer"
    )


def test_a_node_without_branch_copies_nothing():
    """Un nœud sans branche locale n'a pas de nom à copier.

    Copier l'OID à la place tromperait : l'entrée « Copy SHA-1 » existe
    déjà pour cela, et les deux ne doivent pas faire la même chose.
    """
    from tortoisepy.core.model import DisplayNode, NodeKind
    from tortoisepy.core.state import RepositoryState
    from tortoisepy.ui.actions import ActionContext, execute_action

    copie = []
    ctx = ActionContext(
        repository=None,
        node=DisplayNode(oid="a" * 40, kind=NodeKind.REF, refs=()),
        state=RepositoryState(
            head_oid="a" * 40, head_branch=None, detached=True,
            has_unstaged_changes=False, has_staged_changes=False,
            has_conflicts=False, operation_in_progress=None,
            conflicted_paths=(),
        ),
        copy=copie.append,
    )

    execute_action("copy_branch_name", ctx)

    assert copie == []


# --- copier le chemin d'un fichier --------------------------------------


@pytest.fixture
def depot(tmp_path):
    w = tmp_path / "w"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "src").mkdir()
    (w / "src" / "module.py").write_text("x = 1\n")
    _git(w, "add", ".")
    _git(w, "commit", "-qm", "base")
    return pygit2.Repository(str(w))


def test_the_commit_detail_offers_to_copy_the_path(qtbot, depot):
    """Le menu par fichier existe déjà : on s'y greffe."""
    from tortoisepy.ui.commit_detail_window import CommitDetailWindow

    fenetre = CommitDetailWindow(depot, str(depot.head.target))
    qtbot.addWidget(fenetre)

    entrees = fenetre.context_actions_for_row(0)
    assert any("path" in e.lower() for e in entrees), (
        f"aucune entrée pour copier le chemin : {entrees}"
    )


def test_copying_the_path_from_the_detail_window(qtbot, depot, monkeypatch):
    """Le chemin copié doit être celui de la ligne visée."""
    from tortoisepy.ui import commit_detail_window as module
    from tortoisepy.ui.commit_detail_window import CommitDetailWindow

    copie = []
    monkeypatch.setattr(
        module, "copy_to_clipboard", lambda texte: copie.append(texte)
    )

    fenetre = CommitDetailWindow(depot, str(depot.head.target))
    qtbot.addWidget(fenetre)
    fenetre.copy_path_row(0)

    assert copie == ["src/module.py"], (
        f"chemin inattendu : {copie}"
    )


def test_the_copied_path_is_relative_to_the_repository(qtbot, depot, monkeypatch):
    """Un chemin relatif se recolle dans n'importe quelle commande git.

    Un chemin absolu porterait le nom de la machine et ne servirait qu'ici.
    """
    from tortoisepy.ui import commit_detail_window as module
    from tortoisepy.ui.commit_detail_window import CommitDetailWindow

    copie = []
    monkeypatch.setattr(
        module, "copy_to_clipboard", lambda texte: copie.append(texte)
    )

    fenetre = CommitDetailWindow(depot, str(depot.head.target))
    qtbot.addWidget(fenetre)
    fenetre.copy_path_row(0)

    assert not copie[0].startswith("/"), f"chemin absolu : {copie[0]}"


# --- copier le chemin depuis la fenêtre de conflits ---------------------


@pytest.fixture
def depot_en_conflit(tmp_path):
    w = tmp_path / "conflit"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "conf").mkdir()
    cible = w / "conf" / "app.yml"
    cible.write_text("a\n")
    _git(w, "add", ".")
    _git(w, "commit", "-qm", "base")
    _git(w, "checkout", "-qb", "autre")
    cible.write_text("b\n")
    _git(w, "add", ".")
    _git(w, "commit", "-qm", "autre")
    _git(w, "checkout", "-q", "main")
    cible.write_text("c\n")
    _git(w, "add", ".")
    _git(w, "commit", "-qm", "main")
    _git(w, "merge", "autre", check=False)
    return pygit2.Repository(str(w))


def test_the_conflict_window_offers_to_copy_the_path(qtbot, depot_en_conflit):
    """Demandé explicitement : « dans le menu des commits/conflits »."""
    from tortoisepy.ui.conflict_window import ConflictWindow

    fenetre = ConflictWindow(depot_en_conflit)
    qtbot.addWidget(fenetre)

    entrees = fenetre.context_actions_for_row(0)
    assert any("path" in e.lower() for e in entrees), (
        f"aucune entrée pour copier le chemin : {entrees}"
    )


def test_copying_the_path_from_the_conflict_window(
    qtbot, depot_en_conflit, monkeypatch
):
    """Pendant un conflit, le chemin est ce qu'on recopie le plus."""
    from tortoisepy.ui import conflict_window as module
    from tortoisepy.ui.conflict_window import ConflictWindow

    copie = []
    monkeypatch.setattr(
        module, "copy_to_clipboard", lambda texte: copie.append(texte)
    )

    fenetre = ConflictWindow(depot_en_conflit)
    qtbot.addWidget(fenetre)
    fenetre.copy_path_row(0)

    assert copie == ["conf/app.yml"]


def test_copying_from_an_empty_row_does_nothing(qtbot, depot_en_conflit):
    """Un clic hors des lignes ne doit pas lever."""
    from tortoisepy.ui.conflict_window import ConflictWindow

    fenetre = ConflictWindow(depot_en_conflit)
    qtbot.addWidget(fenetre)

    fenetre.copy_path_row(99)     # ne doit pas lever
    assert fenetre.context_actions_for_row(99) == ()


# --- les branches distantes aussi ---------------------------------------


def _etat():
    from tortoisepy.core.state import RepositoryState

    return RepositoryState(
        head_oid="a" * 40, head_branch="develop", detached=False,
        has_unstaged_changes=False, has_staged_changes=False,
        has_conflicts=False, operation_in_progress=None, conflicted_paths=(),
    )


def _copies(refs):
    """Les entrées « Copy branch name » proposées pour ces refs."""
    from tortoisepy.core.model import DisplayNode, NodeKind
    from tortoisepy.ui.context_menu import build_menu_model

    noeud = DisplayNode(oid="a" * 40, kind=NodeKind.REF, refs=refs)
    return [
        e.branch for e in build_menu_model((noeud,), _etat())
        if e.action == "copy_branch_name"
    ]


def test_a_remote_only_node_can_be_copied():
    """Signalé par l'utilisateur : « pourquoi je ne peux copier que les
    branches locales et pas les remotes ? ».

    Un nœud ne portant qu'une branche distante n'offrait rien. C'est
    pourtant le nom qu'on recopie pour un `git checkout origin/…`.
    """
    from tortoisepy.core.model import Ref, RefType

    refs = (
        Ref(name="origin/CRM-3933", type=RefType.REMOTE_BRANCH,
            target="a" * 40),
    )
    assert _copies(refs) == ["origin/CRM-3933"]


def test_both_sides_are_offered_on_a_tracked_branch():
    """Le cas courant : locale et distante sur le même nœud.

    Mesuré avant correction, seule la locale était proposée — donc
    impossible de copier `origin/develop` dès qu'une locale existait, ce
    qui est le cas le plus fréquent.
    """
    from tortoisepy.core.model import Ref, RefType

    refs = (
        Ref(name="develop", type=RefType.LOCAL_BRANCH, target="a" * 40),
        Ref(name="origin/develop", type=RefType.REMOTE_BRANCH,
            target="a" * 40),
    )
    assert _copies(refs) == ["develop", "origin/develop"], (
        "les deux noms doivent être copiables, la locale en premier"
    )


def test_a_protected_remote_branch_can_still_be_copied():
    """`origin/main` se copie, même s'il ne se supprime pas.

    Le piège : réutiliser le filtre écrit pour la suppression. Ce qu'on
    peut copier n'est pas ce qu'on peut détruire — le même contresens
    avait déjà grisé « Switch / Checkout » (phase 21).
    """
    from tortoisepy.core.model import Ref, RefType

    refs = (
        Ref(name="origin/main", type=RefType.REMOTE_BRANCH, target="a" * 40),
    )
    assert _copies(refs) == ["origin/main"]


def test_a_tag_is_not_offered_as_a_branch():
    """Un tag n'est pas une branche : « Copy SHA-1 » reste la bonne entrée."""
    from tortoisepy.core.model import Ref, RefType

    refs = (Ref(name="v5.50.3", type=RefType.TAG, target="a" * 40),)
    assert _copies(refs) == []


def test_copying_a_remote_name_puts_it_in_the_clipboard():
    """Le bout de la chaîne : l'action doit vraiment copier ce nom."""
    from tortoisepy.core.model import DisplayNode, NodeKind, Ref, RefType
    from tortoisepy.ui.actions import ActionContext, execute_action

    copie = []
    noeud = DisplayNode(
        oid="a" * 40, kind=NodeKind.REF,
        refs=(Ref(name="origin/CRM-3933", type=RefType.REMOTE_BRANCH,
                  target="a" * 40),),
    )
    ctx = ActionContext(
        repository=None, node=noeud, state=_etat(),
        copy=copie.append, chosen_branch="origin/CRM-3933",
    )

    execute_action("copy_branch_name", ctx)

    assert copie == ["origin/CRM-3933"]


# --- copier le chemin depuis la fenêtre de commit -----------------------


@pytest.fixture
def depot_modifie(tmp_path):
    """Un dépôt avec un fichier modifié, prêt pour la fenêtre de commit."""
    w = tmp_path / "commit"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "public").mkdir()
    cible = w / "public" / "Model.php"
    cible.write_text("<?php\n")
    _git(w, "add", ".")
    _git(w, "commit", "-qm", "base")
    cible.write_text("<?php // modifie\n")
    return pygit2.Repository(str(w))


def test_the_commit_window_offers_to_copy_the_path(qtbot, depot_modifie):
    """Signalé par l'utilisateur, capture à l'appui : la liste de la
    fenêtre de commit n'avait aucun menu contextuel.

    C'est le quatrième écran qui affiche des fichiers — après le détail
    d'un commit, les conflits et le blâme — et il manquait à l'appel.
    """
    from tortoisepy.ui.commit_window import CommitWindow

    fenetre = CommitWindow(depot_modifie)
    qtbot.addWidget(fenetre)

    entrees = fenetre.context_actions_for_row(0)
    assert any("path" in e.lower() for e in entrees), (
        f"aucune entrée pour copier le chemin : {entrees}"
    )


def test_copying_the_path_from_the_commit_window(
    qtbot, depot_modifie, monkeypatch
):
    """Le chemin copié est celui de la ligne visée, relatif au dépôt."""
    from tortoisepy.ui import commit_window as module
    from tortoisepy.ui.commit_window import CommitWindow

    copie = []
    monkeypatch.setattr(
        module, "copy_to_clipboard", lambda texte: copie.append(texte)
    )

    fenetre = CommitWindow(depot_modifie)
    qtbot.addWidget(fenetre)
    fenetre.copy_path_row(0)

    assert copie == ["public/Model.php"]


def test_copying_does_not_change_the_selection(qtbot, depot_modifie, monkeypatch):
    """Copier un chemin ne doit pas décocher le fichier.

    Le piège propre à CETTE fenêtre : ses cases décident de ce qui sera
    commité. Un menu qui toucherait à la sélection ferait perdre une
    préparation faite à la main.
    """
    from tortoisepy.ui import commit_window as module
    from tortoisepy.ui.commit_window import CommitWindow

    monkeypatch.setattr(module, "copy_to_clipboard", lambda texte: None)

    fenetre = CommitWindow(depot_modifie)
    qtbot.addWidget(fenetre)
    avant = fenetre.checked_paths()

    fenetre.copy_path_row(0)

    assert fenetre.checked_paths() == avant


def test_copying_from_an_empty_row_in_commit_does_nothing(qtbot, depot_modifie):
    """Un clic hors des lignes ne doit pas lever."""
    from tortoisepy.ui.commit_window import CommitWindow

    fenetre = CommitWindow(depot_modifie)
    qtbot.addWidget(fenetre)

    fenetre.copy_path_row(99)
    assert fenetre.context_actions_for_row(99) == ()
