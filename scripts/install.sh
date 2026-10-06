#!/usr/bin/env bash
#
# Installe tortoisePy et sa commande `topy` — macOS et Linux.
#
# `uv` plutôt que `pip` : il crée un environnement isolé ET télécharge
# l'interpréteur au besoin. L'utilisateur n'a donc pas à installer
# Python 3.13 lui-même, ce qui est le vrai obstacle.
#
#   curl -LsSf https://raw.githubusercontent.com/romainh3nry/TortoisePy/v0.9.0/scripts/install.sh | sh

set -euo pipefail

VERSION="v0.9.0"
DEPOT="git+https://github.com/romainh3nry/TortoisePy@${VERSION}"

echo "tortoisePy ${VERSION}"
echo

if ! command -v uv >/dev/null 2>&1; then
    echo "→ Installation de uv…"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # `uv` vient d'être posé : il n'est pas encore visible dans CE shell.
    export PATH="$HOME/.local/bin:$PATH"
fi

echo "→ Installation de tortoisePy…"
echo "  (environ 1,2 Go à télécharger : c'est Qt, pas une erreur)"
# `--force` pour que relancer le script mette à jour plutôt que d'échouer.
uv tool install --force "${DEPOT}"

echo

# Vérifier son propre résultat : l'installation peut parfaitement réussir
# alors que la commande reste introuvable, faute de PATH (vérifié — `uv`
# le signale lui-même). C'est précisément là qu'un utilisateur abandonne,
# en croyant que l'installation a échoué.
if command -v topy >/dev/null 2>&1 && topy --version >/dev/null 2>&1; then
    echo "✓ $(topy --version) installé."
    echo
    echo "  Placez-vous dans un projet Git et lancez :"
    echo "      topy ."
    echo
    echo "  Ou visez un dépôt ailleurs :"
    echo "      topy ~/code/mon-projet"
else
    echo "⚠ tortoisePy est installé, mais « topy » n'est pas dans votre PATH."
    echo
    echo "  Le plus simple :"
    echo "      uv tool update-shell"
    echo
    echo "  Ou ajoutez cette ligne à votre ~/.zshrc (ou ~/.bashrc) :"
    echo "      export PATH=\"\$HOME/.local/bin:\$PATH\""
    echo
    echo "  Puis rouvrez votre terminal."
    exit 1
fi
