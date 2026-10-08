"""Gardes d'architecture : les couches ne remontent jamais vers l'UI (§5)."""

import ast
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "tortoisepy"

QT = ("PySide6", "PyQt6", "PyQt5")
UI = ("tortoisepy.ui",)


def _imports_of(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def _offenders(package: str, forbidden: tuple[str, ...]) -> list[str]:
    found: list[str] = []
    for path in (SRC / package).rglob("*.py"):
        for name in _imports_of(path):
            if any(name.startswith(f) for f in forbidden):
                found.append(f"{package}/{path.name} importe {name}")
    return found


def test_core_never_imports_qt_or_ui():
    offenders = _offenders("core", QT + UI + ("tortoisepy.layout",))
    assert not offenders, "core/ doit rester indépendant : " + "; ".join(offenders)


def test_layout_never_imports_qt_or_ui():
    """layout/ ne connaît ni la police de rendu ni Git : la mesure est injectée."""
    offenders = _offenders("layout", QT + UI)
    assert not offenders, "layout/ doit rester indépendant : " + "; ".join(offenders)


def test_layout_never_imports_pygit2():
    """layout/ travaille sur le modèle, jamais sur le dépôt."""
    offenders = _offenders("layout", ("pygit2",))
    assert not offenders, "layout/ ne doit pas dépendre de pygit2 : " + "; ".join(offenders)


def test_ui_is_the_only_layer_importing_qt():
    """§5 : seule `ui/` connaît PySide6."""
    for package in ("core", "layout"):
        assert not _offenders(package, QT), (
            f"{package}/ ne doit pas importer Qt"
        )


def test_ui_never_calls_pygit2_directly_for_operations():
    """`ui/` passe par core.operations, qui garantit OperationResult (§7.6).

    Lire le dépôt depuis `ui/` reste permis : la fenêtre reçoit un objet
    Repository. Ce qui est proscrit, c'est d'y faire des opérations
    d'écriture sans passer par la couche qui les encadre.
    """
    import ast
    from pathlib import Path

    forbidden = {"merge", "reset", "cherrypick", "revert", "create_branch"}
    offenders = []

    for path in (SRC / "ui").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr not in forbidden:
                continue
            value = func.value
            if isinstance(value, ast.Name) and value.id in {"repo", "repository"}:
                offenders.append(f"{path.name}: {func.attr}")

    assert not offenders, (
        "ui/ doit passer par core.operations : " + "; ".join(offenders)
    )


def test_no_module_uses_qmessagebox():
    """Aucune boîte de l'application ne doit être un `QMessageBox`.

    Signalé trois fois : l'app se ferme au checkout sur macOS 27. Qt
    traduit un `QMessageBox` aux boutons standard en `NSAlert` natif
    (mesuré : il crée un `_NSAlertPanel`, là où un `QDialog` ordinaire
    n'en crée pas), et le rendu d'Apple y lève une exception
    Objective-C que personne ne rattrape :

        QDialog::exec() -> -[NSAlert runModal]
          -> CUINamedVectorGlyph _rasterizeImageUsingScaleFactor:
            -> objc_exception_throw   ← abort()

    Deux corrections ont visé à côté avant celle-ci — l'icône système,
    puis la modale ouverte sous un menu. Ce garde empêche qu'un
    `QMessageBox.information` réapparaisse un jour par commodité : il
    rouvrirait le crash loin d'ici, sur une machine que nous n'avons
    pas.

    `dialogs.py` fournit `confirm`, `show_error` et `show_message`.
    """
    fautifs = [
        f"{chemin.relative_to(SRC)}:{numero}"
        for chemin in SRC.rglob("*.py")
        for numero, ligne in enumerate(
            chemin.read_text().splitlines(), start=1
        )
        if "QMessageBox" in ligne and not ligne.lstrip().startswith("#")
        and '"""' not in ligne and "`QMessageBox" not in ligne
    ]
    assert not fautifs, (
        "QMessageBox devient un NSAlert natif, qui plante macOS 27 ; "
        "utiliser dialogs.confirm / show_error / show_message : "
        + "; ".join(fautifs)
    )
