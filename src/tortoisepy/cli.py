"""Point d'entrée `tgraph` — §8.

    tgraph              # dépôt du dossier courant
    tgraph /chemin      # dépôt à ce chemin
"""

from __future__ import annotations

import sys

import pygit2

__version__ = "0.1.0"


def find_repository(start: str) -> pygit2.Repository | None:
    """Remonte l'arborescence comme le fait Git.

    Vérifié sur pygit2 1.20 : `discover_repository` RETOURNE `None` quand
    elle ne trouve rien, elle ne lève pas. Le `try/except` couvre les
    versions qui levaient, et les chemins illisibles.
    """
    try:
        path = pygit2.discover_repository(start)
    except (pygit2.GitError, KeyError, ValueError):
        return None

    if not path:
        return None

    try:
        return pygit2.Repository(path)
    except (pygit2.GitError, KeyError, ValueError):
        return None


def main(argv: list[str] | None = None) -> int:
    """Ouvre la fenêtre sur le dépôt demandé."""
    arguments = list(sys.argv[1:] if argv is None else argv)

    if arguments and arguments[0] in ("--version", "-V"):
        print(f"tortoisePy {__version__}")
        return 0

    target = arguments[0] if arguments else "."

    repository = find_repository(target)
    if repository is None:
        print(f"Pas de dépôt Git trouvé dans {target}", file=sys.stderr)
        return 1

    # Les imports Qt restent ici : `--version` et le message d'erreur
    # ci-dessus ne doivent pas payer le chargement de PySide6.
    from PySide6.QtWidgets import QApplication

    from tortoisepy.ui.main_window import MainWindow

    # La QApplication doit exister avant toute opération de police :
    # sans elle, Qt abandonne le processus au lieu de lever (vérifié).
    app = QApplication(sys.argv[:1])

    window = MainWindow(repository)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
