# Installation & distribution — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> ## ⚠️ PLAN EN ATTENTE — NE PAS EXÉCUTER
>
> **Décidé avec l'utilisateur le 2026-09-30 :** l'application doit d'abord être
> terminée. Ce plan est rédigé maintenant, pendant que les mesures sont
> fraîches, et **attend son feu vert explicite**.
>
> Deux choses lui appartiennent et ne doivent pas être faites sans qu'il les
> demande : **choisir la licence** (§ Tâche 2) et **publier sur PyPI**
> (§ Après le plan) — cette dernière est **irréversible**, et désormais
> **facultative** : l'installation se fait depuis GitHub (D33).

**Goal:** Qu'un développeur installe tortoisePy en une commande, sur macOS ou
Windows, et lance `topy .` dans n'importe quel projet.

**Architecture:** Le point d'entrée existe déjà et accepte déjà un chemin ; il
suffit de le renommer, de lui donner un vrai `--help`, et d'emballer le tout.
La distribution passe par `uv tool install` **depuis le dépôt GitHub** (D33),
ce qui évite d'avoir à publier sur PyPI pour démarrer.

**Tech Stack:** Python 3.13, setuptools, uv.

**Spec:** `docs/superpowers/specs/2026-09-30-tortoisepy-install-design.md`

## Global Constraints

- **Ne jamais lancer de commande git sur CE dépôt** (add, commit, branch,
  checkout, stash, push, reset). L'utilisateur gère git lui-même.
- **Ne jamais publier sur PyPI ni TestPyPI.** Le plan prépare ; l'utilisateur
  publie. C'est irréversible : un numéro de version ne se réutilise pas, et un
  nom est réservé définitivement.
- **Ne pas installer `topy` sur cette machine** en dehors d'un test explicite
  immédiatement désinstallé : une commande posée dans le PATH de l'utilisateur
  est un effet de bord hors du dépôt.
- **Ne modifier aucun fichier de `src/tortoisepy/ui/` ni de `layout/`** : cette
  phase ne change pas le comportement de l'application.
- Commentaires et docstrings **en français** ; le **README en anglais**, comme
  tout paquet destiné à PyPI.

## Mesures déjà prises (ne pas refaire)

- Le paquet pèse **1,7 Mo** ; **PySide6 pèse 1,2 Go** — c'est ce que
  l'utilisateur téléchargera.
- **Aucune compilation** : `pygit2` et `PySide6` ont des roues pour
  `win_amd64` et `macosx universal2` (vérifié en les téléchargeant).
- `uv` publie des binaires pour **macOS Intel et ARM, Windows 32/64/ARM**, plus
  Linux (vérifié sur l'API PyPI).
- Une installation isolée prend **une minute**, et la commande répond ensuite
  depuis n'importe quel répertoire (testé de bout en bout, puis désinstallé).
- **`tortoisepy` est libre sur PyPI ; `topy` est pris** par un correcteur de
  fautes de frappe sans mise à jour depuis 2021. Sans conséquence — le nom du
  paquet et celui de la commande sont indépendants — mais à savoir.
- **Le dépôt `romainh3nry/TortoisePy` est public**, et GitHub sert ses
  fichiers en brut sans authentification (vérifié en téléchargeant
  `pyproject.toml`). `curl` vers le dépôt fonctionnera donc.
- **Modèle de branches** (décidé le 2026-09-30) : `develop` porte le
  développement, `main` **uniquement la production**. Les tags de version se
  posent donc sur `main`, une fois `develop` fusionnée — et c'est sur ce
  commit-là que les URL d'installation doivent tomber.
- `pyproject.toml` n'a **ni readme, ni license, ni authors, ni classifiers, ni
  urls** ; `README.md` et `LICENSE` **n'existent pas**.

## Review Focus

1. **Le piège du PATH** — vérifié lors d'une vraie installation : `uv` avertit
   que `~/.local/bin` n'y est pas, l'installation réussit, et `topy` reste
   introuvable. C'est là qu'un utilisateur abandonne.
2. **`--help` est pris pour un chemin de dépôt** (vérifié : « Pas de dépôt Git
   trouvé dans --help »). C'est la première chose que tape un nouvel
   utilisateur.
3. **Une option mal orthographiée** (`--verison`) ne doit pas être cherchée
   comme un dépôt.
4. **Le chemin Windows n'est pas testable ici** — pas de PowerShell, pas de
   machine Windows. Le script sera écrit d'après la documentation et relu, sans
   pouvoir être exécuté. À dire à l'utilisateur plutôt qu'à masquer.
5. **Rien ne doit être publié ni installé durablement** par l'exécution du plan.
6. **L'URL d'installation pointe vers un tag** (D34, tranché). Elle ne doit
   **jamais** viser une branche : `develop` porte le travail en cours, et même
   `main` peut recevoir un commit avant qu'une version soit prête.

---

### Task 1: La ligne de commande

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/tortoisepy/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces: la commande `topy`, un `--help`, et le refus des options inconnues

**Vérifié :** `cli.py:96` fait déjà `target = arguments[0] if arguments else "."`,
et `find_repository` remonte l'arborescence comme git. **`topy .` et
`topy /chemin` fonctionnent déjà** — il ne manque que le nom et les options.
Les codes de sortie sont déjà justes (`1` en échec, `0` sinon).

- [ ] **Step 1: Écrire les tests**

```python
# à ajouter dans tests/test_cli.py


def test_help_does_not_look_for_a_repository(capsys):
    """Vérifié : `--help` était pris pour un chemin de dépôt.

    « Pas de dépôt Git trouvé dans --help » — c'est la première chose que
    tape quelqu'un qui découvre l'outil.
    """
    from tortoisepy.cli import main

    assert main(["--help"]) == 0
    sortie = capsys.readouterr().out
    assert "topy" in sortie
    assert "dépôt" not in sortie.lower() or "trouvé" not in sortie.lower()


def test_an_unknown_option_is_refused(capsys):
    """`topy --verison` ne doit pas chercher un dépôt nommé « --verison »."""
    from tortoisepy.cli import main

    assert main(["--verison"]) == 1
    erreur = capsys.readouterr().err
    assert "--verison" in erreur


def test_a_bare_path_is_still_a_repository(tmp_path):
    """Ne pas casser ce qui marche : un chemin reste un chemin."""
    from tortoisepy.cli import find_repository

    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(tmp_path)], capture_output=True
    )
    assert find_repository(str(tmp_path)) is not None


def test_the_entry_point_is_named_topy():
    """Le renommage ne doit pas se perdre dans une fusion."""
    import tomllib
    from pathlib import Path

    racine = Path(__file__).resolve().parent.parent
    config = tomllib.loads((racine / "pyproject.toml").read_text())
    scripts = config["project"]["scripts"]

    assert "topy" in scripts
    assert scripts["topy"] == "tortoisepy.cli:main"
    assert "tgraph" not in scripts, "l'ancien nom ne doit pas subsister"
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/test_cli.py -q`
Expected: FAIL — `--help` cherche un dépôt, et le point d'entrée s'appelle
encore `tgraph`.

- [ ] **Step 3: Renommer le point d'entrée**

Dans `pyproject.toml` :

```toml
[project.scripts]
topy = "tortoisepy.cli:main"
```

**`tgraph` est retiré, pas conservé en alias** : deux noms pour la même chose
obligent à documenter lequel est le bon.

- [ ] **Step 4: Les options**

Dans `cli.py`, avant la résolution du chemin :

```python
_USAGE = """topy — TortoiseGit Revision Graph

Usage:
  topy [CHEMIN]        Ouvre le dépôt (défaut : le répertoire courant)
  topy --version       Affiche la version
  topy --install-icon  Installe l'icône système (macOS)
  topy --help          Affiche ce message

Exemples:
  topy .                     depuis un projet
  topy ~/code/mon-projet     un dépôt ailleurs
"""
```

```python
    if arguments and arguments[0] in ("--help", "-h"):
        print(_USAGE)
        return 0

    # Une option inconnue n'est pas un chemin : sans ce refus,
    # `topy --verison` cherchait un dépôt nommé « --verison » et
    # répondait « Pas de dépôt Git trouvé dans --verison » (vérifié).
    if arguments and arguments[0].startswith("-"):
        print(
            f"Option inconnue : {arguments[0]}\n\n{_USAGE}", file=sys.stderr
        )
        return 1
```

**Attention :** ce refus doit venir **après** `--version` et `--install-icon`,
qui commencent aussi par un tiret.

- [ ] **Step 5: Vérifier le succès**

Run: `.venv/bin/pytest tests/test_cli.py -q`
Expected: PASS.

Puis, à la main : `.venv/bin/python -m tortoisepy.cli --help`,
`--version`, `--verison` — et vérifier les trois sorties.

- [ ] **Step 6: Signaler les fichiers prêts** — ne commite pas.

---

### Task 2: Les métadonnées et le README

**Files:**
- Modify: `pyproject.toml`
- Create: `README.md`
- Create: `LICENSE`

**⚠️ La licence est une décision de l'utilisateur.** Ne pas en choisir une :
demander. Le plan ne peut pas trancher à sa place, parce que cela détermine ce
que d'autres auront le droit de faire du code. Sans licence, personne n'a
légalement le droit de l'utiliser.

Rappel des options, à lui présenter :
- **MIT** — permissif, le plus courant pour ce type d'outil ;
- **Apache-2.0** — permissif, avec une clause sur les brevets ;
- **GPL-3.0** — les dérivés doivent rester libres.

- [ ] **Step 1: Demander la licence**

Poser la question, attendre la réponse, écrire le `LICENSE` correspondant avec
le nom et l'année de l'utilisateur.

- [ ] **Step 2: Compléter `pyproject.toml`**

```toml
[project]
name = "tortoisepy"
version = "0.1.0"
description = "TortoiseGit's Revision Graph for macOS and Windows"
readme = "README.md"
requires-python = ">=3.13"
license = "<choix de l'utilisateur>"
authors = [{ name = "<son nom>", email = "<son email>" }]
keywords = ["git", "graph", "gui", "tortoisegit", "revision"]
classifiers = [
    "Development Status :: 4 - Beta",
    "Environment :: X11 Applications :: Qt",
    "Intended Audience :: Developers",
    "Programming Language :: Python :: 3.13",
    "Topic :: Software Development :: Version Control :: Git",
]
dependencies = ["pygit2>=1.15", "PySide6>=6.7"]

[project.urls]
Homepage = "<dépôt de l'utilisateur>"
Issues = "<dépôt>/issues"
```

**Vérifié :** la description actuelle dit « pour macOS » alors que l'outil vise
aussi Windows — à corriger.

- [ ] **Step 3: Écrire le README**

En anglais, et il doit contenir :

- ce que fait l'outil, en deux phrases ;
- **une capture d'écran** (l'utilisateur en a fourni ; lui demander laquelle) ;
- l'installation, **les deux plateformes**, sous **deux formes** :

  ```
  # macOS / Linux
  curl -LsSf https://raw.githubusercontent.com/romainh3nry/TortoisePy/<TAG>/scripts/install.sh | sh

  # Windows
  irm https://raw.githubusercontent.com/romainh3nry/TortoisePy/<TAG>/scripts/install.ps1 | iex
  ```

  et, pour qui refuse de piper un script distant dans un shell — **ils sont
  nombreux, et ils ont raison de se méfier** :

  ```
  uv tool install git+https://github.com/romainh3nry/TortoisePy
  ```

  **`<TAG>` et non `main`** : sinon un utilisateur installe la dernière
  version, même cassée. Le dépôt n'a pas encore de tag ; le créer est la
  première chose à faire avant de communiquer l'URL ;
- l'usage : `topy .`, `topy /chemin`, `topy` ;
- **l'avertissement sur la taille** : PySide6 pèse 1,2 Go. Le taire ferait
  croire à un problème pendant le téléchargement ;
- ce que l'outil **ne fait pas** (rebase interactif, staging par hunk…), pour
  ne pas décevoir.

- [ ] **Step 4: Vérifier que le paquet se construit**

Run: `.venv/bin/python -m build --wheel --outdir /tmp/verif_paquet`
(ou `uv build`), puis inspecter le contenu :

```bash
.venv/bin/python -m zipfile -l /tmp/verif_paquet/*.whl | head -20
```

Expected: le `.whl` contient `tortoisepy/`, ses `resources/*.png|ico|icns`, et
déclare `topy` dans ses `entry_points`.

- [ ] **Step 5: Signaler les fichiers prêts** — ne commite pas, ne publie pas.

---

### Task 3: Les scripts d'installation

**Files:**
- Create: `scripts/install.sh`
- Create: `scripts/install.ps1`
- Test: `tests/test_install_scripts.py`

**⚠️ Ces scripts ne doivent PAS être exécutés par les tests** : ils
installeraient vraiment, sur la machine de qui lance la suite. Les tests
vérifient leur contenu, pas leur effet.

**Le chemin Windows n'est pas testable ici** (ni PowerShell, ni machine
Windows). Le dire dans le rapport plutôt que de laisser croire à une
vérification.

- [ ] **Step 1: Écrire les tests**

```python
# tests/test_install_scripts.py
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("nom", ["install.sh", "install.ps1"])
def test_the_script_exists(nom):
    assert (RACINE / "scripts" / nom).is_file()


@pytest.mark.parametrize("nom", ["install.sh", "install.ps1"])
def test_the_script_checks_that_the_command_answers(nom):
    """D32, et Review Focus 1 : le piège du PATH.

    Vérifié lors d'une vraie installation : `uv` avertit que
    `~/.local/bin` n'est pas dans le PATH, l'installation réussit, et la
    commande reste introuvable. Un installeur qui ne vérifie pas son
    propre résultat n'a pas fini son travail.
    """
    contenu = (RACINE / "scripts" / nom).read_text()
    assert "topy --version" in contenu, "le script doit éprouver la commande"
    assert "PATH" in contenu, "il doit savoir expliquer le PATH"


def test_the_shell_script_is_executable():
    import os

    chemin = RACINE / "scripts" / "install.sh"
    assert os.access(chemin, os.X_OK), "chmod +x manquant"


@pytest.mark.parametrize("nom", ["install.sh", "install.ps1"])
def test_the_script_never_publishes(nom):
    """Un installeur qui publierait serait un accident grave."""
    contenu = (RACINE / "scripts" / nom).read_text()
    assert "publish" not in contenu
    assert "pypi.org/legacy" not in contenu


@pytest.mark.parametrize("nom", ["install.sh", "install.ps1"])
def test_the_script_installs_from_the_repository(nom):
    """D33 : depuis GitHub, donc rien d'irréversible à faire d'abord."""
    contenu = (RACINE / "scripts" / nom).read_text()
    assert "git+https://github.com/romainh3nry/TortoisePy" in contenu


def test_the_version_references_agree():
    """D34, et le piège du tag : deux endroits, une seule version.

    Figer l'URL du README sans figer le `@tag` du script ne fige **rien** :
    le script prendrait la branche par défaut. Et c'est l'oubli invisible,
    puisque le README, lui, a l'air juste.
    """
    import re

    readme = (RACINE / "README.md").read_text()
    dans_url = set(re.findall(r"TortoisePy/(v[\d.]+)/scripts/", readme))
    assert dans_url, "aucun tag dans les URL du README"

    for nom in ("install.sh", "install.ps1"):
        contenu = (RACINE / "scripts" / nom).read_text()
        dans_script = set(re.findall(r"TortoisePy@(v[\d.]+)", contenu))
        assert dans_script, f"{nom} n'épingle aucune version"
        assert dans_script == dans_url, (
            f"{nom} installe {dans_script}, le README annonce {dans_url}"
        )
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/test_install_scripts.py -q`
Expected: FAIL — les scripts n'existent pas.

- [ ] **Step 3: `scripts/install.sh`**

```bash
#!/usr/bin/env bash
# Installe tortoisePy et sa commande `topy` — macOS et Linux.
#
# `uv` plutôt que `pip` : il crée un environnement isolé ET télécharge
# l'interpréteur au besoin. L'utilisateur n'a donc pas à installer
# Python 3.13 lui-même, ce qui est le vrai obstacle.
set -euo pipefail

if ! command -v uv >/dev/null 2>&1; then
    echo "Installation de uv…"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # `uv` vient d'être posé : il n'est pas encore dans CE shell.
    export PATH="$HOME/.local/bin:$PATH"
fi

# Depuis le dépôt, pas depuis PyPI (D33) : rien n'est publié, donc rien
# n'est irréversible. Au tag, pas à `main` (D34) : sans le `@vX.Y.Z`, le
# script prendrait la branche par défaut et l'URL figée ne figerait rien.
# `--force` pour que réinstaller mette à jour.
uv tool install --force git+https://github.com/romainh3nry/TortoisePy@v0.1.0

# Vérifier son propre résultat : l'installation peut réussir alors que la
# commande reste introuvable, faute de PATH (vérifié). C'est précisément
# là qu'un utilisateur abandonne.
if topy --version >/dev/null 2>&1; then
    echo "Installé. Lancez « topy . » dans un projet Git."
else
    echo
    echo "tortoisePy est installé, mais « topy » n'est pas dans votre PATH."
    echo "Ajoutez cette ligne à votre ~/.zshrc ou ~/.bashrc :"
    echo
    echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
    echo
    echo "Ou lancez : uv tool update-shell"
    exit 1
fi
```

`chmod +x scripts/install.sh`.

- [ ] **Step 4: `scripts/install.ps1`**

**Ne pas tenter d'uniformiser vers `curl | sh` sur Windows** — la question
s'est posée et a été tranchée :

- **il n'y a pas de `sh` sur Windows.** C'est le vrai bloquant : même avec un
  `curl` fonctionnel, `| sh` échoue faute de shell POSIX ;
- **`curl` y est un alias de `Invoke-WebRequest`**, qui n'accepte pas
  `-LsSf` ; atteindre le vrai curl demande d'écrire `curl.exe` ;
- `irm ... | iex` est la forme idiomatique, et celle qu'emploient `uv`,
  `rustup` et Chocolatey — un développeur Windows l'a déjà tapée dix fois.

La symétrie visuelle entre les deux plateformes ne vaut pas une commande plus
longue et moins familière.

Même logique, en PowerShell : installer `uv` s'il manque
(`irm https://astral.sh/uv/install.ps1 | iex`), puis
`uv tool install --force git+https://github.com/romainh3nry/TortoisePy@v0.1.0`, puis
éprouver `topy --version` et expliquer le PATH sinon.

**Le signaler dans le rapport : ce script n'a pas pu être exécuté.**

- [ ] **Step 5: Vérifier**

Run: `.venv/bin/pytest tests/test_install_scripts.py -q`
Expected: PASS.

**Ne pas exécuter `install.sh`.** Pour éprouver le chemin réel, construire le
`.whl` et faire une installation depuis le fichier local, **puis désinstaller
aussitôt** :

```bash
uv tool install --from /tmp/verif_paquet/tortoisepy-0.1.0-py3-none-any.whl tortoisepy
topy --version
uv tool uninstall tortoisepy     # obligatoire : ne rien laisser derrière
```

- [ ] **Step 6: Suite complète**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`
Expected: 968 + ~12 tests. **Deux échecs connus et sans rapport** :
`test_fetch_hides_the_bar_when_done` et `test_worker_reports_its_result`.

- [ ] **Step 7: Signaler les fichiers prêts** — ne commite pas, ne publie pas.
Donner le décompte exact, et **dire explicitement que le chemin Windows n'a pas
été exécuté**.

---

## Après le plan — ce qui appartient à l'utilisateur

**Rien de ce qui suit ne doit être fait par un agent.**

### 1. Créer le tag — **décidé : on pointe vers un tag** (D34)

L'installation fonctionnerait sans tag (`main` est servi normalement,
vérifié), mais l'utilisateur a choisi un tag figé : personne n'installera un
état intermédiaire.

**Sur `main`, pas sur `develop`** : `main` est la branche de production
(décidé le 2026-09-30), et le tag doit désigner ce que les gens installeront.

```bash
git switch main
git merge develop          # amener le travail en production
git tag -a v0.1.0 -m "Première version publiable"
git push origin main v0.1.0
```

`-a` pour un tag **annoté** — il porte l'auteur, la date et un message, ce
qu'on veut pour une version publiée. `git push` seul n'envoie pas les tags.

**À chaque nouvelle version, deux endroits changent ensemble** (§3.2 de la
spec) :

1. l'URL dans le `README.md` ;
2. le `@vX.Y.Z` dans `scripts/install.sh` **et** `scripts/install.ps1`.

Le second est celui qu'on oublie : il est invisible depuis le README, et
l'oublier fait installer `main` en croyant installer une version figée. Le
test `test_the_version_references_agree` (tâche 3) le rattrape.

### 2. Publier sur PyPI — facultatif

L'installation depuis GitHub suffit. Publier n'apporterait que
`uv tool install tortoisepy` **sans URL**.

```bash
uv build
uv publish --token pypi-XXXX
```

Le jeton se crée sur pypi.org (compte + 2FA obligatoire), dans
*Account settings → API tokens*. **Passer d'abord par TestPyPI** pour voir la
page rendue :

```bash
uv publish --publish-url https://test.pypi.org/legacy/ --token pypi-XXXX
```

**Pourquoi c'est irréversible :** un numéro de version ne se réutilise jamais
(une erreur dans la `0.1.0` oblige à publier une `0.1.1`), le nom est réservé
définitivement, et le code devient public de façon permanente sous l'identité
de l'utilisateur.

### 3. Ce que `curl | sh` engage

Le script devient **du code public exécuté sur la machine des autres**. Une
erreur dedans s'exécute chez eux. C'est la norme de l'écosystème — `uv`,
Homebrew et rustup s'installent ainsi — mais cela mérite d'être su.

## Fin de phase 15

**Hors périmètre**, conformément à la spec §9 : publier (c'est à
l'utilisateur), un installeur `.dmg`/`.msi`, un exécutable autonome, et les
recettes Homebrew/winget/apt.
