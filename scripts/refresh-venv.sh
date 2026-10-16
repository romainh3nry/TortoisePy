#!/usr/bin/env bash
#
# Remet le venv local à la version déclarée dans `pyproject.toml`.
#
#   ./scripts/refresh-venv.sh
#
# Pourquoi c'est nécessaire. Un venv éditable pointe sur les sources :
# le CODE y est à jour immédiatement. Mais ses MÉTADONNÉES — dont la
# version — sont figées au moment de l'installation, et c'est elles
# que lit `importlib.metadata` pour `topy --version`.
#
# Donc une seule chose exige une réinstallation : monter la version.
# Toute autre modification est prise en compte sans rien faire.
#
# Avant, `set-version.py` s'en chargeait. Il a été supprimé quand la
# version a cessé d'être recopiée dans quatre fichiers, et ce geste
# est resté orphelin — `test_the_reported_version_follows_the_package`
# a échoué deux fois pour cette raison le 2026-10-16.

set -euo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RACINE"

attendue=$(grep -m1 '^version' pyproject.toml | cut -d'"' -f2)

if [ -z "$attendue" ]; then
    echo "version introuvable dans pyproject.toml" >&2
    exit 1
fi

# `uv` d'abord : un venv créé par `uv venv` n'embarque pas `pip`, et
# c'est le cas de celui de ce projet depuis sa reconstruction.
if command -v uv >/dev/null 2>&1; then
    uv pip install -q -e . --no-deps
elif [ -x .venv/bin/python ]; then
    .venv/bin/python -m pip install -q -e . --no-deps
else
    echo "ni uv ni .venv/bin/python : rien à rafraîchir" >&2
    exit 1
fi

obtenue=$(.venv/bin/topy --version 2>/dev/null | awk '{print $2}')

if [ "$obtenue" != "$attendue" ]; then
    echo "échec : topy annonce $obtenue, pyproject déclare $attendue" >&2
    exit 1
fi

echo "venv à jour : tortoisePy $attendue"
