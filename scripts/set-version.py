#!/usr/bin/env python3
"""Porte la version du projet partout où elle est écrite.

`pyproject.toml` est la **source unique** : c'est lui que lisent `uv`, `pip`
et `importlib.metadata`, donc c'est lui qui fait foi. Les autres fichiers en
sont des copies, et ce script les régénère.

Pourquoi des copies plutôt qu'une lecture à l'exécution : les deux
installeurs tournent **avant** tout clone — `pyproject.toml` n'existe pas
encore sur la machine de l'utilisateur quand `curl … | sh` démarre. Leur
version doit donc être écrite en dur, et le README cite ces mêmes URL.

    python scripts/set-version.py 0.3.0     # pose la version
    python scripts/set-version.py           # affiche la version courante

Ne touche pas au dépôt Git : ni commit, ni tag. C'est une décision de
l'utilisateur, pas de l'outil.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent

GABARIT = re.compile(r"^\d+\.\d+\.\d+$")


def version_courante() -> str:
    config = tomllib.loads((RACINE / "pyproject.toml").read_text())
    return config["project"]["version"]


def _remplacer(chemin: Path, motif: str, remplacement: str) -> int:
    """Applique un remplacement et rend le nombre de lignes changées."""
    avant = chemin.read_text()
    apres, nombre = re.subn(motif, remplacement, avant)
    if nombre:
        chemin.write_text(apres)
    return nombre


def poser(version: str) -> list[tuple[str, int]]:
    """Écrit `version` partout. Rend (fichier, occurrences) pour chacun."""
    tag = f"v{version}"
    resultats: list[tuple[str, int]] = []

    # `pyproject.toml` — la source. On vise la clé du bloc [project] et non
    # n'importe quelle ligne `version = …`, qui pourrait apparaître ailleurs.
    resultats.append((
        "pyproject.toml",
        _remplacer(
            RACINE / "pyproject.toml",
            r'(?m)^version = "\d+\.\d+\.\d+"$',
            f'version = "{version}"',
        ),
    ))

    # Le README cite les URL d'installation, qui portent le tag.
    resultats.append((
        "README.md",
        _remplacer(RACINE / "README.md", r"v\d+\.\d+\.\d+", tag),
    ))

    # Les deux installeurs : la variable ET l'URL de leur en-tête.
    for nom in ("install.sh", "install.ps1"):
        resultats.append((
            f"scripts/{nom}",
            _remplacer(RACINE / "scripts" / nom, r"v\d+\.\d+\.\d+", tag),
        ))

    return resultats


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)

    if not arguments:
        print(version_courante())
        return 0

    version = arguments[0].lstrip("v")
    if not GABARIT.match(version):
        print(
            f"Version invalide : « {arguments[0]} ». Attendu : 1.2.3",
            file=sys.stderr,
        )
        return 1

    ancienne = version_courante()
    for fichier, nombre in poser(version):
        print(f"  {fichier:<22} {nombre} occurrence(s)")

    print(f"\n{ancienne} → {version}")
    print("\nIl reste à committer, puis à créer le tag :")
    print(f"    git tag v{version} && git push origin v{version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
