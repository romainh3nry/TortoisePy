"""Surveillance du dossier `.git` — §7.9.

Un dépôt n'est jamais modifié que par tortoisePy : un `git commit` tapé
dans le terminal doit se voir, sans quoi l'affichage ment.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Signal

GRACE_MS = 600
"""Durée pendant laquelle les événements consécutifs à une opération interne
sont ignorés (§7.9). Le système de fichiers notifie en différé : sans cette
grâce, l'application se réveillerait elle-même après chaque opération."""

DEBOUNCE_MS = 300
"""Une seule commande Git produit plusieurs événements : un `git commit`
touche l'index, HEAD et une ref. Sans temporisation, le graphe serait
reconstruit trois fois (§7.9)."""

_GRAPH_PATHS = ("HEAD", "packed-refs", "MERGE_HEAD", "ORIG_HEAD")
"""Fichiers dont la modification change le graphe."""

_STATE_PATHS = ("index",)
"""Fichiers dont la modification ne change que l'état (§7.8)."""


class RepositoryWatcher(QObject):
    """Signale les changements du dépôt survenus hors de l'application.

    Deux signaux distincts : reconstruire le graphe coûte bien plus cher que
    relire l'état, et un fichier indexé dans l'éditeur ne change pas le
    graphe (§7.8).
    """

    graph_changed = Signal()
    state_changed = Signal()

    def __init__(
        self, git_dir: str, debounce_ms: int = DEBOUNCE_MS, parent=None
    ):
        super().__init__(parent)
        self._git_dir = Path(git_dir)
        self._watcher: QFileSystemWatcher | None = None
        self._suspended = False
        self._pending_graph = False
        self._pending_state = False

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(debounce_ms)
        self._timer.timeout.connect(self._emit_pending)

        # Période de grâce après une opération interne : les événements du
        # système de fichiers arrivent en différé, après la sortie du bloc
        # `suspended()`. Sans elle, chaque opération lancée depuis
        # l'application provoquait un rafraîchissement parasite (mesuré).
        self._grace = QTimer(self)
        self._grace.setSingleShot(True)
        self._grace.setInterval(max(debounce_ms * 2, GRACE_MS))
        self._grace.timeout.connect(self._end_grace)

    def start(self) -> None:
        """Commence à surveiller. Sans effet si le dossier n'existe pas."""
        if self._watcher is not None:
            return
        if not self._git_dir.is_dir():
            return

        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_change)
        self._watcher.directoryChanged.connect(self._on_change)

        for path in self._paths_to_watch():
            self._watcher.addPath(str(path))

    def stop(self) -> None:
        """Arrête la surveillance. Appelable plusieurs fois sans dommage."""
        self._timer.stop()
        if self._watcher is None:
            return

        watched = self._watcher.files() + self._watcher.directories()
        if watched:
            self._watcher.removePaths(watched)

        self._watcher.deleteLater()
        self._watcher = None

    def is_watching(self) -> bool:
        return self._watcher is not None

    def watched_paths(self) -> tuple[str, ...]:
        if self._watcher is None:
            return ()
        return tuple(self._watcher.files() + self._watcher.directories())

    @contextmanager
    def suspended(self):
        """Suspend les notifications le temps d'une opération interne.

        Sans cela, chaque opération lancée depuis l'application
        déclencherait un rafraîchissement en plus de celui déjà prévu par
        `OperationResult.repository_changed` (§7.6).
        """
        previous = self._suspended
        self._suspended = True
        try:
            yield
        finally:
            self._pending_graph = False
            self._pending_state = False
            self._timer.stop()

            # Les événements du système de fichiers arrivent APRÈS la sortie
            # du bloc : mesuré, lever le drapeau tout de suite laissait
            # passer une notification parasite par opération interne.
            # La grâce couvre ce décalage.
            if previous:
                self._suspended = True
            else:
                self._grace.start()

    def _paths_to_watch(self) -> list[Path]:
        """Chemins existants à surveiller (§7.9).

        Le répertoire `.git` lui-même est inclus : mesuré, un `git checkout`
        émet trois événements de répertoire sur `.git` en plus de celui sur
        `HEAD`, et certains changements ne se voient que par là.
        """
        candidates = [self._git_dir]
        candidates += [self._git_dir / name for name in _GRAPH_PATHS]
        candidates += [self._git_dir / name for name in _STATE_PATHS]
        candidates.append(self._git_dir / "refs")

        refs = self._git_dir / "refs"
        if refs.is_dir():
            candidates.extend(p for p in refs.rglob("*") if p.is_dir())

        return [path for path in candidates if path.exists()]

    def _end_grace(self) -> None:
        self._suspended = False
        self._pending_graph = False
        self._pending_state = False
        self._timer.stop()

    def _on_change(self, path: str) -> None:
        if self._suspended or self._grace.isActive():
            return

        # Un événement de RÉPERTOIRE ne nomme pas le fichier modifié : il
        # porte le nom du dossier. Le classer par nom de fichier le ferait
        # passer pour un changement d'état. Dans le doute, on reconstruit
        # le graphe — une reconstruction de trop est sans conséquence, un
        # graphe périmé ment à l'utilisateur.
        name = Path(path).name
        if name in _STATE_PATHS and Path(path).is_file():
            self._pending_state = True
        else:
            self._pending_graph = True

        # Certains éditeurs remplacent le fichier : Qt cesse alors de le
        # surveiller. On le réarme.
        if self._watcher is not None and Path(path).exists():
            if path not in self.watched_paths():
                self._watcher.addPath(path)

        self._timer.start()

    def _emit_pending(self) -> None:
        if self._suspended:
            return

        if self._pending_graph:
            self._pending_graph = False
            self._pending_state = False
            self.graph_changed.emit()
        elif self._pending_state:
            self._pending_state = False
            self.state_changed.emit()
