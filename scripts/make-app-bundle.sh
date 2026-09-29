#!/usr/bin/env bash
# Fabrique « tortoisePy.app », un bundle macOS qui porte sa propre icône.
#
# Pourquoi un bundle : lancé comme un simple script, l'application est vue
# par macOS comme l'interpréteur Python, et le Dock affiche la fusée de
# Python. `setWindowIcon` ne suffit pas à corriger cela — seul un bundle
# avec son `Info.plist` et son `.icns` donne une icône fiable, sans
# ajouter de dépendance (ni pyobjc, ni py2app).
#
# Le bundle ne copie pas Python : il appelle l'interpréteur et le paquet
# déjà installés. Il s'agit d'un lanceur, pas d'une distribution.
#
# Usage :
#   scripts/make-app-bundle.sh [dossier-de-sortie]   (défaut : ~/Applications)
set -euo pipefail

racine="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
sortie="${1:-$HOME/Applications}"
bundle="$sortie/tortoisePy.app"

icns="$racine/src/tortoisepy/resources/tortoisepy.icns"
if [ ! -f "$icns" ]; then
  echo "Icône absente : $icns" >&2
  echo "Lancez d'abord : scripts/make-icon.py" >&2
  exit 1
fi

# L'interpréteur du venv s'il existe, sinon celui du PATH : le bundle doit
# retrouver `tortoisepy`, pas n'importe quel Python.
if [ -x "$racine/.venv/bin/python" ]; then
  python_bin="$racine/.venv/bin/python"
else
  python_bin="$(command -v python3)"
fi

mkdir -p "$bundle/Contents/MacOS" "$bundle/Contents/Resources"
cp "$icns" "$bundle/Contents/Resources/tortoisepy.icns"

cat > "$bundle/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>            <string>tortoisePy</string>
  <key>CFBundleDisplayName</key>     <string>tortoisePy</string>
  <key>CFBundleIdentifier</key>      <string>fr.tortoisepy.app</string>
  <key>CFBundleVersion</key>         <string>0.1.0</string>
  <key>CFBundleShortVersionString</key> <string>0.1.0</string>
  <key>CFBundlePackageType</key>     <string>APPL</string>
  <key>CFBundleExecutable</key>      <string>tortoisepy</string>
  <key>CFBundleIconFile</key>        <string>tortoisepy.icns</string>
  <key>NSHighResolutionCapable</key> <true/>
</dict>
</plist>
PLIST

cat > "$bundle/Contents/MacOS/tortoisepy" <<LANCEUR
#!/bin/bash
# Ouvre le dépôt du dossier courant, ou celui passé en argument.
exec "$python_bin" -c "from tortoisepy.cli import main; raise SystemExit(main())" "\$@"
LANCEUR
chmod +x "$bundle/Contents/MacOS/tortoisepy"

# Forcer macOS à relire l'icône : il met son cache en défaut sinon.
touch "$bundle"

echo "Bundle créé : $bundle"
echo "Interpréteur : $python_bin"
