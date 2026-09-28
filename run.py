#!/usr/bin/env python3
"""Lanceur de développement — ouvre la fenêtre sur un dépôt Git.

    ./run.py                  # dépôt du dossier courant
    ./run.py ~/mon/projet     # dépôt à ce chemin

Provisoire : il tient lieu de commande `tgraph` en attendant la phase 5.
La CLI définitive vivra dans `src/tortoisepy/cli.py`.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import pygit2
from PySide6.QtWidgets import QApplication

from tortoisepy.ui.main_window import MainWindow


def find_repository(start: str) -> pygit2.Repository | None:
    """Remonte l'arborescence comme le fait Git.

    `discover_repository` retourne `None` quand il ne trouve rien — vérifié
    sur pygit2 1.20 ; le try/except couvre les versions qui lèvent.
    """
    try:
        path = pygit2.discover_repository(start)
    except (pygit2.GitError, KeyError):
        return None

    return pygit2.Repository(path) if path else None


def main() -> int:
    target = sys.argv[1] if len(sys.argv) > 1 else "."

    repository = find_repository(target)
    if repository is None:
        print(f"Pas de dépôt Git trouvé dans {target}", file=sys.stderr)
        return 1

    # La QApplication doit exister avant toute opération de police : sans
    # elle, Qt abandonne le processus au lieu de lever (vérifié).
    app = QApplication(sys.argv[:1])

    window = MainWindow(repository)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
