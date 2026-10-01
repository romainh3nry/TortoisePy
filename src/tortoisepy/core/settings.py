"""Schéma des réglages persistés.

Aucun Qt ici : `tests/test_architecture.py` l'interdit à `core/`, et cela
rend la coercition testable sans fenêtre. Le pont `QSettings` vit dans
`ui/settings_store.py`.

`QSettings` rend le plus souvent des chaînes, quel que soit le type écrit
(vérifié sur macOS). Toute valeur relue passe donc par `coerce`.
"""

from __future__ import annotations

SCHEMA_VERSION = 1

DEFAULTS: dict[str, object] = {
    "view/zoom": 1.0,
    "view/panel_width": 0,          # 0 = laisser le splitter décider
    "view/show_tags": True,
    "recent/repositories": (),
}

_VRAI = {"true", "1", "yes", "on"}
_FAUX = {"false", "0", "no", "off"}


def is_supported_version(raw: object) -> bool:
    """Le schéma relu est-il celui que ce code sait lire ?

    Une version plus récente (préférences écrites par une version future
    de l'app) fait repartir des défauts : mieux vaut perdre des réglages
    que lire un format qu'on ne comprend pas.
    """
    try:
        return int(raw) == SCHEMA_VERSION  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False


def _vers_booleen(raw: object, defaut: object) -> object:
    if isinstance(raw, bool):
        return raw
    texte = str(raw).strip().lower()
    if texte in _VRAI:
        return True
    if texte in _FAUX:
        return False
    return defaut


def _vers_zoom(raw: object, defaut: object) -> object:
    try:
        valeur = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return defaut
    # Un zoom nul ou négatif rendrait le graphe invisible, et aucune
    # commande de l'UI ne permettrait d'en sortir.
    return valeur if valeur > 0 else defaut


def _vers_entier(raw: object, defaut: object) -> object:
    try:
        return int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return defaut


def _vers_liste(raw: object, defaut: object) -> object:
    if isinstance(raw, (list, tuple)):
        return tuple(str(element) for element in raw)
    if isinstance(raw, str) and raw:
        return (raw,)
    return defaut


_COERCITIONS = {
    "view/zoom": _vers_zoom,
    "view/panel_width": _vers_entier,
    "view/show_tags": _vers_booleen,
    "recent/repositories": _vers_liste,
}


def coerce(key: str, raw: object) -> object:
    """Valeur typée pour `key`, ou son défaut si `raw` est inexploitable.

    Ne lève jamais : une préférence abîmée doit dégrader l'expérience,
    pas empêcher l'application de démarrer.
    """
    if key not in DEFAULTS:
        return raw
    return _COERCITIONS[key](raw, DEFAULTS[key])
