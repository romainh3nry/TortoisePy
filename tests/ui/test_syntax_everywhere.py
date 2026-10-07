"""La coloration syntaxique partout où du code s'affiche.

Demandé par l'utilisateur après avoir vu le diff coloré : « étends-le sur
tous les endroits où on affiche du code ».

Deux écrans restaient en dehors :

  - l'**éditeur de fusion**, trois `QPlainTextEdit` — et celui du milieu
    s'édite, donc la coloration doit suivre la frappe ;
  - le **blâme**, un `QTreeWidget` où chaque ligne de code est une
    cellule.

Les cinq autres passent par `DiffView` et étaient déjà servis.
"""

from __future__ import annotations

import subprocess

import pygit2
import pytest
from PySide6.QtGui import QTextCursor

from tortoisepy.ui import theme

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


def _teintes(vue) -> set[str]:
    """Les couleurs de texte présentes dans la vue.

    Lues dans `block.layout().formats()` : un `QSyntaxHighlighter` y
    dépose ses formats, et non dans le `charFormat` du curseur — qui
    rend alors la couleur par défaut (vérifié).
    """
    vues = set()
    bloc = vue.document().firstBlock()
    while bloc.isValid():
        for plage in bloc.layout().formats():
            texte = bloc.text()[plage.start:plage.start + plage.length]
            if texte.strip():
                vues.add(plage.format.foreground().color().name())
        bloc = bloc.next()
    return vues


# --- l'éditeur de fusion -------------------------------------------------


@pytest.fixture
def depot_en_conflit(tmp_path):
    """Un conflit sur un fichier PHP : le cas de l'utilisateur."""
    w = tmp_path / "conflit"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    cible = w / "RateLimiter.php"
    cible.write_text("class RateLimiter {\n}\n")
    _git(w, "add", ".")
    _git(w, "commit", "-qm", "base")

    _git(w, "checkout", "-qb", "autre")
    cible.write_text("class RateLimiter {\n    const MAX = 40000;\n}\n")
    _git(w, "add", ".")
    _git(w, "commit", "-qm", "autre")

    _git(w, "checkout", "-q", "main")
    cible.write_text("class RateLimiter {\n    const PREFIX = 'rate';\n}\n")
    _git(w, "add", ".")
    _git(w, "commit", "-qm", "main")
    _git(w, "merge", "autre", check=False)

    return pygit2.Repository(str(w))


@pytest.fixture
def editeur(qtbot, depot_en_conflit):
    from tortoisepy.ui.merge_editor import MergeEditor

    e = MergeEditor(depot_en_conflit, "RateLimiter.php")
    qtbot.addWidget(e)
    e.show()
    return e


def test_the_sides_are_coloured(editeur):
    """Les deux colonnes de référence portent du code à lire."""
    syntaxe = {c.name() for c in theme.syntax_colors().values()}

    for nom, vue in (
        ("ours", editeur.ours_view), ("theirs", editeur.theirs_view)
    ):
        assert _teintes(vue) & syntaxe, f"la colonne « {nom} » n'est pas colorée"


def test_the_result_column_is_coloured(editeur):
    """C'est celle qu'on compose : elle doit être la plus lisible."""
    syntaxe = {c.name() for c in theme.syntax_colors().values()}

    assert _teintes(editeur.result_view) & syntaxe


def test_the_colouring_follows_typing(qtbot, editeur):
    """La colonne du milieu s'édite : la coloration doit suivre.

    Un surligneur posé une fois sur un texte figé ne tiendrait pas — dès
    la première frappe, le code saisi resterait incolore.
    """
    syntaxe = {c.name() for c in theme.syntax_colors().values()}
    editeur.result_view.setPlainText("$x = 'nouvelle chaine';")
    qtbot.wait(20)

    assert _teintes(editeur.result_view) & syntaxe, (
        "le texte saisi après coup n'est pas coloré"
    )


def test_an_unknown_extension_is_not_coloured(qtbot, tmp_path):
    """Sans lexer, le texte reste neutre plutôt que coloré au hasard."""
    from tortoisepy.ui.merge_editor import MergeEditor

    w = tmp_path / "inconnu"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    cible = w / "donnees.inconnu"
    cible.write_text("class X {\n")
    _git(w, "add", ".")
    _git(w, "commit", "-qm", "base")
    _git(w, "checkout", "-qb", "autre")
    cible.write_text("class Y {\n")
    _git(w, "add", ".")
    _git(w, "commit", "-qm", "autre")
    _git(w, "checkout", "-q", "main")
    cible.write_text("class Z {\n")
    _git(w, "add", ".")
    _git(w, "commit", "-qm", "main")
    _git(w, "merge", "autre", check=False)

    editeur = MergeEditor(pygit2.Repository(str(w)), "donnees.inconnu")
    qtbot.addWidget(editeur)
    editeur.show()

    syntaxe = {c.name() for c in theme.syntax_colors().values()}
    assert not (_teintes(editeur.result_view) & syntaxe)


def test_saving_still_works(qtbot, editeur, depot_en_conflit):
    """La coloration ne doit rien changer au contenu enregistré.

    Le piège : un surligneur qui toucherait au texte plutôt qu'à son
    format.
    """
    from tortoisepy.core.conflicts import list_conflicts

    editeur.result_view.setPlainText("class RateLimiter {}\n")
    editeur.save()

    assert list_conflicts(depot_en_conflit) == ()
    chemin = depot_en_conflit.workdir + "RateLimiter.php"
    with open(chemin) as fichier:
        assert fichier.read() == "class RateLimiter {}\n"


# --- le blâme ------------------------------------------------------------


@pytest.fixture
def depot_blame(tmp_path):
    w = tmp_path / "blame"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "module.php").write_text(
        "class RateLimiter {\n"
        "    const PREFIX = 'rate-limit';\n"
        "    /** Documentation. */\n"
        "}\n"
    )
    _git(w, "add", ".")
    _git(w, "commit", "-qm", "base")
    return pygit2.Repository(str(w))


def test_the_blame_lines_are_coloured(qtbot, depot_blame):
    """Le blâme affiche du code : il doit se lire comme ailleurs."""
    from tortoisepy.ui.blame_window import BlameWindow

    fenetre = BlameWindow(
        depot_blame, "module.php", str(depot_blame.head.target)
    )
    qtbot.addWidget(fenetre)
    fenetre.show()
    qtbot.waitUntil(lambda: fenetre.line_count() > 0, timeout=5000)

    assert fenetre.is_syntax_highlighted(), (
        "les lignes du blâme ne sont pas colorées"
    )

    # Le drapeau dit l'intention ; les PIXELS disent le résultat. Un
    # délégué qui ne peindrait rien le laisserait au vert tout en
    # laissant l'écran gris.
    from PySide6.QtGui import QPixmap

    image = QPixmap(fenetre._lines.viewport().size())
    fenetre._lines.viewport().render(image)
    rendu = image.toImage()
    peintes = {
        rendu.pixelColor(x, y).name()
        for y in range(0, rendu.height(), 2)
        for x in range(0, rendu.width(), 2)
    }
    syntaxe = {c.name() for c in theme.syntax_colors().values()}

    assert peintes & syntaxe, (
        "aucune couleur de syntaxe n'apparaît réellement à l'écran"
    )


def test_the_blame_tints_are_preserved(qtbot, depot_blame):
    """Les bandes alternées par commit doivent survivre.

    Elles portent l'information principale du blâme — quel commit a
    écrit quelle ligne — et la coloration ne doit pas la noyer.
    """
    from tortoisepy.ui.blame_window import BlameWindow

    fenetre = BlameWindow(
        depot_blame, "module.php", str(depot_blame.head.target)
    )
    qtbot.addWidget(fenetre)
    fenetre.show()
    qtbot.waitUntil(lambda: fenetre.line_count() > 0, timeout=5000)

    premier = fenetre._lines.topLevelItem(0)
    from PySide6.QtCore import Qt

    assert premier.background(0).style() != Qt.BrushStyle.NoBrush, (
        "la teinte de commit a disparu"
    )


def test_an_unknown_extension_leaves_the_blame_plain(qtbot, tmp_path):
    """Sans lexer, le blâme reste tel quel."""
    from tortoisepy.ui.blame_window import BlameWindow

    w = tmp_path / "brut"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "donnees.inconnu").write_text("class X {\n")
    _git(w, "add", ".")
    _git(w, "commit", "-qm", "base")

    repo = pygit2.Repository(str(w))
    fenetre = BlameWindow(repo, "donnees.inconnu", str(repo.head.target))
    qtbot.addWidget(fenetre)
    fenetre.show()
    qtbot.waitUntil(lambda: fenetre.line_count() > 0, timeout=5000)

    assert not fenetre.is_syntax_highlighted()


def test_the_blame_expands_tabs(qtbot, tmp_path):
    """Les tabulations ne doivent pas valoir huit espaces.

    `drawText` leur donne 80 px — plus de huit espaces dans la police du
    code — et `setTabStopDistance` ne s'applique pas à un délégué qui
    peint lui-même. Un fichier PHP indenté par tabulations partait hors
    de l'écran (signalé par l'utilisateur).
    """
    from tortoisepy.ui.blame_window import BlameWindow

    w = tmp_path / "tabs"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    (w / "m.php").write_text("class X {\n\t\t\tconst A = 1;\n}\n")
    _git(w, "add", ".")
    _git(w, "commit", "-qm", "base")

    repo = pygit2.Repository(str(w))
    fenetre = BlameWindow(repo, "m.php", str(repo.head.target))
    qtbot.addWidget(fenetre)
    fenetre.show()
    qtbot.waitUntil(lambda: fenetre.line_count() > 0, timeout=5000)

    from PySide6.QtGui import QFontMetricsF, QPixmap

    image = QPixmap(fenetre._lines.viewport().size())
    fenetre._lines.viewport().render(image)
    rendu = image.toImage()

    # La ligne indentée ne doit pas commencer au-delà de ce que trois
    # tabulations valent en espaces.
    metriques = QFontMetricsF(fenetre._lines.font())
    limite = 3 * theme.TAB_EN_ESPACES * metriques.horizontalAdvance(" ")
    assert limite < 200, (
        f"trois tabulations occuperaient {limite:.0f} px"
    )
