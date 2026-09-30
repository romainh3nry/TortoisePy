# Réglages persistés et raccourcis modifiables — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mémoriser les réglages d'affichage entre deux lancements, afficher les raccourcis clavier et les rendre modifiables, sans qu'une mise à jour ne les perde.

**Architecture :** Une couche `core/` pure (schéma, défauts, validation, catalogue des raccourcis) qui n'importe jamais Qt, et une couche `ui/` qui la branche sur `QSettings` et sur une fenêtre dédiée. Les raccourcis sont stockés en texte portable (`Ctrl+F`) et affichés en texte natif (`⌘F`), ce qui rend le fichier de préférences valide sur les deux plateformes.

**Tech Stack :** Python 3.13, PySide6 6.11.2 (`QSettings`, `QKeySequence`), pytest + pytest-qt.

**Spec :** `docs/superpowers/specs/2026-09-30-tortoisepy-settings-design.md`

## Global Constraints

- **`core/` et `layout/` n'importent JAMAIS Qt** (`PySide6`, `PyQt6`, `PyQt5`) — imposé par `tests/test_architecture.py`. La validation des raccourcis travaille sur des `str`, pas sur `QKeySequence`.
- **Seule `ui/` importe Qt.** `ui/` ne fait pas d'opération pygit2 directe.
- **Stockage en PortableText** (`"Ctrl+F"`), affichage en NativeText (`"⌘F"`). Jamais l'inverse.
- **Le rendu du graphe ne doit pas se dégrader** : ni couleurs, ni courbes, ni flèches, ni mise en page. Les tests de `tests/ui/test_graph_items.py` et `tests/ui/test_theme.py` doivent rester verts **sans modification**.
- **Garantie de lecture seule** : aucune écriture supplémentaire dans `.git`. Les préférences vivent hors du dépôt.
- **Libellés de menus en anglais** ; commentaires et docstrings en français.
- **Version de schéma `1`** dans toute préférence écrite.
- **Ne jamais lancer de commande git sur le dépôt du projet.** Le `git` des fixtures `tmp_path` est autorisé et attendu.

## Review Focus

- **Préférences corrompues ou d'un type inattendu** (un `str` là où un `float` est attendu, un plist édité à la main) — l'application démarre sur les défauts au lieu de lever. Couvert Task 1.
- **Géométrie mémorisée devenue invisible** (moniteur débranché, résolution réduite) — la fenêtre s'ouvre sur les défauts plutôt que hors écran. Couvert Task 6.
- **Raccourci destructeur réassigné puis frappé par réflexe** (`Ctrl+D` sur Drop stash) — la confirmation s'affiche quand même, et un refus ne détruit rien. Couvert Task 5.
- **Bascule du filtre de tags sans changement de refs** — le graphe est reconstruit malgré le cache, qui ne connaît que l'empreinte du dépôt. Couvert Task 7.
- **Dépôt récent supprimé ou déplacé depuis** — l'entrée est purgée au lieu de faire échouer l'ouverture. Couvert Task 8.

---

## File Structure

| Fichier | Responsabilité |
|---|---|
| `src/tortoisepy/core/settings.py` | Schéma, défauts, coercition de type, version. Aucun Qt. |
| `src/tortoisepy/core/shortcuts.py` | Catalogue des actions, détection de conflits, séquences réservées. Aucun Qt. |
| `src/tortoisepy/ui/settings_store.py` | Pont `QSettings` : lit/écrit ce que `core/settings.py` décrit. |
| `src/tortoisepy/ui/shortcuts_window.py` | Fenêtre « Keyboard Shortcuts » : liste et édition. |
| `src/tortoisepy/ui/main_window.py` | Lit le catalogue, restaure et sauve les réglages. |
| `src/tortoisepy/ui/graph_view.py` | Expose `set_zoom` pour la restauration. |

---

### Task 1 : Le schéma des réglages

**Files:**
- Create: `src/tortoisepy/core/settings.py`
- Test: `tests/core/test_settings.py`

**Interfaces:**
- Consumes: rien.
- Produces:
  - `SCHEMA_VERSION: int = 1`
  - `DEFAULTS: dict[str, object]` — clés `"view/zoom"` (`1.0`), `"view/panel_width"` (`0`), `"view/show_tags"` (`True`), `"recent/repositories"` (`()`)
  - `coerce(key: str, raw: object) -> object` — rend la valeur typée, ou le défaut si `raw` est inexploitable
  - `is_supported_version(raw: object) -> bool`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_settings.py
import pytest

from tortoisepy.core.settings import (
    DEFAULTS,
    SCHEMA_VERSION,
    coerce,
    is_supported_version,
)


def test_defaults_cover_every_persisted_key():
    """Une clé sans défaut planterait au premier démarrage."""
    assert set(DEFAULTS) == {
        "view/zoom",
        "view/panel_width",
        "view/show_tags",
        "recent/repositories",
    }


def test_a_readable_value_is_typed():
    """QSettings rend des chaînes : « 1.5 » doit devenir un float."""
    assert coerce("view/zoom", "1.5") == 1.5
    assert coerce("view/show_tags", "false") is False
    assert coerce("view/show_tags", "true") is True


def test_a_corrupt_value_falls_back_to_the_default():
    """Un plist édité à la main ne doit pas empêcher l'app de démarrer.

    C'est le test qui compte : sans lui, une valeur illisible lèverait au
    lancement, et l'utilisateur n'aurait aucun moyen de s'en sortir sans
    supprimer ses préférences à la main.
    """
    assert coerce("view/zoom", "pas-un-nombre") == DEFAULTS["view/zoom"]
    assert coerce("view/zoom", None) == DEFAULTS["view/zoom"]
    assert coerce("view/panel_width", []) == DEFAULTS["view/panel_width"]


def test_an_absurd_zoom_is_refused():
    """Un zoom nul ou négatif rendrait le graphe invisible."""
    assert coerce("view/zoom", "0") == DEFAULTS["view/zoom"]
    assert coerce("view/zoom", "-2") == DEFAULTS["view/zoom"]


def test_an_unknown_key_is_returned_unchanged():
    assert coerce("inconnue", "valeur") == "valeur"


def test_only_the_current_schema_is_supported():
    """Une version future fait repartir des défauts plutôt que planter."""
    assert is_supported_version(SCHEMA_VERSION)
    assert is_supported_version(str(SCHEMA_VERSION))
    assert not is_supported_version(SCHEMA_VERSION + 1)
    assert not is_supported_version(None)
    assert not is_supported_version("abîmé")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/core/test_settings.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tortoisepy.core.settings'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/tortoisepy/core/settings.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/core/test_settings.py tests/test_architecture.py -v`
Expected: PASS — y compris `test_core_never_imports_qt_or_ui`

- [ ] **Step 5: Commit**

```bash
git add src/tortoisepy/core/settings.py tests/core/test_settings.py
git commit -m "feat(settings): schéma et coercition des réglages persistés"
```

---

### Task 2 : Le catalogue des raccourcis

**Files:**
- Create: `src/tortoisepy/core/shortcuts.py`
- Test: `tests/core/test_shortcuts.py`

**Interfaces:**
- Consumes: rien.
- Produces:
  - `@dataclass(frozen=True) ShortcutSpec` — champs `action_id: str`, `label: str`, `default: str`, `destructive: bool = False`
  - `CATALOGUE: tuple[ShortcutSpec, ...]` — les dix actions actuelles
  - `RESERVED: frozenset[str]`
  - `spec_for(action_id: str) -> ShortcutSpec | None`
  - `validate(action_id: str, sequence: str, assignments: dict[str, str]) -> str | None` — rend `None` si valide, sinon le motif du refus
  - `resolve(overrides: dict[str, str]) -> dict[str, str]` — défauts surchargés par les modifications

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_shortcuts.py
from tortoisepy.core.shortcuts import (
    CATALOGUE,
    RESERVED,
    resolve,
    spec_for,
    validate,
)


def test_the_catalogue_covers_the_current_shortcuts():
    """Les dix actions de `main_window._build_actions` (§6.1)."""
    ids = {spec.action_id for spec in CATALOGUE}
    assert ids == {
        "zoom_in", "zoom_out", "zoom_reset", "fit_to_window",
        "refresh", "commit", "search", "push", "pull", "fetch",
    }


def test_action_ids_are_stable_and_distinct_from_labels():
    """Renommer un libellé ne doit pas perdre le choix de l'utilisateur."""
    for spec in CATALOGUE:
        assert spec.action_id.islower()
        assert " " not in spec.action_id
        assert spec.action_id != spec.label


def test_defaults_are_stored_portable_not_native():
    """§D47 : « Ctrl+F », jamais « ⌘F ».

    Un fichier de préférences contenant du texte natif serait illisible
    en changeant de plateforme.
    """
    for spec in CATALOGUE:
        assert "⌘" not in spec.default
        assert "⇧" not in spec.default


def test_a_free_sequence_is_accepted():
    assert validate("commit", "Ctrl+J", {}) is None


def test_a_conflict_names_the_other_action():
    """Le message doit dire à QUI la touche est prise (§6.3)."""
    motif = validate("commit", "Ctrl+F", {"search": "Ctrl+F"})
    assert motif is not None
    assert "search" in motif


def test_reassigning_an_action_to_its_own_sequence_is_allowed():
    """Rouvrir l'éditeur sans rien changer ne doit pas crier au conflit."""
    assert validate("search", "Ctrl+F", {"search": "Ctrl+F"}) is None


def test_a_reserved_sequence_is_refused():
    """Réassigner ⌘Q rendrait l'application impossible à quitter."""
    for sequence in ("Ctrl+Q", "Ctrl+W"):
        assert sequence in RESERVED
        assert validate("commit", sequence, {}) is not None


def test_an_empty_sequence_is_refused():
    assert validate("commit", "", {}) is not None
    assert validate("commit", "   ", {}) is not None


def test_resolve_applies_overrides_over_defaults():
    resolus = resolve({"commit": "Ctrl+J"})
    assert resolus["commit"] == "Ctrl+J"
    assert resolus["search"] == spec_for("search").default


def test_resolve_ignores_an_unknown_action():
    """Une préférence d'une version future ne doit pas planter."""
    assert "inconnue" not in resolve({"inconnue": "Ctrl+Z"})


def test_destructive_actions_are_flagged():
    """Le drapeau sert à PRÉVENIR l'utilisateur, pas à protéger.

    La protection réelle est `dialogs.confirmation_for` (§6.4). Ce
    drapeau ne pilote que l'affichage.
    """
    assert any(spec.destructive for spec in CATALOGUE) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/core/test_shortcuts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tortoisepy.core.shortcuts'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/tortoisepy/core/shortcuts.py
"""Catalogue des raccourcis et règles de validation.

Aucun Qt : `test_architecture.py` l'interdit à `core/`. Les séquences sont
donc des chaînes au format portable de Qt (« Ctrl+F »), que `ui/` convertit
en `QKeySequence` pour l'affichage natif (« ⌘F »).

Les dix entrées reprennent `main_window._build_actions`, où elles étaient
codées en dur dans un littéral. `zoom_in`, `zoom_out` et `refresh`
utilisaient des `StandardKey` : leurs équivalents portables sont repris
tels quels pour ne pas changer le comportement existant.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ShortcutSpec:
    """Une action raccourcissable.

    `action_id` est stable et distinct de `label` : renommer un libellé ne
    doit pas faire perdre à l'utilisateur le raccourci qu'il a choisi.
    """

    action_id: str
    label: str
    default: str
    destructive: bool = False
    """Purement indicatif, pour l'affichage.

    **Ce drapeau ne protège rien** — la leçon de la phase 11, où
    `MenuEntry.needs_confirmation` était posé, testé, et pourtant sans
    effet : « Drop stash » détruisait le stash même sur un refus. La
    protection réelle passe par `dialogs.confirmation_for` (§6.4).
    """


CATALOGUE: tuple[ShortcutSpec, ...] = (
    ShortcutSpec("zoom_in", "Zoom in", "Ctrl++"),
    ShortcutSpec("zoom_out", "Zoom out", "Ctrl+-"),
    ShortcutSpec("zoom_reset", "Zoom 100%", "Ctrl+0"),
    ShortcutSpec("fit_to_window", "Fit to window", "Ctrl+9"),
    # F5 même sur macOS, où ce n'est pas une convention : c'est le défaut
    # actuel (QKeySequence.StandardKey.Refresh), conservé pour ne pas
    # changer le comportement sous l'utilisateur. Il devient modifiable,
    # ce qui règle le problème pour qui le souhaite (§6.1).
    ShortcutSpec("refresh", "Refresh", "F5"),
    ShortcutSpec("commit", "Commit…", "Ctrl+K"),
    ShortcutSpec("search", "Search", "Ctrl+F"),
    ShortcutSpec("push", "Push", "Ctrl+P"),
    ShortcutSpec("pull", "Pull", "Ctrl+L"),
    ShortcutSpec("fetch", "Fetch", "Ctrl+Shift+F"),
)

RESERVED: frozenset[str] = frozenset({
    "Ctrl+Q",    # quitter — l'app deviendrait impossible à fermer
    "Ctrl+W",    # fermer la fenêtre
    "Ctrl+Tab",  # navigation système
    "Alt+F4",    # fermer sous Windows
})

_PAR_ID = {spec.action_id: spec for spec in CATALOGUE}


def spec_for(action_id: str) -> ShortcutSpec | None:
    return _PAR_ID.get(action_id)


def resolve(overrides: dict[str, str]) -> dict[str, str]:
    """Défauts du catalogue, surchargés par les choix de l'utilisateur.

    Une clé inconnue est ignorée : des préférences écrites par une version
    plus récente ne doivent pas empêcher celle-ci de démarrer.
    """
    resolus = {spec.action_id: spec.default for spec in CATALOGUE}
    for action_id, sequence in overrides.items():
        if action_id in resolus and sequence:
            resolus[action_id] = sequence
    return resolus


def validate(
    action_id: str, sequence: str, assignments: dict[str, str]
) -> str | None:
    """Motif du refus, ou `None` si la séquence est acceptable.

    `assignments` associe chaque action à sa séquence courante. Réassigner
    une action à la séquence qu'elle porte déjà n'est pas un conflit :
    sans cette exception, rouvrir l'éditeur sans rien changer serait refusé.
    """
    nettoyee = sequence.strip()
    if not nettoyee:
        return "Une séquence vide n'est pas un raccourci."

    if nettoyee in RESERVED:
        return f"« {nettoyee} » est réservé par le système."

    for autre_id, autre_sequence in assignments.items():
        if autre_sequence == nettoyee and autre_id != action_id:
            return f"« {nettoyee} » est déjà utilisé par « {autre_id} »."

    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/core/test_shortcuts.py tests/test_architecture.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/tortoisepy/core/shortcuts.py tests/core/test_shortcuts.py
git commit -m "feat(shortcuts): catalogue des actions et validation"
```

---

### Task 3 : Le pont QSettings

**Files:**
- Create: `src/tortoisepy/ui/settings_store.py`
- Test: `tests/ui/test_settings_store.py`

**Interfaces:**
- Consumes: `core.settings.{DEFAULTS, SCHEMA_VERSION, coerce, is_supported_version}`, `core.shortcuts.{CATALOGUE, resolve}`
- Produces:
  - `class SettingsStore` avec `__init__(self, settings: QSettings | None = None)`
  - `value(key: str) -> object`
  - `set_value(key: str, value: object) -> None`
  - `shortcut_overrides() -> dict[str, str]`
  - `set_shortcut(action_id: str, sequence: str | None) -> None` — `None` efface la surcharge
  - `resolved_shortcuts() -> dict[str, str]`
  - `reset_shortcuts() -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/ui/test_settings_store.py
import pytest
from PySide6.QtCore import QSettings

from tortoisepy.core.settings import DEFAULTS, SCHEMA_VERSION
from tortoisepy.core.shortcuts import spec_for
from tortoisepy.ui.settings_store import SettingsStore


@pytest.fixture
def store(tmp_path):
    """Un magasin isolé : un fichier .ini du test, jamais les vraies
    préférences de l'utilisateur."""
    chemin = str(tmp_path / "prefs.ini")
    return SettingsStore(QSettings(chemin, QSettings.Format.IniFormat))


def test_a_round_trip_preserves_each_value(store):
    store.set_value("view/zoom", 1.75)
    store.set_value("view/show_tags", False)
    assert store.value("view/zoom") == 1.75
    assert store.value("view/show_tags") is False


def test_an_unset_key_gives_its_default(store):
    assert store.value("view/zoom") == DEFAULTS["view/zoom"]
    assert store.value("view/show_tags") == DEFAULTS["view/show_tags"]


def test_a_corrupt_stored_value_gives_the_default(store, tmp_path):
    """Écrit à la main dans le fichier, comme le ferait un éditeur."""
    store._settings.setValue("view/zoom", "abîmé")
    assert store.value("view/zoom") == DEFAULTS["view/zoom"]


def test_an_unknown_schema_version_falls_back_to_defaults(tmp_path):
    """§D48 : des préférences d'une version future ne cassent rien."""
    chemin = str(tmp_path / "futur.ini")
    brut = QSettings(chemin, QSettings.Format.IniFormat)
    brut.setValue("settings/version", SCHEMA_VERSION + 99)
    brut.setValue("view/zoom", 3.0)
    brut.sync()

    store = SettingsStore(QSettings(chemin, QSettings.Format.IniFormat))
    assert store.value("view/zoom") == DEFAULTS["view/zoom"]


def test_writing_stamps_the_schema_version(store):
    store.set_value("view/zoom", 1.25)
    assert int(store._settings.value("settings/version")) == SCHEMA_VERSION


def test_only_modified_shortcuts_are_stored(store):
    """§D49 : ne pas figer les défauts dans le fichier de l'utilisateur."""
    assert store.shortcut_overrides() == {}

    store.set_shortcut("commit", "Ctrl+J")
    assert store.shortcut_overrides() == {"commit": "Ctrl+J"}

    store.set_shortcut("commit", None)
    assert store.shortcut_overrides() == {}


def test_a_shortcut_is_stored_portable_not_native(store):
    """Le test qui protège le multiplateforme (§D47).

    Stocker « ⌘F » produirait un fichier illisible sur Windows.
    """
    store.set_shortcut("search", "Ctrl+F")
    brut = store._settings.value("shortcuts/search")
    assert brut == "Ctrl+F"
    assert "⌘" not in str(brut)


def test_resolved_shortcuts_merge_defaults_and_overrides(store):
    store.set_shortcut("commit", "Ctrl+J")
    resolus = store.resolved_shortcuts()
    assert resolus["commit"] == "Ctrl+J"
    assert resolus["search"] == spec_for("search").default


def test_reset_clears_every_override(store):
    store.set_shortcut("commit", "Ctrl+J")
    store.set_shortcut("push", "Ctrl+Y")
    store.reset_shortcuts()
    assert store.shortcut_overrides() == {}
    assert store.resolved_shortcuts()["commit"] == spec_for("commit").default
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_settings_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tortoisepy.ui.settings_store'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/tortoisepy/ui/settings_store.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_settings_store.py -v`
Expected: PASS — 10 tests

- [ ] **Step 5: Commit**

```bash
git add src/tortoisepy/ui/settings_store.py tests/ui/test_settings_store.py
git commit -m "feat(settings): pont QSettings avec version de schéma"
```

---

### Task 4 : Les raccourcis viennent du catalogue

**Files:**
- Modify: `src/tortoisepy/ui/main_window.py:403-430` (`_build_actions`)
- Modify: `src/tortoisepy/ui/graph_view.py` (ajouter `set_zoom`)
- Test: `tests/ui/test_main_window_shortcuts.py`

**Interfaces:**
- Consumes: `core.shortcuts.CATALOGUE`, `ui.settings_store.SettingsStore`
- Produces:
  - `MainWindow.settings: SettingsStore`
  - `MainWindow.actions_by_id: dict[str, QAction]`
  - `MainWindow.apply_shortcuts(resolved: dict[str, str]) -> None`
  - `GraphView.set_zoom(value: float) -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/ui/test_main_window_shortcuts.py
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QKeySequence

from tortoisepy.core.shortcuts import CATALOGUE, spec_for
from tortoisepy.ui.main_window import MainWindow
from tortoisepy.ui.settings_store import SettingsStore


@pytest.fixture
def window(qtbot, repo_linear, tmp_path):
    store = SettingsStore(
        QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    )
    w = MainWindow(repo_linear, settings=store)
    qtbot.addWidget(w)
    return w


def test_every_catalogue_action_exists(window):
    """Le littéral codé en dur est remplacé par le catalogue (§6.1)."""
    for spec in CATALOGUE:
        assert spec.action_id in window.actions_by_id


def test_defaults_are_applied_when_nothing_is_stored(window):
    action = window.actions_by_id["commit"]
    attendu = QKeySequence(spec_for("commit").default)
    assert action.shortcut() == attendu


def test_a_stored_override_wins_over_the_default(qtbot, repo_linear, tmp_path):
    chemin = str(tmp_path / "prefs.ini")
    store = SettingsStore(QSettings(chemin, QSettings.Format.IniFormat))
    store.set_shortcut("commit", "Ctrl+J")

    w = MainWindow(repo_linear, settings=store)
    qtbot.addWidget(w)
    assert w.actions_by_id["commit"].shortcut() == QKeySequence("Ctrl+J")


def test_applying_shortcuts_updates_live(window):
    """Modifier un raccourci ne doit pas exiger de relancer l'app."""
    window.apply_shortcuts({**window.settings.resolved_shortcuts(),
                            "search": "Ctrl+E"})
    assert window.actions_by_id["search"].shortcut() == QKeySequence("Ctrl+E")


def test_shortcuts_are_displayed_natively(window):
    """§6.2 : ⌘F à l'écran, « Ctrl+F » dans le fichier.

    Le test compare au rendu natif de Qt sur la plateforme courante, ce
    qui le rend valide aussi bien sur macOS que sur Windows.
    """
    action = window.actions_by_id["search"]
    natif = action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
    portable = action.shortcut().toString(
        QKeySequence.SequenceFormat.PortableText
    )
    assert portable == spec_for("search").default
    assert natif == QKeySequence(
        spec_for("search").default
    ).toString(QKeySequence.SequenceFormat.NativeText)


def test_set_zoom_is_exposed(window):
    """La restauration du zoom en a besoin (Task 6)."""
    window.view.set_zoom(1.5)
    assert window.view.current_zoom() == pytest.approx(1.5)


def test_set_zoom_refuses_an_absurd_value(window):
    """Un zoom nul rendrait le graphe invisible sans recours."""
    avant = window.view.current_zoom()
    window.view.set_zoom(0.0)
    assert window.view.current_zoom() == pytest.approx(avant)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_main_window_shortcuts.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'settings'`

- [ ] **Step 3: Write minimal implementation**

Dans `src/tortoisepy/ui/graph_view.py`, ajouter après `current_zoom` :

```python
    def set_zoom(self, value: float) -> None:
        """Applique un zoom restauré depuis les préférences.

        Une valeur nulle ou négative est ignorée : elle rendrait le graphe
        invisible, et aucune commande de l'UI ne permettrait d'en sortir.
        """
        if value <= 0:
            return
        self._set_zoom(value)
```

Dans `src/tortoisepy/ui/main_window.py`, remplacer la signature :

```python
    def __init__(self, repository: pygit2.Repository, parent=None,
                 settings: SettingsStore | None = None):
        super().__init__(parent)
        self.repository = repository
        self.settings = settings or SettingsStore()
```

et remplacer entièrement `_build_actions` :

```python
    def _build_actions(self) -> None:
        """Actions de navigation (§7.1), raccourcis lus du catalogue.

        Les séquences vivaient ici dans un littéral ; elles sont désormais
        dans `core/shortcuts.py`, ce qui permet de les surcharger depuis
        les préférences. Qt traduit « Ctrl » en ⌘ sur macOS.
        """
        slots = {
            "zoom_in": self.view.zoom_in,
            "zoom_out": self.view.zoom_out,
            "zoom_reset": self.view.reset_zoom,
            "fit_to_window": self.view.fit_to_window,
            "refresh": self.refresh,
            "commit": self.open_commit_window,
            "search": self.focus_search,
            "push": self._start_push,
            "pull": self._start_pull,
            "fetch": self._start_fetch,
        }

        self.actions_by_id: dict[str, QAction] = {}
        for spec in CATALOGUE:
            action = QAction(spec.label, self)
            action.triggered.connect(slots[spec.action_id])
            self.addAction(action)
            self.toolbar.addAction(action)
            self.actions_by_id[spec.action_id] = action

        # Ces trois-là sont manipulées ailleurs (activation/désactivation
        # pendant une opération réseau) : on garde les attributs nommés.
        self.push_action = self.actions_by_id["push"]
        self.pull_action = self.actions_by_id["pull"]
        self.fetch_action = self.actions_by_id["fetch"]

        self.apply_shortcuts(self.settings.resolved_shortcuts())

    def apply_shortcuts(self, resolved: dict[str, str]) -> None:
        """Applique les séquences aux actions, sans relancer l'app."""
        for action_id, sequence in resolved.items():
            action = self.actions_by_id.get(action_id)
            if action is not None:
                action.setShortcut(QKeySequence(sequence))
```

Ajouter les imports en tête de `main_window.py` :

```python
from tortoisepy.core.shortcuts import CATALOGUE
from tortoisepy.ui.settings_store import SettingsStore
```

- [ ] **Step 4: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_main_window_shortcuts.py tests/ui/test_main_window.py -v`
Expected: PASS — les tests existants de `main_window` restent verts, `settings` étant optionnel

- [ ] **Step 5: Commit**

```bash
git add src/tortoisepy/ui/main_window.py src/tortoisepy/ui/graph_view.py tests/ui/test_main_window_shortcuts.py
git commit -m "feat(shortcuts): les raccourcis viennent du catalogue"
```

---

### Task 5 : La fenêtre des raccourcis

**Files:**
- Create: `src/tortoisepy/ui/shortcuts_window.py`
- Modify: `src/tortoisepy/ui/main_window.py` (entrée de menu `Keyboard Shortcuts…`)
- Test: `tests/ui/test_shortcuts_window.py`

**Interfaces:**
- Consumes: `core.shortcuts.{CATALOGUE, validate, spec_for}`, `ui.settings_store.SettingsStore`
- Produces:
  - `class ShortcutsWindow(QDialog)` — `__init__(self, store: SettingsStore, parent=None)`
  - `rows() -> tuple[tuple[str, str, str], ...]` — `(action_id, label, texte natif)`
  - `try_assign(action_id: str, sequence: str) -> str | None`
  - `reset_all() -> None`
  - signal `shortcuts_changed = Signal(dict)`

- [ ] **Step 1: Write the failing test**

```python
# tests/ui/test_shortcuts_window.py
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QKeySequence

from tortoisepy.core.shortcuts import CATALOGUE, spec_for
from tortoisepy.ui.settings_store import SettingsStore
from tortoisepy.ui.shortcuts_window import ShortcutsWindow


@pytest.fixture
def window(qtbot, tmp_path):
    store = SettingsStore(
        QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    )
    w = ShortcutsWindow(store)
    qtbot.addWidget(w)
    return w


def test_every_action_is_listed(window):
    """§6.2 : la fenêtre rend les raccourcis découvrables."""
    ids = {ligne[0] for ligne in window.rows()}
    assert ids == {spec.action_id for spec in CATALOGUE}


def test_sequences_are_shown_natively(window):
    """⌘F à l'écran, « Ctrl+F » dans le fichier (§6.2)."""
    par_id = {ligne[0]: ligne[2] for ligne in window.rows()}
    attendu = QKeySequence(spec_for("search").default).toString(
        QKeySequence.SequenceFormat.NativeText
    )
    assert par_id["search"] == attendu


def test_assigning_a_free_sequence_succeeds(window):
    assert window.try_assign("commit", "Ctrl+J") is None
    assert window._store.resolved_shortcuts()["commit"] == "Ctrl+J"


def test_a_conflict_is_refused_and_nothing_is_written(window):
    """Le refus doit être total : ni écriture, ni état incohérent."""
    avant = window._store.resolved_shortcuts()["commit"]
    motif = window.try_assign("commit", spec_for("search").default)

    assert motif is not None
    assert "search" in motif
    assert window._store.resolved_shortcuts()["commit"] == avant


def test_a_reserved_sequence_is_refused(window):
    assert window.try_assign("commit", "Ctrl+Q") is not None
    assert window._store.shortcut_overrides() == {}


def test_reset_restores_every_default(window):
    window.try_assign("commit", "Ctrl+J")
    window.reset_all()
    assert window._store.shortcut_overrides() == {}
    par_id = {ligne[0]: ligne[2] for ligne in window.rows()}
    assert par_id["commit"] == QKeySequence(
        spec_for("commit").default
    ).toString(QKeySequence.SequenceFormat.NativeText)


def test_a_successful_assignment_emits_the_signal(qtbot, window):
    """La fenêtre principale doit pouvoir appliquer sans relancer."""
    with qtbot.waitSignal(window.shortcuts_changed, timeout=1000) as bloqueur:
        window.try_assign("commit", "Ctrl+J")
    assert bloqueur.args[0]["commit"] == "Ctrl+J"


def test_a_refused_assignment_emits_nothing(qtbot, window):
    with qtbot.assertNotEmitted(window.shortcuts_changed):
        window.try_assign("commit", "Ctrl+Q")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_shortcuts_window.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tortoisepy.ui.shortcuts_window'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/tortoisepy/ui/shortcuts_window.py
"""Fenêtre « Keyboard Shortcuts » : afficher et modifier.

L'affichage est natif (⌘F sur macOS, Ctrl+F sur Windows), le stockage
portable (§D47). La conversion se fait ici, à la frontière : `core/` ne
connaît que des chaînes portables.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from tortoisepy.core.shortcuts import CATALOGUE, spec_for, validate
from tortoisepy.ui.settings_store import SettingsStore


def _natif(sequence: str) -> str:
    """Texte portable -> texte natif, pour l'affichage seul."""
    return QKeySequence(sequence).toString(
        QKeySequence.SequenceFormat.NativeText
    )


class ShortcutsWindow(QDialog):
    """Liste les raccourcis et permet de les réassigner."""

    shortcuts_changed = Signal(dict)
    """Émis après une assignation ACCEPTÉE, avec les séquences résolues.

    La fenêtre principale s'y branche pour appliquer sans relancer l'app.
    Un refus n'émet rien : sans cela, un conflit repeindrait l'interface
    avec un état que le magasin n'a pas enregistré.
    """

    def __init__(self, store: SettingsStore, parent=None):
        super().__init__(parent)
        self._store = store
        self.setWindowTitle("Keyboard Shortcuts")

        disposition = QVBoxLayout(self)
        disposition.addWidget(
            QLabel("Double-click a shortcut to change it.")
        )

        self.table = QTableWidget(len(CATALOGUE), 2, self)
        self.table.setHorizontalHeaderLabels(["Action", "Shortcut"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        disposition.addWidget(self.table)

        boutons = QHBoxLayout()
        self.reset_button = QPushButton("Reset to defaults", self)
        self.reset_button.clicked.connect(self.reset_all)
        boutons.addWidget(self.reset_button)
        boutons.addStretch(1)
        self.close_button = QPushButton("Close", self)
        self.close_button.clicked.connect(self.accept)
        boutons.addWidget(self.close_button)
        disposition.addLayout(boutons)

        self._refresh()

    def rows(self) -> tuple[tuple[str, str, str], ...]:
        """(action_id, libellé, séquence en texte natif)."""
        resolus = self._store.resolved_shortcuts()
        return tuple(
            (spec.action_id, spec.label, _natif(resolus[spec.action_id]))
            for spec in CATALOGUE
        )

    def _refresh(self) -> None:
        for ligne, (_, label, natif) in enumerate(self.rows()):
            self.table.setItem(ligne, 0, QTableWidgetItem(label))
            element = QTableWidgetItem(natif)
            element.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(ligne, 1, element)

    def try_assign(self, action_id: str, sequence: str) -> str | None:
        """Motif du refus, ou `None` si la séquence a été enregistrée.

        Rien n'est écrit tant que la validation n'est pas passée : un
        refus doit laisser l'état exactement tel qu'il était.
        """
        motif = validate(
            action_id, sequence, self._store.resolved_shortcuts()
        )
        if motif is not None:
            return motif

        spec = spec_for(action_id)
        # Revenir au défaut efface la surcharge plutôt que de l'écrire
        # (§D49) : le défaut pourra ainsi évoluer plus tard.
        if spec is not None and sequence == spec.default:
            self._store.set_shortcut(action_id, None)
        else:
            self._store.set_shortcut(action_id, sequence)

        self._refresh()
        self.shortcuts_changed.emit(self._store.resolved_shortcuts())
        return None

    def reset_all(self) -> None:
        self._store.reset_shortcuts()
        self._refresh()
        self.shortcuts_changed.emit(self._store.resolved_shortcuts())
```

Dans `main_window.py`, ajouter la méthode d'ouverture :

```python
    def open_shortcuts_window(self) -> None:
        """Fenêtre « Keyboard Shortcuts » (§6.2)."""
        from tortoisepy.ui.shortcuts_window import ShortcutsWindow

        fenetre = ShortcutsWindow(self.settings, self)
        fenetre.shortcuts_changed.connect(self.apply_shortcuts)
        fenetre.exec()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_shortcuts_window.py -v`
Expected: PASS — 8 tests

- [ ] **Step 5: Commit**

```bash
git add src/tortoisepy/ui/shortcuts_window.py src/tortoisepy/ui/main_window.py tests/ui/test_shortcuts_window.py
git commit -m "feat(shortcuts): fenêtre d'affichage et d'édition"
```

---

### Task 6 : Restaurer géométrie, zoom et panneau

**Files:**
- Modify: `src/tortoisepy/ui/main_window.py` (`__init__`, `closeEvent`)
- Test: `tests/ui/test_settings_restore.py`

**Interfaces:**
- Consumes: `SettingsStore`, `GraphView.set_zoom`
- Produces:
  - `MainWindow.restore_settings() -> None`
  - `MainWindow.save_settings() -> None`
  - `MainWindow.geometry_is_visible(geometry: QRect) -> bool`

- [ ] **Step 1: Write the failing test**

```python
# tests/ui/test_settings_restore.py
import pytest
from PySide6.QtCore import QRect, QSettings

from tortoisepy.ui.main_window import MainWindow
from tortoisepy.ui.settings_store import SettingsStore


@pytest.fixture
def store(tmp_path):
    return SettingsStore(
        QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    )


def test_zoom_survives_a_close_and_reopen(qtbot, repo_linear, store):
    """Le réglage le plus visible d'un lancement à l'autre."""
    first = MainWindow(repo_linear, settings=store)
    qtbot.addWidget(first)
    first.view.set_zoom(1.6)
    first.save_settings()

    second = MainWindow(repo_linear, settings=store)
    qtbot.addWidget(second)
    assert second.view.current_zoom() == pytest.approx(1.6, abs=0.01)


def test_panel_width_survives(qtbot, repo_linear, store):
    first = MainWindow(repo_linear, settings=store)
    qtbot.addWidget(first)
    first.splitter.setSizes([700, 300])
    first.save_settings()

    second = MainWindow(repo_linear, settings=store)
    qtbot.addWidget(second)
    assert second.splitter.sizes()[1] > 0


def test_an_offscreen_geometry_is_ignored(qtbot, repo_linear, store):
    """§D51 : débrancher un moniteur ne doit pas rendre l'app injoignable.

    Le test qui distingue cette phase d'une restauration naïve : sans lui,
    une géométrie mémorisée sur un second écran rouvrirait la fenêtre hors
    de tout écran, invisible et inatteignable.
    """
    window = MainWindow(repo_linear, settings=store)
    qtbot.addWidget(window)
    assert not window.geometry_is_visible(QRect(-9000, -9000, 800, 600))
    assert window.geometry_is_visible(window.geometry())


def test_a_fresh_profile_uses_the_defaults(qtbot, repo_linear, store):
    """Premier lancement : aucun réglage, aucun plantage."""
    window = MainWindow(repo_linear, settings=store)
    qtbot.addWidget(window)
    assert window.view.current_zoom() == pytest.approx(1.0)


def test_saving_twice_is_idempotent(qtbot, repo_linear, store):
    window = MainWindow(repo_linear, settings=store)
    qtbot.addWidget(window)
    window.view.set_zoom(1.3)
    window.save_settings()
    premier = store.value("view/zoom")
    window.save_settings()
    assert store.value("view/zoom") == premier
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_settings_restore.py -v`
Expected: FAIL — `AttributeError: 'MainWindow' object has no attribute 'save_settings'`

- [ ] **Step 3: Write minimal implementation**

Ajouter à `main_window.py` (appeler `self.restore_settings()` à la fin de `__init__`) :

```python
    def geometry_is_visible(self, geometry) -> bool:
        """La géométrie recoupe-t-elle un écran réellement présent ?

        Sans ce contrôle, une fenêtre mémorisée sur un moniteur débranché
        rouvrirait hors de tout écran : invisible, et impossible à
        rattraper autrement qu'en supprimant les préférences (§D51).
        """
        for ecran in QGuiApplication.screens():
            if ecran.availableGeometry().intersects(geometry):
                return True
        return False

    def restore_settings(self) -> None:
        """Réapplique les réglages mémorisés, en se méfiant de chacun."""
        brut = self.settings.value("window/geometry")
        if isinstance(brut, (bytes, QByteArray)):
            sauvegarde = self.saveGeometry()
            if self.restoreGeometry(QByteArray(brut)):
                if not self.geometry_is_visible(self.geometry()):
                    self.restoreGeometry(sauvegarde)

        zoom = self.settings.value("view/zoom")
        if isinstance(zoom, (int, float)) and zoom > 0:
            self.view.set_zoom(float(zoom))

        largeur = self.settings.value("view/panel_width")
        if isinstance(largeur, int) and largeur > 0:
            total = sum(self.splitter.sizes())
            if total > largeur:
                self.splitter.setSizes([total - largeur, largeur])

    def save_settings(self) -> None:
        """Mémorise l'état courant. Appelé à la fermeture."""
        self.settings.set_value(
            "window/geometry", bytes(self.saveGeometry())
        )
        self.settings.set_value("view/zoom", self.view.current_zoom())
        tailles = self.splitter.sizes()
        if len(tailles) > 1:
            self.settings.set_value("view/panel_width", tailles[1])

    def closeEvent(self, event) -> None:
        self.save_settings()
        super().closeEvent(event)
```

Ajouter l'import : `from PySide6.QtCore import QByteArray` (et `QGuiApplication` est déjà importé).

- [ ] **Step 4: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_settings_restore.py tests/ui/test_main_window.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/tortoisepy/ui/main_window.py tests/ui/test_settings_restore.py
git commit -m "feat(settings): restaurer géométrie, zoom et panneau"
```

---

### Task 7 : Le filtre de tags, exposé et persisté (D52)

**Files:**
- Modify: `src/tortoisepy/ui/main_window.py` (barre d'outils, `refresh`)
- Modify: `src/tortoisepy/core/graph_cache.py` (la clé tient compte des options)
- Test: `tests/ui/test_tags_filter.py`, `tests/core/test_graph_cache_options.py`

**Décision appliquée :** D52 — le filtre est **exposé dans l'UI avant
d'être persisté**. Vérifié : `GraphOptions` porte cinq filtres et aucun
n'est accessible depuis `ui/`. Persister un réglage que l'utilisateur ne
peut pas atteindre n'aurait aucun effet visible.

**Interfaces:**
- Consumes: `core.options.GraphOptions`, `SettingsStore`
- Produces:
  - `MainWindow.show_tags_action: QAction` (cochable)
  - `MainWindow.graph_options() -> GraphOptions`
  - `GraphCache.get(repo, build, options_key=None)`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_graph_cache_options.py
from tortoisepy.core.graph_cache import GraphCache


def test_changing_the_options_key_rebuilds(repo_linear):
    """Le défaut que la lecture du code a révélé.

    `repo_fingerprint` ne connaît que les refs, HEAD et l'état. Basculer
    le filtre de tags ne change aucune ref : sans clé d'options, le cache
    rendrait le graphe précédent et l'interface ne bougerait pas.
    """
    appels = []

    def build(repo):
        appels.append(1)
        return object()

    cache = GraphCache()
    cache.get(repo_linear, build, options_key=("tags", True))
    cache.get(repo_linear, build, options_key=("tags", True))
    assert len(appels) == 1, "même clé : pas de reconstruction"

    cache.get(repo_linear, build, options_key=("tags", False))
    assert len(appels) == 2, "clé changée : reconstruction attendue"


def test_the_options_key_is_optional(repo_linear):
    """Les appels existants restent valides."""
    cache = GraphCache()
    premier = cache.get(repo_linear, lambda r: "graphe")
    assert cache.get(repo_linear, lambda r: "autre") == premier
```

```python
# tests/ui/test_tags_filter.py
import pytest
from PySide6.QtCore import QSettings

from tortoisepy.ui.main_window import MainWindow
from tortoisepy.ui.settings_store import SettingsStore


@pytest.fixture
def store(tmp_path):
    return SettingsStore(
        QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    )


def test_the_filter_is_exposed(qtbot, repo_linear, store):
    """§5.3 : aucun filtre n'était accessible depuis l'UI."""
    window = MainWindow(repo_linear, settings=store)
    qtbot.addWidget(window)
    assert window.show_tags_action.isCheckable()
    assert window.show_tags_action.isChecked() is True


def test_toggling_updates_the_options(qtbot, repo_linear, store):
    window = MainWindow(repo_linear, settings=store)
    qtbot.addWidget(window)
    window.show_tags_action.setChecked(False)
    assert window.graph_options().show_tags is False


def test_the_choice_survives_a_reopen(qtbot, repo_linear, store):
    first = MainWindow(repo_linear, settings=store)
    qtbot.addWidget(first)
    first.show_tags_action.setChecked(False)
    first.save_settings()

    second = MainWindow(repo_linear, settings=store)
    qtbot.addWidget(second)
    assert second.show_tags_action.isChecked() is False
    assert second.graph_options().show_tags is False


def test_the_other_filters_keep_their_measured_defaults(
    qtbot, repo_linear, store
):
    """§9 : seul `show_tags` entre dans le périmètre.

    Les quatre autres défauts sont justifiés par des mesures dans
    `options.py` et ne doivent pas bouger.
    """
    window = MainWindow(repo_linear, settings=store)
    qtbot.addWidget(window)
    options = window.graph_options()
    assert options.show_local_branches is True
    assert options.show_remote_branches is True
    assert options.show_stashes is True
    assert options.show_junctions is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/core/test_graph_cache_options.py tests/ui/test_tags_filter.py -v`
Expected: FAIL — `TypeError: get() got an unexpected keyword argument 'options_key'`

- [ ] **Step 3: Write minimal implementation**

Dans `src/tortoisepy/core/graph_cache.py`, modifier `get` :

```python
    def get(
        self,
        repo: pygit2.Repository,
        build: Callable[[pygit2.Repository], Any],
        options_key: tuple | None = None,
    ) -> Any:
        """Rend le graphe, en le reconstruisant seulement si nécessaire.

        `options_key` couvre ce que l'empreinte du dépôt ignore : les
        filtres d'affichage. Basculer le filtre de tags ne change aucune
        ref, donc aucune empreinte — sans cette clé, le cache rendrait le
        graphe précédent et l'interface ne bougerait pas.
        """
        empreinte = (repo_fingerprint(repo), options_key)
        if self._graphe is not None and empreinte == self._empreinte:
            return self._graphe

        graphe = build(repo)
        self._empreinte = empreinte
        self._graphe = graphe
        return graphe
```

Dans `main_window.py`, ajouter au `_build_toolbar` (ou après `_build_actions`) :

```python
        self.show_tags_action = QAction("Show tags", self)
        self.show_tags_action.setCheckable(True)
        self.show_tags_action.setChecked(
            bool(self.settings.value("view/show_tags"))
        )
        self.show_tags_action.toggled.connect(self._on_tags_toggled)
        self.toolbar.addAction(self.show_tags_action)
```

et les méthodes :

```python
    def graph_options(self) -> GraphOptions:
        """Options d'affichage courantes.

        Seul `show_tags` est réglable (§5.3) : les quatre autres gardent
        les défauts que `options.py` justifie par des mesures.
        """
        return GraphOptions(show_tags=self.show_tags_action.isChecked())

    def _on_tags_toggled(self, checked: bool) -> None:
        self.settings.set_value("view/show_tags", checked)
        self.refresh()
```

et modifier `refresh` pour passer options et clé :

```python
        options = self.graph_options()
        self.graph = self._graph_cache.get(
            self.repository,
            lambda repo: build_graph(repo, options),
            options_key=(options.show_tags,),
        )
```

Ajouter l'import : `from tortoisepy.core.options import GraphOptions`.

- [ ] **Step 4: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/core/test_graph_cache_options.py tests/ui/test_tags_filter.py tests/core/test_graph_cache.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/tortoisepy/core/graph_cache.py src/tortoisepy/ui/main_window.py tests/core/test_graph_cache_options.py tests/ui/test_tags_filter.py
git commit -m "feat(settings): filtre de tags exposé, persisté et pris en compte par le cache"
```

---

### Task 8 : Les dépôts récents

**Files:**
- Modify: `src/tortoisepy/ui/settings_store.py`
- Modify: `src/tortoisepy/ui/main_window.py` (menu « Open Recent »)
- Test: `tests/ui/test_recent_repositories.py`

**Interfaces:**
- Consumes: `SettingsStore`
- Produces:
  - `SettingsStore.recent_repositories() -> tuple[str, ...]` — purgée des chemins disparus
  - `SettingsStore.remember_repository(path: str) -> None`
  - `MAX_RECENT: int = 10`

- [ ] **Step 1: Write the failing test**

```python
# tests/ui/test_recent_repositories.py
import pytest
from PySide6.QtCore import QSettings

from tortoisepy.ui.settings_store import MAX_RECENT, SettingsStore


@pytest.fixture
def store(tmp_path):
    return SettingsStore(
        QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    )


def test_a_repository_is_remembered(store, tmp_path):
    store.remember_repository(str(tmp_path))
    assert str(tmp_path) in store.recent_repositories()


def test_the_most_recent_comes_first(store, tmp_path):
    premier = tmp_path / "un"
    second = tmp_path / "deux"
    premier.mkdir()
    second.mkdir()

    store.remember_repository(str(premier))
    store.remember_repository(str(second))
    assert store.recent_repositories()[0] == str(second)


def test_reopening_moves_it_up_without_duplicating(store, tmp_path):
    premier = tmp_path / "un"
    second = tmp_path / "deux"
    premier.mkdir()
    second.mkdir()

    store.remember_repository(str(premier))
    store.remember_repository(str(second))
    store.remember_repository(str(premier))

    recents = store.recent_repositories()
    assert recents[0] == str(premier)
    assert recents.count(str(premier)) == 1


def test_a_vanished_repository_is_purged(store, tmp_path):
    """Un dépôt déplacé ou supprimé ne doit pas encombrer la liste.

    Le test qui compte : sans purge, le menu proposerait des entrées qui
    échouent à l'ouverture, sans que l'utilisateur puisse les retirer.
    """
    disparu = tmp_path / "disparu"
    disparu.mkdir()
    store.remember_repository(str(disparu))
    disparu.rmdir()

    assert str(disparu) not in store.recent_repositories()


def test_the_list_is_capped(store, tmp_path):
    for index in range(MAX_RECENT + 5):
        chemin = tmp_path / f"depot-{index}"
        chemin.mkdir()
        store.remember_repository(str(chemin))

    assert len(store.recent_repositories()) <= MAX_RECENT
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_recent_repositories.py -v`
Expected: FAIL — `ImportError: cannot import name 'MAX_RECENT'`

- [ ] **Step 3: Write minimal implementation**

Ajouter à `src/tortoisepy/ui/settings_store.py` :

```python
import os

MAX_RECENT = 10
```

et les méthodes de `SettingsStore` :

```python
    def recent_repositories(self) -> tuple[str, ...]:
        """Les derniers dépôts ouverts, les disparus exclus.

        La purge se fait à la LECTURE et non à l'écriture : un dépôt peut
        être déplacé entre deux lancements, et proposer une entrée qui
        échoue à l'ouverture sans moyen de la retirer serait pire que de
        l'oublier.
        """
        bruts = self.value("recent/repositories") or ()
        return tuple(
            chemin for chemin in bruts if os.path.isdir(chemin)
        )

    def remember_repository(self, path: str) -> None:
        """Place `path` en tête, sans doublon, liste plafonnée."""
        restants = [
            chemin
            for chemin in self.recent_repositories()
            if chemin != path
        ]
        self.set_value(
            "recent/repositories", [path, *restants][:MAX_RECENT]
        )
```

Dans `main_window.py`, à la fin de `__init__` :

```python
        self.settings.remember_repository(
            str(Path(repository.path).parent)
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_recent_repositories.py -v`
Expected: PASS — 5 tests

- [ ] **Step 5: Commit**

```bash
git add src/tortoisepy/ui/settings_store.py src/tortoisepy/ui/main_window.py tests/ui/test_recent_repositories.py
git commit -m "feat(settings): liste des dépôts récents"
```

---

### Task 9 : Les garanties — confirmation, lecture seule, non-régression (D50)

**Files:**
- Test: `tests/ui/test_shortcut_safety.py`, `tests/test_settings_isolation.py`

**Décision appliquée :** D50 — les actions destructrices restent
**réassignables en principe**, mais leur confirmation est
**inconditionnelle**. Aucune n'entre dans le catalogue de la Task 2, ce qui
est la forme la plus solide de la garantie : ce qui n'a pas de raccourci ne
peut pas être déclenché par une frappe réflexe. Si l'une y entrait un jour,
le second test garantit que `confirmation_for` la connaît toujours.

**Interfaces:**
- Consumes: tout ce qui précède.
- Produces: aucun code de production — cette tâche verrouille les garanties de la spec.

- [ ] **Step 1: Write the failing test**

```python
# tests/ui/test_shortcut_safety.py
"""§6.4 : un raccourci ne doit jamais contourner la confirmation.

La phase 11 a coûté cher : « Drop stash » portait `needs_confirmation`,
un test l'affirmait, et le stash était pourtant détruit même sur un refus
— parce que `confirmation_for` n'avait pas de branche `drop_stash`. Poser
un drapeau ne protège rien. Ces tests visent la vraie porte.
"""

from tortoisepy.core.shortcuts import CATALOGUE
from tortoisepy.ui.dialogs import confirmation_for

DESTRUCTRICES = (
    "drop_stash",
    "delete_branch",
    "delete_remote_branch",
    "reset_to",
    "revert_commit",
)


def test_no_destructive_action_is_reachable_by_shortcut():
    """Aucune action destructrice n'est dans le catalogue.

    C'est la garantie la plus simple et la plus solide : ce qui n'a pas de
    raccourci ne peut pas être déclenché par une frappe réflexe.
    """
    ids = {spec.action_id for spec in CATALOGUE}
    assert ids & set(DESTRUCTRICES) == set()


def test_every_destructive_action_still_has_its_confirmation():
    """La porte reste fermée pour chacune d'elles.

    Si une action destructrice entrait un jour dans le catalogue, ce test
    garantit que `confirmation_for` la connaît toujours.
    """
    for action in DESTRUCTRICES:
        assert confirmation_for(action, {}) is not None, (
            f"« {action} » n'a plus de confirmation : "
            "c'est exactement la régression de la phase 11"
        )
```

```python
# tests/test_settings_isolation.py
"""§2.2 et §7 : les préférences vivent hors du dépôt et hors de l'install."""

import inspect

from tortoisepy.ui import settings_store


def test_the_store_never_writes_into_the_repository():
    """La garantie de lecture seule (§7.0) ne doit pas être entamée."""
    source = inspect.getsource(settings_store)
    assert ".git" not in source
    assert "repository.path" not in source


def test_the_store_never_writes_into_the_install_directory():
    """§2.2 : c'est ce qui fait survivre les réglages aux mises à jour.

    Écrire dans le dossier de l'application les ferait disparaître à
    chaque `uv tool install --force`.
    """
    source = inspect.getsource(settings_store)
    for interdit in ("__file__", "sys.prefix", "site-packages", "uv/tools"):
        assert interdit not in source, (
            f"« {interdit} » suggère une écriture dans l'installation"
        )


def test_the_default_store_uses_the_platform_location():
    """QSettings sans chemin explicite = emplacement natif de la plateforme."""
    assert settings_store.ORGANISATION == "tortoisePy"
    assert settings_store.APPLICATION == "tortoisePy"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_shortcut_safety.py tests/test_settings_isolation.py -v`
Expected: PASS immédiat si les tâches 1-8 sont correctes. Si un test échoue, c'est une vraie régression à corriger — ne pas modifier le test pour le faire passer.

- [ ] **Step 3: Vérifier la non-régression du rendu**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_graph_items.py tests/ui/test_theme.py tests/test_read_only.py tests/test_architecture.py -v`
Expected: PASS **sans qu'aucun de ces fichiers ait été modifié**. Le rendu validé par l'utilisateur et la garantie de lecture seule sont intacts.

- [ ] **Step 4: Suite complète**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -p no:randomly`
Expected: tout vert, à l'exception des deux instabilités connues et documentées (`test_fetch_hides_the_bar_when_done`, `test_worker_reports_its_result`), qui repassent isolément.

- [ ] **Step 5: Commit**

```bash
git add tests/ui/test_shortcut_safety.py tests/test_settings_isolation.py
git commit -m "test(settings): verrouille confirmation, isolation et non-régression"
```
