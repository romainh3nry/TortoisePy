"""Identifiants HTTPS, délégués à Git — §7.3.

libgit2 **ne consulte pas** le gestionnaire d'identifiants de Git : sans
rappel, un push HTTPS échoue sur « remote authentication required but no
callback set ». On interroge donc `git credential`, qui est l'interface
documentée et *multi-plateforme* de Git : trousseau macOS (`osxkeychain`),
Git Credential Manager sur Windows, `libsecret` sur Linux. tortoisePy n'a
pas à connaître ces backends — Git sait lequel utiliser.

Rien n'est stocké par tortoisePy : les secrets restent chez Git.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from urllib.parse import urlparse

_TIMEOUT = 15.0
"""Le helper peut ouvrir une fenêtre système ; au-delà, on abandonne
plutôt que de figer l'interface."""


@dataclass(frozen=True)
class Credentials:
    username: str
    password: str

    def __repr__(self) -> str:  # pragma: no cover - garde-fou
        """Ne jamais laisser fuir le secret dans une trace ou un log."""
        return f"Credentials(username={self.username!r}, password=***)"


def is_https(url: str) -> bool:
    return url.startswith(("http://", "https://"))


def credentials_for(url: str) -> Credentials | None:
    """Identifiants connus de Git pour cette URL, ou `None`.

    `GIT_TERMINAL_PROMPT=0` est indispensable : sans lui, Git tenterait de
    poser une question sur un terminal qui n'existe pas dans une
    application graphique, et l'appel resterait suspendu. Vérifié : sans
    identifiant, la commande sort en 128 en ~30 ms, sans rien écrire.
    """
    query = _query(url)
    if query is None:
        return None

    try:
        result = subprocess.run(
            ["git", "credential", "fill"],
            input=query,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except (OSError, subprocess.SubprocessError):
        return None

    if result.returncode != 0:
        return None

    fields = _parse(result.stdout)
    username, password = fields.get("username"), fields.get("password")
    if not username or not password:
        return None
    return Credentials(username=username, password=password)


def remember(url: str, credentials: Credentials) -> bool:
    """Confie ces identifiants au gestionnaire de Git. Vrai si accepté.

    C'est `git credential approve` qui décide où les ranger — trousseau
    macOS, Credential Manager Windows… — exactement comme lorsque `git
    push` les enregistre.
    """
    query = _query(url)
    if query is None:
        return False

    # Le protocole est ligne par ligne : un saut de ligne dans un champ
    # le corromprait, et pourrait injecter une clé arbitraire.
    if any(c in credentials.username or c in credentials.password
           for c in ("\n", "\r", "\0")):
        return False

    payload = (
        query.rstrip("\n")
        + f"\nusername={credentials.username}"
        + f"\npassword={credentials.password}\n\n"
    )

    try:
        result = subprocess.run(
            ["git", "credential", "approve"],
            input=payload,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _query(url: str) -> str | None:
    """Requête au format de `git credential`, ou `None` si l'URL ne s'y prête.

    Le `path` est transmis : certains hébergeurs distinguent les
    identifiants par dépôt, et Git l'ignore de lui-même quand
    `credential.useHttpPath` est faux.
    """
    if not is_https(url):
        return None

    parsed = urlparse(url)
    if not parsed.hostname:
        return None

    lines = [f"protocol={parsed.scheme}", f"host={parsed.hostname}"]
    if parsed.port:
        lines[-1] = f"host={parsed.hostname}:{parsed.port}"
    if parsed.username:
        lines.append(f"username={parsed.username}")
    path = parsed.path.lstrip("/")
    if path:
        lines.append(f"path={path}")
    return "\n".join(lines) + "\n\n"


def _parse(output: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in output.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            fields[key] = value
    return fields
