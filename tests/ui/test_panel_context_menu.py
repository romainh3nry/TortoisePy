"""Clic droit dans le panneau latéral : agir sur UN commit précis.

Signalé par l'utilisateur. Le cherry-pick du graphe applique
`ctx.node.oid` — la **pointe** de la branche — jamais le commit
sélectionné dans le panneau. Mesuré :

    le NOEUD « feature » = dfd08892 : travail en cours
    le panneau affiche :
      dfd08892  travail en cours      <- le seul atteignable
      11e12141  deuxieme correctif
      f967f826  premier correctif
      9749d569  base

Les trois commits du dessous étaient donc hors de portée.

Le cherry-pick s'applique sur la **branche courante**, comme git et
TortoiseGit : appliquer ailleurs imposerait un checkout, donc de quitter
sa branche — bien plus que ce qu'on attend d'un « Cherry-pick ».
"""

from __future__ import annotations

import subprocess

import pygit2
import pytest

from tortoisepy.ui.commit_panel import CommitPanel
from tortoisepy.ui.main_window import MainWindow


def _git(chemin, *args):
    subprocess.run(
        ["git", "-C", str(chemin), *args], check=True, capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
            "PATH": "/usr/bin:/bin:/usr/local/bin",
        },
    )


@pytest.fixture(autouse=True)
def _pas_de_modale(monkeypatch):
    """`show_error` ouvre un `QMessageBox.exec()`, qui bloque la suite.

    Même motif que `tests/ui/test_main_window.py` : on neutralise la
    boîte, pas le chemin qui y mène.
    """
    from tortoisepy.ui import main_window as module

    monkeypatch.setattr(module, "show_error", lambda *a, **k: None)


@pytest.fixture
def fenetre(qtbot, tmp_path):
    """`feature` porte trois commits ; on est sur `main`."""
    w = tmp_path / "w"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "a.txt").write_text("a")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "base")
    _git(w, "checkout", "-q", "-b", "feature")
    for nom in ("premier", "deuxieme", "troisieme"):
        (w / f"{nom}.txt").write_text("x")
        _git(w, "add", ".")
        _git(w, "commit", "-q", "-m", f"{nom} correctif")
    _git(w, "checkout", "-q", "main")

    fenetre = MainWindow(pygit2.Repository(str(w)))
    qtbot.addWidget(fenetre)
    fenetre.show()
    return fenetre


def _afficher_feature(fenetre):
    """Remplit le panneau avec l'historique de `feature`."""
    oid = str(fenetre.repository.branches.local["feature"].target)
    fenetre._show_commits(oid)
    return oid


def test_the_panel_offers_a_context_menu(fenetre):
    """Le panneau n'en avait aucun : les commits étaient inertes."""
    assert hasattr(fenetre.commit_panel, "menu_for")


def test_the_menu_targets_the_selected_commit_not_the_tip(fenetre):
    """L'assertion centrale : c'est tout le point de la demande.

    Sans elle, le menu reproduirait le défaut qu'il doit corriger.
    """
    pointe = _afficher_feature(fenetre)
    arbre = fenetre.commit_panel._tree

    # On sélectionne le TROISIÈME commit, pas la pointe.
    item = arbre.topLevelItem(2)
    arbre.setCurrentItem(item)
    vise = fenetre.commit_panel.selected_oid()

    assert vise != pointe, "le test doit viser un commit autre que la pointe"

    entrees = fenetre.commit_panel.menu_for(vise)
    assert entrees, "aucune entrée de menu"
    for entree in entrees:
        assert entree.oid == vise


def test_the_menu_offers_the_four_requested_actions(fenetre):
    """Les quatre entrées choisies par l'utilisateur."""
    _afficher_feature(fenetre)
    arbre = fenetre.commit_panel._tree
    arbre.setCurrentItem(arbre.topLevelItem(1))

    actions = {
        e.action for e in fenetre.commit_panel.menu_for(
            fenetre.commit_panel.selected_oid()
        )
    }
    assert actions == {
        "cherry_pick_commit", "revert_commit_oid",
        "show_commit_detail", "copy_commit_hash",
    }


def test_cherry_picking_applies_the_selected_commit(qtbot, fenetre):
    """Le commit choisi atterrit sur la branche courante."""
    _afficher_feature(fenetre)
    arbre = fenetre.commit_panel._tree
    arbre.setCurrentItem(arbre.topLevelItem(2))
    vise = fenetre.commit_panel.selected_oid()
    sujet = fenetre.repository.get(vise).message.strip()

    avant = str(fenetre.repository.head.target)
    fenetre.run_panel_action("cherry_pick_commit", vise)
    # L'écriture est DIFFÉRÉE depuis la phase 24bis : elle part en
    # arrière-plan avec le loader, comme les actions du graphe.
    qtbot.waitUntil(
        lambda: str(pygit2.Repository(fenetre.repository.path).head.target)
        != avant,
        timeout=5000,
    )

    apres = str(pygit2.Repository(fenetre.repository.path).head.target)
    assert apres != avant, "aucun commit n'a été créé"
    assert fenetre.repository.get(apres).message.strip() == sujet
    assert fenetre.repository.head.shorthand == "main", (
        "le cherry-pick ne doit pas changer de branche"
    )


def test_cherry_picking_keeps_the_original_commit(fenetre):
    """Cherry-pick COPIE : la branche d'origine garde son commit."""
    _afficher_feature(fenetre)
    arbre = fenetre.commit_panel._tree
    arbre.setCurrentItem(arbre.topLevelItem(2))
    vise = fenetre.commit_panel.selected_oid()

    fenetre.run_panel_action("cherry_pick_commit", vise)

    assert fenetre.repository.get(vise) is not None
    oids_feature = {
        str(c.id) for c in fenetre.repository.walk(
            fenetre.repository.branches.local["feature"].target
        )
    }
    assert vise in oids_feature


def test_copying_the_hash_uses_the_selected_commit(fenetre):
    """Le SHA copié doit être celui de la ligne, pas de la pointe."""
    pointe = _afficher_feature(fenetre)
    arbre = fenetre.commit_panel._tree
    arbre.setCurrentItem(arbre.topLevelItem(2))
    vise = fenetre.commit_panel.selected_oid()

    copies = []
    fenetre._copy_to_clipboard = copies.append
    fenetre.run_panel_action("copy_commit_hash", vise)

    assert copies == [vise]
    assert copies[0] != pointe


def test_an_empty_panel_offers_no_menu(fenetre):
    """Clic droit sur un panneau vide : rien, et aucun plantage."""
    fenetre.commit_panel.clear()
    assert fenetre.commit_panel.selected_oid() is None
    assert fenetre.commit_panel.menu_for(None) == ()


def test_a_conflict_opens_the_resolution_window(qtbot, tmp_path):
    """Signalé par l'utilisateur : « ça indique des conflits mais on peut
    pas les voir ».

    Le chemin du graphe ouvre la fenêtre de résolution quand l'erreur
    parle de conflit ; le panneau se contentait d'écrire le message dans
    la barre d'état, sans rien proposer pour les résoudre.
    """
    w = tmp_path / "w"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "f.txt").write_text("version de base\n")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "base")

    # Deux modifications incompatibles de la MÊME ligne.
    _git(w, "checkout", "-q", "-b", "feature")
    (w / "f.txt").write_text("version feature\n")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "cote feature")
    conflictuel = subprocess.run(
        ["git", "-C", str(w), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    _git(w, "checkout", "-q", "main")
    (w / "f.txt").write_text("version main\n")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "cote main")

    fenetre = MainWindow(pygit2.Repository(str(w)))
    qtbot.addWidget(fenetre)

    ouvertures = []
    fenetre.open_conflict_window = lambda: ouvertures.append(1)

    fenetre.run_panel_action("cherry_pick_commit", conflictuel)
    qtbot.waitUntil(lambda: bool(ouvertures), timeout=5000)

    assert ouvertures, (
        "un conflit doit ouvrir la fenêtre de résolution, "
        "pas seulement afficher un message"
    )
