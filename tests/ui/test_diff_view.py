import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QTextCursor

from tortoisepy.core.changes import DiffHunk, DiffLine, FileDiff
from tortoisepy.ui import theme
from tortoisepy.ui.diff_view import DiffView


def _format_at(view, line_index):
    """Format de caractère réel d'une ligne rendue.

    `block.layout().formats()` ne convient pas : il ne contient que les
    formats additionnels, pas ceux stockés dans le document (vérifié).
    """
    doc = view.document()
    block = doc.findBlockByNumber(line_index)
    cursor = QTextCursor(doc)
    cursor.setPosition(block.position() + 1)
    return cursor.charFormat()


@pytest.fixture
def view(qtbot):
    widget = DiffView()
    qtbot.addWidget(widget)
    return widget


def sample() -> FileDiff:
    return FileDiff(
        path="src/app.py",
        hunks=(
            DiffHunk(
                header="@@ -1,3 +1,4 @@",
                lines=(
                    DiffLine(" ", "contexte"),
                    DiffLine("-", "ancienne ligne"),
                    DiffLine("+", "nouvelle ligne"),
                ),
            ),
        ),
        added=1,
        removed=1,
    )


def test_starts_empty(view):
    assert view.line_count() == 0


def test_shows_every_line(view):
    view.show_diff(sample())
    # 1 en-tête de hunk + 3 lignes
    assert view.line_count() == 4


def test_keeps_the_line_content(view):
    view.show_diff(sample())
    assert "nouvelle ligne" in view.text()
    assert "ancienne ligne" in view.text()


def test_shows_the_hunk_header(view):
    view.show_diff(sample())
    assert "@@ -1,3 +1,4 @@" in view.text()


def test_binary_file_says_so(view):
    """Review Focus 1 : afficher des octets bruts serait illisible."""
    view.show_diff(FileDiff(path="image.png", is_binary=True))
    assert "binaire" in view.text().lower()
    assert view.line_count() == 1


def test_empty_diff_says_so(view):
    view.show_diff(FileDiff(path="vide.txt"))
    assert view.text()


def test_showing_again_replaces_the_previous(view):
    view.show_diff(sample())
    view.show_diff(FileDiff(path="autre.txt", is_binary=True))
    assert "nouvelle ligne" not in view.text()


def test_clear_empties_the_view(view):
    view.show_diff(sample())
    view.clear()
    assert view.line_count() == 0


def test_uses_a_monospace_font(view):
    """Un diff aligné en colonnes exige une chasse fixe."""
    assert view.font().fixedPitch() is True


def test_is_read_only(view):
    """Le diff se lit, il ne s'édite pas."""
    assert view.isReadOnly()


def test_added_line_has_the_added_background(view):
    view.show_diff(sample())
    # lignes : 0=en-tête, 1=contexte, 2=supprimée, 3=ajoutée
    fmt = _format_at(view, 3)
    assert fmt.background().style() != Qt.BrushStyle.NoBrush
    assert fmt.background().color() == theme.DIFF_ADDED


def test_removed_line_has_the_removed_background(view):
    view.show_diff(sample())
    fmt = _format_at(view, 2)
    assert fmt.background().style() != Qt.BrushStyle.NoBrush
    assert fmt.background().color() == theme.DIFF_REMOVED


def test_context_line_has_no_background(view):
    """Le contexte reste neutre — un fond y attirerait l'œil à tort."""
    view.show_diff(sample())
    fmt = _format_at(view, 1)
    assert fmt.background().style() == Qt.BrushStyle.NoBrush


def test_hunk_header_uses_the_header_colour(view):
    view.show_diff(sample())
    fmt = _format_at(view, 0)
    assert fmt.foreground().color() == theme.DIFF_HEADER


def test_binary_message_uses_the_header_colour(view):
    view.show_diff(FileDiff(path="image.png", is_binary=True))
    fmt = _format_at(view, 0)
    assert fmt.foreground().color() == theme.DIFF_HEADER


def test_added_line_text_is_green(view):
    """Le fond seul ne suffit pas : le texte doit porter la couleur aussi."""
    view.show_diff(sample())
    fmt = _format_at(view, 3)
    assert fmt.foreground().color() == theme.DIFF_ADDED_TEXT


def test_removed_line_text_is_red(view):
    view.show_diff(sample())
    fmt = _format_at(view, 2)
    assert fmt.foreground().color() == theme.DIFF_REMOVED_TEXT


def _with_dark_palette(qtbot):
    """Bascule l'application en thème sombre, comme macOS le fait."""
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    previous = QPalette(app.palette())
    dark = QPalette(previous)
    dark.setColor(QPalette.ColorRole.Base, QColor(30, 30, 30))
    dark.setColor(QPalette.ColorRole.Text, QColor(238, 238, 238))
    app.setPalette(dark)
    return previous


def test_dark_theme_uses_dark_backgrounds(qtbot):
    """En thème sombre, les fonds pâles rendent la ligne illisible.

    Mesuré : du texte clair (238,238,238) sur le vert pâle du thème clair
    donne 1.02:1 — la ligne ajoutée disparaît sous son propre surlignage.
    C'est exactement ce que l'utilisateur a constaté sur macOS.
    """
    from PySide6.QtWidgets import QApplication

    previous = _with_dark_palette(qtbot)
    try:
        widget = DiffView()
        qtbot.addWidget(widget)
        widget.show_diff(sample())

        added = _format_at(widget, 3)
        removed = _format_at(widget, 2)

        assert added.background().color() == theme.DIFF_ADDED_DARK
        assert added.foreground().color() == theme.DIFF_ADDED_TEXT_DARK
        assert removed.background().color() == theme.DIFF_REMOVED_DARK
        assert removed.foreground().color() == theme.DIFF_REMOVED_TEXT_DARK
    finally:
        QApplication.instance().setPalette(previous)


def test_light_theme_keeps_the_pale_backgrounds(qtbot):
    """Le thème clair, lui, ne change pas : il était déjà lisible."""
    widget = DiffView()
    qtbot.addWidget(widget)
    widget.show_diff(sample())
    assert _format_at(widget, 3).background().color() == theme.DIFF_ADDED
