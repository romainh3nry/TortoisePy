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
    # Demandé par l'utilisateur : masquer la liste latérale. Faux par
    # défaut — le panneau révèle ce que la compression masque (§4.2.1).
    "view/panel_hidden": False,
    # Demandé par l'utilisateur : le dossier de projets choisi une
    # fois, qui doit rester d'un lancement à l'autre.
    "view/workdir": "",
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


def _vers_chemin(raw: object, defaut: object) -> object:
    """Un chemin lu des préférences, ou le défaut s'il est inexploitable.

    `QSettings` peut rendre autre chose qu'une chaîne (une liste, si le
    chemin contenait une virgule et a été écrit par une version
    antérieure). On ne vérifie PAS que le dossier existe : il peut être
    sur un disque externe débranché, et l'oublier silencieusement
    perdrait le réglage de l'utilisateur. C'est à l'affichage de dire
    qu'il est introuvable.
    """
    if isinstance(raw, str):
        return raw
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
    "view/panel_hidden": _vers_booleen,
    "view/workdir": _vers_chemin,
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
