"""Pont entre le schéma de `core/settings.py` et `QSettings`.

`QSettings` écrit hors du dépôt — `~/Library/Preferences/` sur macOS, le
registre sous Windows. Ces emplacements sont disjoints du dossier
d'installation (`~/.local/share/uv/tools/`), ce qui est la raison pour
laquelle une mise à jour ne perd pas les réglages (§2.2). Un test le
vérifie plutôt que de s'y fier.
"""

from __future__ import annotations

from PySide6.QtCore import QSettings

from tortoisepy.core.settings import (
    DEFAULTS,
    SCHEMA_VERSION,
    coerce,
    is_supported_version,
)
from tortoisepy.core.shortcuts import CATALOGUE, resolve

ORGANISATION = "tortoisePy"
APPLICATION = "tortoisePy"

_PREFIXE_RACCOURCI = "shortcuts/"
_CLE_VERSION = "settings/version"


class SettingsStore:
    """Lecture et écriture des réglages.

    L'injection de `QSettings` sert aux tests : ils travaillent sur un
    fichier `.ini` temporaire, jamais sur les vraies préférences de
    l'utilisateur.
    """

    def __init__(self, settings: QSettings | None = None):
        self._settings = settings or QSettings(ORGANISATION, APPLICATION)
        # Des préférences écrites par une version plus récente sont
        # ignorées en bloc : mieux vaut repartir des défauts que lire un
        # format qu'on ne comprend pas (§D48).
        stockee = self._settings.value(_CLE_VERSION)
        self._lisible = stockee is None or is_supported_version(stockee)

    def value(self, key: str) -> object:
        if not self._lisible:
            return DEFAULTS.get(key)
        if not self._settings.contains(key):
            return DEFAULTS.get(key)
        return coerce(key, self._settings.value(key))

    def set_value(self, key: str, value: object) -> None:
        self._settings.setValue(_CLE_VERSION, SCHEMA_VERSION)
        self._settings.setValue(key, value)
        self._settings.sync()

    def shortcut_overrides(self) -> dict[str, str]:
        """Uniquement les raccourcis MODIFIÉS (§D49).

        Stocker les dix figerait les défauts dans le fichier de
        l'utilisateur : en changer un plus tard n'aurait alors aucun effet
        chez lui.
        """
        if not self._lisible:
            return {}
        surcharges: dict[str, str] = {}
        for spec in CATALOGUE:
            cle = _PREFIXE_RACCOURCI + spec.action_id
            if self._settings.contains(cle):
                valeur = self._settings.value(cle)
                if valeur:
                    surcharges[spec.action_id] = str(valeur)
        return surcharges

    def set_shortcut(self, action_id: str, sequence: str | None) -> None:
        """`None` efface la surcharge et fait revenir au défaut."""
        self._settings.setValue(_CLE_VERSION, SCHEMA_VERSION)
        cle = _PREFIXE_RACCOURCI + action_id
        if sequence is None:
            self._settings.remove(cle)
        else:
            self._settings.setValue(cle, sequence)
        self._settings.sync()

    def resolved_shortcuts(self) -> dict[str, str]:
        return resolve(self.shortcut_overrides())

    def reset_shortcuts(self) -> None:
        for spec in CATALOGUE:
            self._settings.remove(_PREFIXE_RACCOURCI + spec.action_id)
        self._settings.sync()
