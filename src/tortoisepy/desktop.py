"""Mise en place de l'icône au niveau du système.

`setWindowIcon` suffit pour la fenêtre et, sur Windows, pour la barre des
tâches. Mais le Dock de macOS lit l'icône du **bundle**, pas celle de la
fenêtre : lancé comme un simple script, tortoisePy y apparaît avec la
fusée de l'interpréteur Python.

Ce module fabrique donc, une fois, un `tortoisePy.app` qui appelle
l'interpréteur et le paquet déjà installés. Ce n'est pas une
distribution : juste un lanceur qui porte la bonne icône.

Sans Qt : appelé avant que `QApplication` n'existe.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BUNDLE_NAME = "tortoisePy.app"

_INFO_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>            <string>tortoisePy</string>
  <key>CFBundleDisplayName</key>     <string>tortoisePy</string>
  <key>CFBundleIdentifier</key>      <string>fr.tortoisepy.app</string>
  <key>CFBundleVersion</key>         <string>{version}</string>
  <key>CFBundleShortVersionString</key> <string>{version}</string>
  <key>CFBundlePackageType</key>     <string>APPL</string>
  <key>CFBundleExecutable</key>      <string>tortoisepy</string>
  <key>CFBundleIconFile</key>        <string>tortoisepy.icns</string>
  <key>NSHighResolutionCapable</key> <true/>
</dict>
</plist>
"""

_LANCEUR = """#!/bin/bash
# Ouvre le dépôt du dossier courant, ou celui passé en argument.
exec "{python}" "{point_entree}" "$@"
"""

_POINT_ENTREE = '''"""Point d\'entrée du bundle macOS.

Un fichier plutôt qu\'un `python -c` : avec `-c`, `sys.argv[0]` vaut
« -c », et Qt en tire le nom affiché de l\'application.
"""

from tortoisepy.cli import main

raise SystemExit(main())
'''


def icon_path(name: str) -> Path:
    """Chemin d'un fichier d'icône livré avec le paquet."""
    return Path(__file__).parent / "resources" / name


def default_bundle_location() -> Path:
    """Où déposer le bundle : le dossier Applications de l'utilisateur.

    Pas `/Applications`, qui demanderait les droits administrateur pour
    une application qui n'en a pas besoin.
    """
    return Path.home() / "Applications" / BUNDLE_NAME


def is_installed(location: Path | None = None) -> bool:
    """Le bundle est-il déjà en place, avec son icône ?"""
    bundle = location or default_bundle_location()
    return (bundle / "Contents" / "Resources" / "tortoisepy.icns").exists()


def install_bundle(location: Path | None = None) -> Path | None:
    """Crée le bundle macOS. Rend son chemin, ou `None` si impossible.

    Ne lève jamais : une icône est un confort, et son échec ne doit pas
    empêcher l'application de s'ouvrir.
    """
    if sys.platform != "darwin":
        return None

    icns = icon_path("tortoisepy.icns")
    if not icns.exists():
        return None

    bundle = location or default_bundle_location()

    try:
        from tortoisepy.cli import __version__

        contents = bundle / "Contents"
        (contents / "MacOS").mkdir(parents=True, exist_ok=True)
        (contents / "Resources").mkdir(parents=True, exist_ok=True)

        (contents / "Resources" / "tortoisepy.icns").write_bytes(
            icns.read_bytes()
        )
        (contents / "Info.plist").write_text(
            _INFO_PLIST.format(version=__version__), encoding="utf-8"
        )

        # Un vrai fichier plutôt qu'un `python -c` : avec `-c`,
        # `sys.argv[0]` vaut « -c » et Qt en tire le nom affiché.
        point_entree = contents / "Resources" / "lanceur.py"
        point_entree.write_text(_POINT_ENTREE, encoding="utf-8")

        lanceur = contents / "MacOS" / "tortoisepy"
        # `sys.executable` : l'interpréteur courant est celui qui sait
        # importer `tortoisepy`. Un `python3` du PATH pourrait ne pas
        # avoir le paquet.
        lanceur.write_text(
            _LANCEUR.format(
                python=sys.executable, point_entree=point_entree
            ),
            encoding="utf-8",
        )
        lanceur.chmod(0o755)

        # macOS garde son cache d'icônes : sans cette touche, il continue
        # d'afficher l'ancienne.
        os.utime(bundle, None)
        return bundle
    except OSError:
        return None


def install_if_missing() -> Path | None:
    """Pose l'icône au premier lancement, puis ne fait plus rien.

    `TORTOISEPY_NO_DESKTOP_INSTALL` permet de s'y opposer — utile dans
    les tests et pour qui ne veut rien voir apparaître dans Applications.
    """
    if os.environ.get("TORTOISEPY_NO_DESKTOP_INSTALL"):
        return None
    if sys.platform != "darwin":
        return None
    if is_installed():
        return None
    return install_bundle()
