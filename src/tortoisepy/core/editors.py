"""Trouver les éditeurs installés, pour y ouvrir le projet courant.

Demandé par l'utilisateur : un bouton qui ouvre le dépôt comme le
ferait `code .`, affiché seulement si l'éditeur est présent — « si pas
installé, on affiche rien ».

Pourquoi deux façons de chercher. `shutil.which` suffirait dans un
terminal, mais l'application se lance depuis un **bundle macOS**, qui
ne reçoit pas le `PATH` de l'utilisateur. Mesuré avant d'écrire :

    which("code") depuis le terminal    -> /usr/local/bin/code
    which("code") avec un PATH minimal  -> None

Sans chemins de repli, le bouton disparaîtrait chez quelqu'un qui a
pourtant VSCode installé — l'inverse exact de ce qui est demandé.

Aucun Qt : `tests/test_architecture.py` l'interdit à `core/`, et la
détection se teste ainsi sans fenêtre.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EditorSpec:
    """Un éditeur connu : son nom au menu, sa commande."""

    label: str
    command: str


@dataclass(frozen=True)
class Editor:
    """Un éditeur réellement trouvé, avec le chemin qui le lance."""

    label: str
    command: str
    path: str


CATALOGUE: tuple[EditorSpec, ...] = (
    EditorSpec("VS Code", "code"),
    EditorSpec("VS Code Insiders", "code-insiders"),
    EditorSpec("Cursor", "cursor"),
    EditorSpec("VSCodium", "codium"),
    EditorSpec("Zed", "zed"),
    EditorSpec("Sublime Text", "subl"),
    EditorSpec("PhpStorm", "phpstorm"),
    EditorSpec("PyCharm", "pycharm"),
    EditorSpec("IntelliJ IDEA", "idea"),
    EditorSpec("WebStorm", "webstorm"),
    EditorSpec("GoLand", "goland"),
    EditorSpec("RubyMine", "rubymine"),
    EditorSpec("CLion", "clion"),
    EditorSpec("Rider", "rider"),
    EditorSpec("DataGrip", "datagrip"),
    EditorSpec("Android Studio", "studio"),
)
"""Les éditeurs proposés, dans l'ordre du menu.

Liste fixe et non découverte : deviner quel éditeur l'utilisateur
préfère serait arbitraire, et l'ordre du disque n'est pas stable d'un
lancement à l'autre.
"""

_MAISON = Path.home()
_TOOLBOX = _MAISON / "Library" / "Application Support" / "JetBrains" / "Toolbox" / "scripts"

_REPLIS: dict[str, tuple[str, ...]] = {
    # Les emplacements où ces commandes se trouvent quand elles ne sont
    # pas dans le `PATH` du processus. Vérifiés sur une machine réelle :
    # `code` y vivait dans `/usr/local/bin`, `pycharm` et `idea` dans le
    # dossier de JetBrains Toolbox.
    #
    # Cette liste vieillira, et c'est accepté : un chemin disparu est
    # ignoré, les autres continuent de servir.
    "code": (
        "/usr/local/bin/code",
        "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code",
        str(_MAISON / "Applications/Visual Studio Code.app/Contents/Resources/app/bin/code"),
    ),
    "code-insiders": (
        "/usr/local/bin/code-insiders",
        "/Applications/Visual Studio Code - Insiders.app/Contents/Resources/app/bin/code-insiders",
    ),
    "cursor": (
        "/usr/local/bin/cursor",
        "/Applications/Cursor.app/Contents/Resources/app/bin/cursor",
    ),
    "codium": (
        "/usr/local/bin/codium",
        "/Applications/VSCodium.app/Contents/Resources/app/bin/codium",
    ),
    "zed": (
        "/usr/local/bin/zed",
        str(_MAISON / ".local/bin/zed"),
    ),
    "subl": (
        "/usr/local/bin/subl",
        "/Applications/Sublime Text.app/Contents/SharedSupport/bin/subl",
    ),
    # Toute la famille JetBrains passe par le même dossier de scripts,
    # posé par Toolbox. PhpStorm manquait à la première version, et
    # l'utilisateur l'a relevé : il était installé, donc invisible
    # pour rien.
    **{
        commande: (str(_TOOLBOX / commande),)
        for commande in (
            "phpstorm", "pycharm", "idea", "webstorm", "goland",
            "rubymine", "clion", "rider", "datagrip", "studio",
        )
    },
}


def _executable(chemin: str) -> bool:
    """Ce fichier peut-il être lancé ?

    Un fichier du bon nom mais sans droit d'exécution échouerait au
    lancement : le proposer ferait cliquer pour rien.
    """
    try:
        return os.path.isfile(chemin) and os.access(chemin, os.X_OK)
    except OSError:
        return False


def _trouver(spec: EditorSpec) -> Editor | None:
    """Le chemin de cet éditeur, ou `None` s'il n'est pas installé.

    Le `PATH` d'abord : ce que l'utilisateur y a mis fait foi — une
    version précise, ou un script à lui. Les replis sont un filet pour
    le cas du bundle, pas une préférence.
    """
    dans_path = shutil.which(spec.command)
    if dans_path:
        return Editor(spec.label, spec.command, dans_path)

    for repli in _REPLIS.get(spec.command, ()):
        if _executable(repli):
            return Editor(spec.label, spec.command, repli)

    return None


def find_editors() -> tuple[Editor, ...]:
    """Les éditeurs installés, dans l'ordre du catalogue.

    L'ordre est celui du catalogue et non celui du disque : deux
    lancements qui proposeraient les éditeurs différemment feraient
    cliquer au mauvais endroit par habitude.
    """
    trouves = (_trouver(spec) for spec in CATALOGUE)
    return tuple(editeur for editeur in trouves if editeur is not None)


def _lancer(commande: list[str]) -> bool:
    """Lance `commande` sans attendre sa fin.

    DÉTACHÉ : attendre la fermeture de l'éditeur gèlerait
    l'application, exactement le défaut corrigé ailleurs à propos de
    l'ouverture de projet.
    """
    try:
        subprocess.Popen(
            commande,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True
    except OSError:
        # Installation abîmée, droits manquants : l'appelant le dira à
        # l'utilisateur plutôt que de laisser un clic sans effet.
        return False


def open_in_editor(editor: Editor, folder: str) -> bool:
    """Ouvre `folder` dans `editor`. Faux si cela n'a pas pu se faire.

    Le dossier est vérifié : il a pu disparaître entre l'affichage du
    menu et le clic — même cas que « Open Project ».
    """
    try:
        if not Path(folder).is_dir():
            return False
    except OSError:
        return False

    return _lancer([editor.path, folder])
