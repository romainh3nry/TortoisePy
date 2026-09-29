#!/usr/bin/env python3
"""Fabrique les icônes de l'application à partir du logo.

Le logo source (`logo_topy_3.png`) porte le mot « tortoisePy » sous le
dessin. Ce mot est **retiré** des icônes : sous 64 px il devient une
bouillie illisible qui brouille la silhouette. Le point de coupe n'est pas
deviné — il est mesuré, en cherchant la bande horizontale entièrement
vide qui sépare le dessin du texte.

Produit :
  - `icon-{16,32,48,64,128,256,512}.png` — toutes plateformes
  - `tortoisepy.icns` — macOS (via `iconutil`)
  - `tortoisepy.ico`  — Windows, multi-tailles

Usage :
    python scripts/make-icon.py
"""

from __future__ import annotations

import struct
import subprocess
import sys
import tempfile
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
RESSOURCES = RACINE / "src" / "tortoisepy" / "resources"
SOURCE = RESSOURCES / "logo_topy_3.png"

TAILLES = (16, 32, 48, 64, 128, 256, 512)
TAILLES_ICO = (16, 32, 48, 64, 128, 256)

BLANC = 242
"""Au-dessus, un pixel compte comme fond. Le logo est sur blanc, pas sur
transparent : un seuil sur l'alpha ne suffirait pas."""


def _densite(image, y: int) -> int:
    """Nombre de pixels non blancs sur cette ligne."""
    total = 0
    for x in range(0, image.width(), 2):
        couleur = image.pixelColor(x, y)
        if couleur.alpha() > 20 and (
            couleur.red() < BLANC
            or couleur.green() < BLANC
            or couleur.blue() < BLANC
        ):
            total += 1
    return total


def _coupe_sous_le_dessin(image) -> int:
    """Hauteur à laquelle couper, juste avant le texte.

    Cherche la première bande horizontale vide sous le dessin. Mesurer
    plutôt qu'estimer : une première version coupait à 89 % et laissait
    le texte entier, une seconde à 72 % laissait le haut des lettres.
    """
    hauteur = image.height()
    debut = int(hauteur * 0.55)

    vides = 0
    for y in range(debut, hauteur):
        if _densite(image, y) == 0:
            vides += 1
            if vides >= 6:  # une vraie bande, pas un interstice du dessin
                return y - vides // 2
        else:
            vides = 0

    return hauteur  # pas de texte détecté : on garde tout


def _boite_utile(image):
    """Rectangle contenant le dessin, marges blanches exclues."""
    from PySide6.QtCore import QRect

    x0, y0 = image.width(), image.height()
    x1 = y1 = 0
    for y in range(0, image.height(), 2):
        for x in range(0, image.width(), 2):
            couleur = image.pixelColor(x, y)
            if couleur.alpha() > 20 and (
                couleur.red() < BLANC
                or couleur.green() < BLANC
                or couleur.blue() < BLANC
            ):
                x0, y0 = min(x0, x), min(y0, y)
                x1, y1 = max(x1, x), max(y1, y)
    return QRect(x0, y0, x1 - x0 + 1, y1 - y0 + 1)


def generer_png() -> None:
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QApplication

    QApplication(sys.argv[:1])

    source = QImage(str(SOURCE))
    if source.isNull():
        raise SystemExit(f"Logo introuvable ou illisible : {SOURCE}")

    coupe = _coupe_sous_le_dessin(source)
    dessin = source.copy(QRect(0, 0, source.width(), coupe))
    print(f"coupe à y={coupe} ({coupe / source.height():.0%}) — texte retiré")

    boite = _boite_utile(dessin)

    # Carré centré avec 8 % de marge : collée aux bords, une icône paraît
    # mal cadrée dans le Dock.
    # Le logo est sur fond blanc : tel quel, le Dock affiche un carré
    # blanc au lieu de la silhouette. On rend ce blanc transparent.
    dessin = _sans_fond_blanc(dessin)

    # Grille macOS : mesurée sur une icône système, le dessin occupe
    # ~80 % du canevas avec ~10 % de marge. Sans cela l'icône paraît
    # plus petite ou plus grande que ses voisines dans le Dock.
    cote = int(max(boite.width(), boite.height()) / 0.80)
    centre = boite.center()

    carre = QImage(cote, cote, QImage.Format.Format_ARGB32)
    carre.fill(Qt.GlobalColor.transparent)
    peintre = QPainter(carre)
    peintre.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Fond arrondi, comme les autres applications : un dessin flottant
    # sans support ne ressemble pas à une icône macOS.
    _fond_arrondi(peintre, cote)

    peintre.drawImage(
        -(centre.x() - cote // 2), -(centre.y() - cote // 2), dessin
    )
    peintre.end()

    for taille in TAILLES:
        carre.scaled(
            taille,
            taille,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ).save(str(RESSOURCES / f"icon-{taille}.png"))
    print("PNG :", ", ".join(str(t) for t in TAILLES))


def _sans_fond_blanc(image):
    """Rend transparent le fond blanc du logo.

    Le seuil est volontairement haut : le dessin contient des zones très
    claires (le ventre de la tortue, l'écran) qu'il ne faut pas percer.
    Seul le blanc quasi pur disparaît, et uniquement s'il touche un bord
    — un remplissage depuis les bords, pour ne pas trouer l'intérieur.
    """
    from PySide6.QtGui import qRgba

    copie = image.convertToFormat(image.Format.Format_ARGB32)
    largeur, hauteur = copie.width(), copie.height()

    def est_blanc(x, y):
        couleur = copie.pixelColor(x, y)
        return (
            couleur.alpha() > 0
            and couleur.red() >= 247
            and couleur.green() >= 247
            and couleur.blue() >= 247
        )

    # Parcours en largeur depuis les bords : le fond est connexe, les
    # zones claires internes ne le sont pas.
    vus = bytearray(largeur * hauteur)
    file = []
    for x in range(largeur):
        for y in (0, hauteur - 1):
            if est_blanc(x, y):
                file.append((x, y))
    for y in range(hauteur):
        for x in (0, largeur - 1):
            if est_blanc(x, y):
                file.append((x, y))

    while file:
        x, y = file.pop()
        index = y * largeur + x
        if vus[index]:
            continue
        vus[index] = 1
        copie.setPixel(x, y, qRgba(0, 0, 0, 0))
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < largeur and 0 <= ny < hauteur:
                if not vus[ny * largeur + nx] and est_blanc(nx, ny):
                    file.append((nx, ny))

    return copie


def _fond_arrondi(peintre, cote: int) -> None:
    """Le carré arrondi que macOS attend, dans les verts du graphe."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainterPath

    marge = cote * 0.10
    rayon = cote * 0.225   # proportion du « squircle » macOS

    degrade = QLinearGradient(0, marge, 0, cote - marge)
    degrade.setColorAt(0.0, QColor(247, 250, 247))
    degrade.setColorAt(1.0, QColor(223, 235, 224))

    chemin = QPainterPath()
    chemin.addRoundedRect(
        QRectF(marge, marge, cote - 2 * marge, cote - 2 * marge),
        rayon, rayon,
    )
    peintre.fillPath(chemin, QBrush(degrade))


def generer_icns() -> None:
    """Format macOS, via l'outil système `iconutil`."""
    if sys.platform != "darwin":
        print("icns : ignoré (macOS uniquement)")
        return

    with tempfile.TemporaryDirectory() as dossier:
        iconset = Path(dossier) / "tortoisepy.iconset"
        iconset.mkdir()

        for taille in (16, 32, 128, 256, 512):
            (iconset / f"icon_{taille}x{taille}.png").write_bytes(
                (RESSOURCES / f"icon-{taille}.png").read_bytes()
            )
        # Variantes Retina : le double de la taille nominale.
        for nominale, reelle in ((16, 32), (32, 64), (128, 256), (256, 512)):
            (iconset / f"icon_{nominale}x{nominale}@2x.png").write_bytes(
                (RESSOURCES / f"icon-{reelle}.png").read_bytes()
            )

        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset),
             "-o", str(RESSOURCES / "tortoisepy.icns")],
            check=True,
        )
    print("icns : écrit")


def generer_ico() -> None:
    """Format Windows, assemblé à la main.

    Qt n'écrit qu'une taille par fichier `.ico` ; or Windows en attend
    plusieurs et choisit selon le contexte. Le format est simple :
    en-tête, répertoire, puis les PNG bruts.
    """
    images = [
        (taille, (RESSOURCES / f"icon-{taille}.png").read_bytes())
        for taille in TAILLES_ICO
    ]

    entetes = b""
    donnees = b""
    decalage = 6 + 16 * len(images)
    for taille, png in images:
        # 0 signifie 256 dans le format ICO : un octet ne va pas plus loin.
        dimension = 0 if taille >= 256 else taille
        entetes += struct.pack(
            "<BBBBHHII", dimension, dimension, 0, 0, 1, 32, len(png), decalage
        )
        donnees += png
        decalage += len(png)

    (RESSOURCES / "tortoisepy.ico").write_bytes(
        struct.pack("<HHH", 0, 1, len(images)) + entetes + donnees
    )
    print("ico :", ", ".join(str(t) for t, _ in images))


if __name__ == "__main__":
    generer_png()
    generer_icns()
    generer_ico()
