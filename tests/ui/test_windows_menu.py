"""Savoir combien de graphes sont ouverts, et y revenir.

Signalé par l'utilisateur :

    « quand on ouvre un graph de manière classique, une icône s'ouvre
      en bas, si j'ouvre à nouveau un autre graph, une deuxième icône
      s'ouvre, c'est le comportement voulu. par contre si j'ouvre un
      deuxième repo depuis le open project ou open recent, le graph
      s'affiche bien mais pas de deuxième icône, ce qui fait qu'on ne
      sait pas très bien combien de graph est ouvert »

Le Dock de macOS représente des PROCESSUS, pas des fenêtres : `topy`
relance un processus détaché (une icône chacun), alors que « Open
Project » construit une `MainWindow` dans le processus courant (une
seule icône, partagée). Ce n'est donc pas un défaut à corriger mais
une contrainte de plateforme à contourner — par la convention macOS
pour ce problème : un menu listant les fenêtres ouvertes.

Le registre `_recent_windows` ne pouvait pas servir de source : il
est PAR fenêtre. La fenêtre A ouvre B et C, mais B ne connaît ni A ni
C — le menu aurait montré une liste différente selon l'endroit d'où
on l'ouvre, soit exactement la confusion à supprimer.
"""

from __future__ import annotations

import os
import subprocess

import pygit2
import pytest
from unittest.mock import patch
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QToolButton

from tortoisepy.ui.child_windows import still_alive
from tortoisepy.ui.main_window import MainWindow


def run_git(path, *args):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
    }
    return subprocess.run(
        ["git", *args], cwd=path, env=env, capture_output=True, text=True
    )


def _depot(chemin):
    chemin.mkdir(parents=True, exist_ok=True)
    run_git(chemin, "init", "-q", "-b", "main")
    (chemin / "f.txt").write_text("x\n")
    run_git(chemin, "add", "f.txt")
    run_git(chemin, "commit", "-q", "-m", "base")
    return pygit2.Repository(str(chemin))


@pytest.fixture
def trois_depots(tmp_path):
    return [_depot(tmp_path / nom) for nom in ("alpha", "beta", "gamma")]


def _bouton_fenetres(fenetre) -> QToolButton | None:
    """Le bouton à menu déroulant qui liste les fenêtres."""
    for bouton in fenetre.findChildren(QToolButton):
        if bouton.text() == "Windows":
            return bouton
    return None


def _entrees(fenetre) -> list[str]:
    """Les intitulés du menu, après peuplement."""
    bouton = _bouton_fenetres(fenetre)
    menu = bouton.menu()
    menu.aboutToShow.emit()
    return [action.text() for action in menu.actions()]


# Les dépôts créés par CE fichier. Le menu liste les fenêtres de tout
# le processus, et la suite complète en laisse d'autres ouvertes
# (« gros », « petit », « recent »… vus en exécution réelle). Compter
# un total absolu passait en isolation et échouait dans la suite — le
# code n'y était pour rien, mes assertions supposaient un processus
# vierge.
_NOTRES = ("alpha", "beta", "gamma", "intrus", "sans-suffixe")


def _nos_entrees(fenetre) -> list[str]:
    """Les entrées correspondant aux dépôts de ce fichier."""
    return [
        entree for entree in _entrees(fenetre)
        if any(entree.startswith(nom) for nom in _NOTRES)
    ]


# --- le cas signalé -----------------------------------------------------


def test_the_menu_lists_every_open_window(qtbot, trois_depots):
    """Le besoin exact : savoir combien de graphes sont ouverts."""
    fenetres = []
    for depot in trois_depots:
        f = MainWindow(depot)
        qtbot.addWidget(f)
        f.show()
        qtbot.waitExposed(f)
        fenetres.append(f)

    entrees = _nos_entrees(fenetres[0])

    assert len(entrees) == 3, (
        f"{len(entrees)} entrée(s) pour 3 fenêtres ouvertes : {entrees}"
    )
    for nom in ("alpha", "beta", "gamma"):
        assert any(nom in entree for entree in entrees), (
            f"« {nom} » absent du menu : {entrees}"
        )


def test_every_window_shows_the_same_list(qtbot, trois_depots):
    """LE point qui a dicté la conception.

    `_recent_windows` est par fenêtre : s'en servir aurait donné une
    liste dépendant de l'endroit d'où on ouvre le menu. La source doit
    être globale au processus.
    """
    fenetres = []
    for depot in trois_depots:
        f = MainWindow(depot)
        qtbot.addWidget(f)
        f.show()
        qtbot.waitExposed(f)
        fenetres.append(f)

    listes = [sorted(_nos_entrees(f)) for f in fenetres]

    assert listes[0] == listes[1] == listes[2], (
        "le menu dépend de la fenêtre d'où on l'ouvre :\n"
        + "\n".join(map(str, listes))
    )


def test_a_single_window_still_gets_an_entry(qtbot, trois_depots):
    """Une seule fenêtre : l'entrée existe quand même.

    Un menu vide ne dirait pas « une seule fenêtre », il dirait
    « quelque chose est cassé ».
    """
    f = MainWindow(trois_depots[0])
    qtbot.addWidget(f)
    f.show()
    qtbot.waitExposed(f)

    entrees = _nos_entrees(f)

    assert len(entrees) == 1
    assert "alpha" in entrees[0]


# --- les pièges mesurés -------------------------------------------------


def test_a_closed_window_leaves_the_list(qtbot, trois_depots):
    """Mesuré : une fenêtre fermée reste dans `topLevelWidgets()`.

    Avec `WA_DeleteOnClose` l'objet part après `processEvents`, mais la
    fenêtre racine — celle lancée depuis le terminal — ne porte PAS
    cet attribut : elle reste listée, `isVisible()` à False. Filtrer
    sur la seule validité la laisserait dans le menu.
    """
    gardee = MainWindow(trois_depots[0])
    qtbot.addWidget(gardee)
    gardee.show()
    qtbot.waitExposed(gardee)

    fermee = MainWindow(trois_depots[1])
    qtbot.addWidget(fermee)
    fermee.show()
    qtbot.waitExposed(fermee)

    assert len(_nos_entrees(gardee)) == 2

    fermee.close()
    qtbot.waitUntil(lambda: not fermee.isVisible(), timeout=2000)

    entrees = _nos_entrees(gardee)
    assert len(entrees) == 1, (
        f"la fenêtre fermée est encore listée : {entrees}"
    )
    assert "beta" not in entrees[0]


def test_the_entry_names_the_repository(qtbot, trois_depots):
    """L'entrée doit identifier le dépôt, pas juste numéroter.

    « Fenêtre 2 » ne dit pas sur quoi elle est ouverte.
    """
    f = MainWindow(trois_depots[0])
    qtbot.addWidget(f)
    f.show()
    qtbot.waitExposed(f)

    assert "alpha" in _nos_entrees(f)[0]


def test_the_menu_is_rebuilt_each_time(qtbot, trois_depots):
    """Peuplé à l'ouverture, comme « Open Recent » juste à côté.

    Un menu construit une fois afficherait la liste du passé.
    """
    premiere = MainWindow(trois_depots[0])
    qtbot.addWidget(premiere)
    premiere.show()
    qtbot.waitExposed(premiere)

    assert len(_nos_entrees(premiere)) == 1

    seconde = MainWindow(trois_depots[1])
    qtbot.addWidget(seconde)
    seconde.show()
    qtbot.waitExposed(seconde)

    assert len(_nos_entrees(premiere)) == 2, (
        "le menu n'a pas vu la fenêtre ouverte après sa construction"
    )


def test_clicking_an_entry_raises_that_window(qtbot, trois_depots):
    """Le menu sert aussi à NAVIGUER, pas seulement à compter.

    C'est ce qui le rend meilleur qu'un simple compteur dans la barre
    d'état : revenir à une fenêtre enfouie est le vrai besoin derrière
    « on ne sait pas combien sont ouverts ».
    """
    premiere = MainWindow(trois_depots[0])
    qtbot.addWidget(premiere)
    premiere.show()
    qtbot.waitExposed(premiere)

    seconde = MainWindow(trois_depots[1])
    qtbot.addWidget(seconde)
    seconde.show()
    qtbot.waitExposed(seconde)

    bouton = _bouton_fenetres(seconde)
    menu = bouton.menu()
    menu.aboutToShow.emit()

    vers_alpha = [a for a in menu.actions() if "alpha" in a.text()]
    assert vers_alpha, "pas d'entrée vers la première fenêtre"

    # On observe les appels plutôt que `isVisible()` : les deux
    # fenêtres sont déjà visibles, donc l'état visible ne prouve rien.
    # Trouvé par mutation — retirer `raise_` ET `activateWindow`
    # laissait ce test au vert.
    appels = []
    for cible in (premiere, seconde):
        cible.raise_ = lambda c=cible: appels.append(("raise", c))
        cible.activateWindow = lambda c=cible: appels.append(("activate", c))

    vers_alpha[0].trigger()
    qtbot.wait(50)

    assert ("raise", premiere) in appels, (
        f"la fenêtre visée n'a pas été remontée : {appels}"
    )
    assert ("activate", premiere) in appels, (
        "la fenêtre apparaît sans recevoir le focus clavier"
    )
    # Et surtout PAS l'autre : sans `fenetre=fenetre` dans la fermeture,
    # toutes les entrées viseraient la dernière de la boucle (trouvé
    # par mutation).
    assert not any(cible is seconde for _, cible in appels), (
        f"le clic a visé la mauvaise fenêtre : {appels}"
    )


def test_the_current_window_is_marked(qtbot, trois_depots):
    """Distinguer la fenêtre courante des autres.

    Sans repère, le menu dit combien de fenêtres existent mais pas
    laquelle on regarde.
    """
    premiere = MainWindow(trois_depots[0])
    qtbot.addWidget(premiere)
    premiere.show()
    qtbot.waitExposed(premiere)

    seconde = MainWindow(trois_depots[1])
    qtbot.addWidget(seconde)
    seconde.show()
    qtbot.waitExposed(seconde)

    bouton = _bouton_fenetres(premiere)
    menu = bouton.menu()
    menu.aboutToShow.emit()

    cochees = [a for a in menu.actions() if a.isChecked()]

    assert len(cochees) == 1, (
        f"{len(cochees)} entrée(s) marquée(s), il en faut une"
    )
    assert "alpha" in cochees[0].text(), (
        "la marque n'est pas sur la fenêtre d'où le menu est ouvert"
    )


def test_the_order_is_stable(qtbot, trois_depots):
    """L'ordre ne doit pas dépendre de celui de Qt.

    Trouvé par mutation : retirer le tri laissait tout passer. Mesuré
    pourtant, `topLevelWidgets()` rend un ordre arbitraire — beta,
    gamma, alpha pour trois fenêtres créées dans l'ordre inverse. Un
    menu qui se réordonne entre deux ouvertures fait cliquer à côté.
    """
    fenetres = []
    for depot in trois_depots:
        f = MainWindow(depot)
        qtbot.addWidget(f)
        f.show()
        qtbot.waitExposed(f)
        fenetres.append(f)

    entrees = _entrees(fenetres[0])  # l'ordre global, pas seulement le nôtre

    assert entrees == sorted(entrees), (
        f"l'ordre du menu suit celui de Qt, pas le titre : {entrees}"
    )


def test_a_destroyed_window_is_not_listed(qtbot, trois_depots):
    """Une fenêtre détruite disparaît du menu.

    Épingle le comportement de Qt dont la conception dépend : mesuré,
    `topLevelWidgets()` ne contient plus l'objet que Qt a détruit
    (`WA_DeleteOnClose`). C'est ce qui rend un garde `still_alive`
    inutile dans ce filtre — la mutation l'a montré, aucun test ne
    pouvait le tuer. Si une version de Qt changeait cela, ce test le
    dirait, et le garde redeviendrait nécessaire.
    """
    gardee = MainWindow(trois_depots[0])
    qtbot.addWidget(gardee)
    gardee.show()
    qtbot.waitExposed(gardee)

    detruite = MainWindow(trois_depots[1])
    detruite.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    detruite.show()
    qtbot.waitExposed(detruite)

    assert len(_nos_entrees(gardee)) == 2

    # `WA_DeleteOnClose` : Qt détruit l'objet C++, le wrapper Python
    # reste.
    detruite.close()
    qtbot.waitUntil(lambda: not still_alive(detruite), timeout=3000)

    # Le menu doit s'ouvrir SANS lever.
    entrees = _nos_entrees(gardee)

    assert len(entrees) == 1, f"objet détruit encore listé : {entrees}"


def test_only_graph_windows_are_listed(qtbot, trois_depots):
    """Les autres fenêtres du processus n'ont rien à faire là.

    Trouvé par mutation : retirer le test de type laissait tout
    passer. `topLevelWidgets()` rend TOUTES les fenêtres de premier
    niveau — l'écran d'attente, un dialogue, une fenêtre de détail.
    Les lister ferait du menu un inventaire illisible.
    """
    from tortoisepy.ui.splash import StartupSplash

    f = MainWindow(trois_depots[0])
    qtbot.addWidget(f)
    f.show()
    qtbot.waitExposed(f)

    intrus = StartupSplash("intrus")
    qtbot.addWidget(intrus)
    intrus.show()
    qtbot.waitExposed(intrus)

    entrees = _nos_entrees(f)

    assert len(entrees) == 1, (
        f"une fenêtre qui n'est pas un graphe est listée : {entrees}"
    )
    assert not any("intrus" in entree for entree in entrees), (
        f"l'écran d'attente est listé : {entrees}"
    )


def test_clicking_a_vanished_window_does_not_raise(qtbot, trois_depots):
    """La fenêtre peut disparaître entre l'ouverture du menu et le clic.

    Trouvé par mutation : retirer le garde de `_raise_window` laissait
    tout passer. La référence est figée dans la fermeture au
    peuplement du menu ; si la fenêtre est détruite avant le clic,
    l'appeler lève un `RuntimeError` de shiboken. Ici le garde est
    bien nécessaire — contrairement au filtre, où Qt fait déjà le
    travail.
    """
    courante = MainWindow(trois_depots[0])
    qtbot.addWidget(courante)
    courante.show()
    qtbot.waitExposed(courante)

    partira = MainWindow(trois_depots[1])
    partira.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    partira.show()
    qtbot.waitExposed(partira)

    # Le menu est peuplé TANT QUE la fenêtre existe : l'action garde
    # une référence vers elle.
    bouton = _bouton_fenetres(courante)
    menu = bouton.menu()
    menu.aboutToShow.emit()
    vers_beta = [a for a in menu.actions() if "beta" in a.text()]
    assert vers_beta, "la fenêtre n'était pas listée au peuplement"

    # Puis elle disparaît, avant le clic.
    partira.close()
    qtbot.waitUntil(lambda: not still_alive(partira), timeout=3000)

    # Le clic ne doit pas lever.
    vers_beta[0].trigger()
    qtbot.wait(50)


# --- ce qui ne doit pas se dégrader -------------------------------------


def test_the_neighbouring_buttons_are_untouched(qtbot, trois_depots):
    """« Open Recent » et « Open Project » restent en place.

    Le piège : ajouter le bouton en déplaçant ou remplaçant ses
    voisins.
    """
    f = MainWindow(trois_depots[0])
    qtbot.addWidget(f)
    f.show()
    qtbot.waitExposed(f)

    intitules = {b.text() for b in f.findChildren(QToolButton)}

    assert "Open Recent" in intitules
    assert "Open Project" in intitules
    assert "Windows" in intitules


def test_the_button_survives_having_no_editor(qtbot, trois_depots):
    """Le bouton est ajouté APRÈS un bloc conditionnel.

    « Open in editor » n'apparaît que si un éditeur est installé. Si le
    bouton « Windows » tombait dans ce `if`, il disparaîtrait chez
    quelqu'un sans éditeur — et personne ne le verrait, puisque la
    machine de développement en a toujours un.
    """
    import tortoisepy.ui.main_window as module

    with patch.object(module, "find_editors", return_value=()):
        f = module.MainWindow(trois_depots[0])
    qtbot.addWidget(f)
    f.show()
    qtbot.waitExposed(f)

    intitules = {b.text() for b in f.findChildren(QToolButton)}
    assert "Open in editor" not in intitules, "la sonde est invalide"
    assert "Windows" in intitules, (
        "le bouton a disparu avec le bloc de l'éditeur"
    )
    # Et il fonctionne.
    assert len(_nos_entrees(f)) == 1


def test_a_title_without_the_suffix_is_left_alone(qtbot, trois_depots):
    """`removesuffix` ne doit pas tronquer un titre atypique.

    Le menu retire « — tortoisePy » du titre. Un titre qui ne le porte
    pas doit passer tel quel, pas être amputé.
    """
    f = MainWindow(trois_depots[0])
    qtbot.addWidget(f)
    f.show()
    qtbot.waitExposed(f)

    f.setWindowTitle("sans-suffixe")

    assert _nos_entrees(f) == ["sans-suffixe"]


def test_no_menu_bar_was_introduced(qtbot, trois_depots):
    """Un `QToolButton`, comme ses voisins — pas une barre de menus.

    Le code le dit : « ce projet n'a pas de `QMenuBar`, tout vit dans
    la barre d'outils ». Introduire une barre de menus pour une seule
    entrée changerait l'aspect de la fenêtre, que l'utilisateur a
    validé.
    """
    f = MainWindow(trois_depots[0])
    qtbot.addWidget(f)
    f.show()
    qtbot.waitExposed(f)

    barre = f.menuBar()
    assert barre is None or barre.isHidden() or not barre.actions(), (
        "une barre de menus est apparue"
    )
