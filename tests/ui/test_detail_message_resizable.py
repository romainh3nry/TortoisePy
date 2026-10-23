"""Le message d'un commit ne doit pas écraser la liste des fichiers.

Signalé par l'utilisateur, capture à l'appui : sur un commit au
message long — une quarantaine de lignes — l'en-tête occupait
900 px et la liste des fichiers était réduite à trois lignes, alors
que le commit en touchait cinq.

    « quand le message du commit est trop gros ça écrase le bloc des
      changes, il faut pouvoir agrandir ou rétrécir la taille du bloc
      du message »

La fenêtre avait bien un splitter, mais entre le HAUT (en-tête +
fichiers) et le diff. À l'intérieur du haut, les deux widgets
vivaient dans un `QVBoxLayout` : aucune poignée, et l'en-tête prenait
tout ce que son texte demandait.
"""

from __future__ import annotations

import os
import subprocess

import pygit2
import pytest
from PySide6.QtWidgets import QSplitter

from tortoisepy.ui.commit_detail_window import CommitDetailWindow


def run_git(path, *args):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
    }
    return subprocess.run(
        ["git", *args], cwd=path, env=env, capture_output=True, text=True
    )


_MESSAGE_LONG = "Titre court\n\n" + "\n".join(
    f"Ligne {i} d'un message qui explique longuement une décision."
    for i in range(40)
)


@pytest.fixture
def depot_message_long(tmp_path):
    """Le cas signalé : message de quarante lignes, cinq fichiers."""
    chemin = tmp_path / "long"
    chemin.mkdir()
    run_git(chemin, "init", "-q", "-b", "main")
    for i in range(5):
        (chemin / f"f{i}.txt").write_text(f"contenu {i}\n")
    run_git(chemin, "add", ".")
    run_git(chemin, "commit", "-q", "-m", _MESSAGE_LONG)
    return pygit2.Repository(str(chemin))


@pytest.fixture
def fenetre(qtbot, depot_message_long):
    f = CommitDetailWindow(
        depot_message_long, str(depot_message_long.head.target)
    )
    qtbot.addWidget(f)
    f.show()
    qtbot.waitExposed(f)
    return f


def _splitter_du_haut(fenetre) -> QSplitter | None:
    """Le splitter qui sépare le message de la liste des fichiers."""
    for splitter in fenetre.findChildren(QSplitter):
        widgets = [
            splitter.widget(i) for i in range(splitter.count())
        ]
        if fenetre._files in widgets:
            return splitter
    return None


# --- le cas signalé -----------------------------------------------------


def test_the_message_and_the_files_share_a_splitter(fenetre):
    """La demande : pouvoir agrandir ou rétrécir le bloc du message.

    Sans poignée entre les deux, l'en-tête prend tout ce que son
    texte demande et la liste se réduit à ce qui reste.
    """
    splitter = _splitter_du_haut(fenetre)

    assert splitter is not None, (
        "la liste des fichiers n'est pas dans un splitter : sa hauteur "
        "ne peut pas être ajustée"
    )
    # L'en-tête est DANS la zone défilante, elle-même dans le
    # splitter : on remonte la chaîne de parenté plutôt que d'exiger
    # qu'il en soit l'enfant direct. Un message long doit pouvoir
    # défiler, pas seulement être rogné.
    cotes = [splitter.widget(i) for i in range(splitter.count())]
    assert any(
        cote is not None and fenetre._header in cote.findChildren(
            type(fenetre._header)
        )
        for cote in cotes
    ), "le message n'est pas du même côté de la poignée"


def test_the_message_is_resizable(qtbot, fenetre):
    """Le test qui compte : la hauteur doit RÉELLEMENT changer.

    Un splitter dont un panneau refuserait de se redimensionner
    n'apporterait rien — c'est l'état d'avant, avec une poignée en
    plus.
    """
    splitter = _splitter_du_haut(fenetre)
    total = sum(splitter.sizes())

    splitter.setSizes([total // 5, total - total // 5])
    qtbot.waitUntil(
        lambda: splitter.sizes()[0] < total // 2, timeout=2000
    )

    assert splitter.sizes()[0] < total // 2, (
        f"le message garde {splitter.sizes()[0]} px sur {total}"
    )


def test_the_file_list_keeps_a_usable_height(qtbot, fenetre):
    """Le symptôme : trois lignes visibles pour cinq fichiers.

    Mesuré sur la capture de l'utilisateur. Même à l'ouverture, avant
    tout réglage, la liste doit montrer ce qu'elle contient.
    """
    assert fenetre.file_count() == 5

    hauteur_ligne = fenetre._files.sizeHintForRow(0)
    assert hauteur_ligne > 0

    visibles = fenetre._files.viewport().height() // hauteur_ligne
    assert visibles >= 4, (
        f"{visibles} lignes visibles pour {fenetre.file_count()} "
        "fichiers : le message écrase la liste"
    )


def test_the_file_list_gets_a_real_share_at_opening(fenetre):
    """Les deux panneaux se partagent la hauteur dès l'ouverture.

    Trouvé par mutation : retirer `setSizes` laissait tous les tests
    passer, alors que c'est LE correctif qui a réglé le symptôme.
    `setStretchFactor` ne joue que sur l'espace EXCÉDENTAIRE, et Qt
    part des tailles souhaitées — or un `QLabel` en demande autant
    que son texte. Sans tailles explicites, le rendu restait
    identique au défaut (constaté sur capture).
    """
    splitter = _splitter_du_haut(fenetre)
    message, fichiers = splitter.sizes()

    assert fichiers > 0, "la liste n'a aucune hauteur"
    assert message > 0, "le message n'a aucune hauteur"

    # Parts ÉGALES à l'ouverture, à 10 % près. Un seuil plus lâche ne
    # suffit pas : mesuré, retirer `setSizes` donne [88, 166], soit un
    # rapport de 1,9 — assez pour que le message tombe à trois lignes,
    # le défaut d'origine inversé, mais trop peu pour qu'un seuil de 3
    # le remarque.
    rapport = max(message, fichiers) / min(message, fichiers)
    assert rapport <= 1.1, (
        f"message {message} px contre fichiers {fichiers} px : "
        "les deux panneaux ne se partagent pas la hauteur"
    )


def test_the_message_scrolls_instead_of_being_cut(fenetre):
    """Un message long doit défiler, pas disparaître.

    Trouvé par mutation : sans `setWidgetResizable(True)`, la zone
    ne redimensionne pas son contenu — le texte garde sa largeur
    naturelle et déborde horizontalement au lieu de se replier.
    """
    from PySide6.QtWidgets import QScrollArea

    zones = [
        z for z in fenetre.findChildren(QScrollArea)
        if fenetre._header in z.findChildren(type(fenetre._header))
    ]

    assert zones, "le message n'est pas dans une zone défilante"
    assert zones[0].widgetResizable(), (
        "la zone ne redimensionne pas son contenu : le texte "
        "débordera au lieu de se replier"
    )


def test_a_long_message_does_not_take_everything(fenetre):
    """L'en-tête ne doit pas revendiquer toute la hauteur.

    C'est la cause racine : un `QLabel` dans un `QVBoxLayout` prend
    la place que son texte demande, sans limite.
    """
    splitter = _splitter_du_haut(fenetre)
    message, _reste = splitter.sizes()[0], splitter.sizes()[1]

    assert message < splitter.height() * 0.75, (
        f"le message occupe {message} px sur {splitter.height()}"
    )


# --- le reste ne doit pas se dégrader -----------------------------------


def test_the_message_is_still_shown_entirely(fenetre):
    """Réduire la place ne doit pas tronquer le texte.

    Le message reste consultable : on fait défiler, on ne perd rien.
    """
    assert "Titre court" in fenetre._header.text()
    assert "Ligne 39" in fenetre._header.text()


def test_the_message_is_still_selectable(fenetre):
    """Copier un identifiant ou un message reste possible."""
    from PySide6.QtCore import Qt

    assert (
        fenetre._header.textInteractionFlags()
        & Qt.TextInteractionFlag.TextSelectableByMouse
    )


def test_a_short_message_does_not_waste_space(qtbot, depot_message_long,
                                               tmp_path):
    """Un message d'une ligne ne doit pas réserver une grande zone.

    Le piège de la correction : poser une hauteur fixe généreuse
    règlerait le cas long en gâchant le cas courant, qui est le plus
    fréquent.
    """
    chemin = tmp_path / "court"
    chemin.mkdir()
    run_git(chemin, "init", "-q", "-b", "main")
    (chemin / "f.txt").write_text("x\n")
    run_git(chemin, "add", ".")
    run_git(chemin, "commit", "-q", "-m", "fix")

    depot = pygit2.Repository(str(chemin))
    f = CommitDetailWindow(depot, str(depot.head.target))
    qtbot.addWidget(f)
    f.show()
    qtbot.waitExposed(f)

    splitter = _splitter_du_haut(f)
    assert splitter.sizes()[0] < splitter.height() * 0.5, (
        "un message d'une ligne réserve la moitié de la fenêtre"
    )


def test_the_diff_still_has_its_own_splitter(fenetre):
    """La séparation haut / diff existait déjà et doit rester.

    Le piège : remplacer un splitter par l'autre au lieu d'imbriquer.
    """
    splitters = fenetre.findChildren(QSplitter)

    assert len(splitters) >= 2, (
        f"{len(splitters)} splitter(s) : la séparation avec le diff a "
        "disparu"
    )
    assert any(
        fenetre.diff_view in [s.widget(i) for i in range(s.count())]
        for s in splitters
    )
