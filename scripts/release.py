#!/usr/bin/env python3
"""Prépare une version : pose le numéro, commite, pousse, annonce la PR.

Demandé par l'utilisateur : « une commande unique permettant de set la
version, merge develop dans main, créer le tag ».

    python scripts/release.py 0.15.0     # prépare la version
    python scripts/release.py --tag      # tague, une fois la PR fusionnée

Pourquoi DEUX commandes et non une. Le script s'arrête avant la fusion,
délibérément : la pull request est le seul moment où quelqu'un regarde
ce qui part en production, et c'est là que la CI rend son verdict. Ce
qui est automatisé, ce sont les trois étapes mécaniques — version,
commit, poussée — où l'on se trompe d'ordre. Pas le jugement.

Ce script est né d'un incident, le 2026-10-15 : la montée de version
avait été commitée sans être poussée, la fusion s'est faite entre-temps,
et le tag `v0.14.0` s'est posé sur un commit déclarant encore 0.13.0.
Deux gardes en découlent, chacun tenu par un test :

  - commit PUIS poussée, dans la même exécution ;
  - avant de taguer, vérifier que `main` déclare bien la version
    attendue.

Il ne fusionne jamais, ne force aucune référence, et n'appelle pas
`gh` : il affiche le lien de la PR, ce qui marche sans jeton
d'authentification — et ne casse pas le jour où celui-ci expire.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
BRANCHE = "develop"
CIBLE = "main"
DEPOT = "https://github.com/romainh3nry/TortoisePy"

GABARIT = re.compile(r"^\d+\.\d+\.\d+$")


class Refus(Exception):
    """Le déploiement s'arrête, et dit pourquoi.

    Toujours levée AVANT d'avoir touché au dépôt : un script qui
    échoue à mi-parcours laisse un état que personne ne sait lire.
    """


def _set_version():
    """Charge `set-version.py`, dont le tiret interdit l'import.

    Réutilisé plutôt que recopié : il connaît les quatre fichiers qui
    portent la version, et son propre test garde cette liste à jour.
    Dupliquer la logique créerait une seconde source de vérité, qui
    finirait périmée.
    """
    spec = importlib.util.spec_from_file_location(
        "set_version", RACINE / "scripts" / "set-version.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(*args: str) -> str:
    """Lance une commande Git et rend sa sortie, sans le retour final."""
    resultat = subprocess.run(
        ["git", *args], cwd=RACINE, capture_output=True, text=True,
    )
    if resultat.returncode != 0:
        raise Refus(
            f"git {' '.join(args)} a échoué :\n{resultat.stderr.strip()}"
        )
    return resultat.stdout.strip()


# --- vérifications, toutes avant la moindre écriture -------------------


def verifier_le_depart(lanceur=git) -> None:
    """Le dépôt est-il en état de recevoir une version ?

    Les trois refus correspondent à trois façons de publier n'importe
    quoi : depuis la mauvaise branche, avec du travail non relu, ou en
    retard sur un autre poste.
    """
    branche = lanceur("rev-parse", "--abbrev-ref", "HEAD")
    if branche != BRANCHE:
        raise Refus(
            f"Vous êtes sur « {branche} ». Le déploiement part de "
            f"« {BRANCHE} »."
        )

    sale = lanceur("status", "--porcelain")
    if sale:
        raise Refus(
            "L'arbre de travail porte des modifications non commitées.\n"
            "Le commit de version les emporterait sans qu'elles aient "
            "été relues :\n" + sale
        )

    lanceur("fetch", "origin")
    retard = lanceur(
        "rev-list", "--count", f"{BRANCHE}..origin/{BRANCHE}"
    )
    if retard and retard != "0":
        raise Refus(
            f"{BRANCHE} est en retard de {retard} commit(s) sur origin. "
            "Faites un `git pull` d'abord."
        )


def _en_nombres(version: str) -> tuple[int, ...]:
    """« 0.9.0 » → (0, 9, 0).

    Comparer les chaînes directement serait faux : « 0.9.0 » passe
    pour supérieur à « 0.14.0 » en ordre alphabétique.
    """
    return tuple(int(morceau) for morceau in version.split("."))


def verifier_la_version(nouvelle: str, courante: str) -> None:
    """Le numéro est-il bien formé, et va-t-il de l'avant ?

    Une version qui recule ne serait jamais proposée comme mise à jour
    par les gestionnaires de paquets, qui comparent les numéros.
    """
    if not GABARIT.match(nouvelle):
        raise Refus(
            f"Version invalide : « {nouvelle} ». Attendu : 1.2.3"
        )

    if _en_nombres(nouvelle) <= _en_nombres(courante):
        raise Refus(
            f"« {nouvelle} » ne suit pas la version courante "
            f"« {courante} »."
        )


# --- les actions -------------------------------------------------------


def commiter_et_pousser(lanceur=git, version: str = "") -> None:
    """Commite les fichiers de version, PUIS pousse. Dans cet ordre.

    L'ordre est le garde né de l'incident du 2026-10-15 : un commit
    gardé en local pendant qu'on annonce la version prête est
    exactement ce qui a fait poser un tag sur le mauvais commit.

    Les fichiers sont nommés un par un : `git add -A` emporterait tout
    ce qui traîne à côté — et le départ a justement été vérifié
    propre, donc ce serait un ajout silencieux.
    """
    for fichier in (
        "pyproject.toml", "README.md",
        "scripts/install.sh", "scripts/install.ps1",
    ):
        lanceur("add", fichier)

    lanceur("commit", "-m", f"version update to v{version}")
    lanceur("push", "origin", BRANCHE)


def annoncer_la_pr(version: str) -> None:
    """Affiche le lien de la pull request à ouvrir.

    Pas d'appel à `gh` : il n'est pas authentifié sur ce poste (choix
    de l'utilisateur), et en dépendre ferait échouer le déploiement le
    jour où un jeton expire. Un lien marche toujours.
    """
    print()
    print(f"  Version {version} poussée sur {BRANCHE}.")
    print()
    print("  Ouvrez la pull request :")
    print(f"      {DEPOT}/compare/{CIBLE}...{BRANCHE}?expand=1")
    print()
    print("  La CI se lance à l'ouverture (12 à 20 min). Une fois la")
    print("  PR fusionnée :")
    print("      python scripts/release.py --tag")
    print()


def taguer(lanceur=git, version: str = "") -> None:
    """Pose le tag, après avoir vérifié que `main` dit la même chose.

    LE garde qui aurait évité l'incident : le tag v0.14.0 s'était posé
    sur un commit déclarant 0.13.0, parce que la montée de version
    n'était pas encore dans `main`. Un utilisateur installant depuis
    ce tag aurait reçu le bon code sous le mauvais numéro.

    Aucun `--force` : déplacer un tag publié réécrit une référence que
    d'autres ont pu récupérer. Cela se demande, cela ne s'automatise
    pas.
    """
    lanceur("fetch", "origin")
    contenu = lanceur("show", f"origin/{CIBLE}:pyproject.toml")

    trouve = re.search(r'^version = "([^"]+)"', contenu, re.MULTILINE)
    declaree = trouve.group(1) if trouve else "?"

    if declaree != version:
        raise Refus(
            f"{CIBLE} déclare la version « {declaree} », pas "
            f"« {version} ».\n"
            "La pull request n'est sans doute pas encore fusionnée — "
            "taguer maintenant poserait v"
            f"{version} sur du code qui s'annonce {declaree}."
        )

    # `origin/main` EXPLICITEMENT, et non `git tag v…` seul : sans
    # cible, Git tague `HEAD`. Constaté en l'utilisant sur la 0.15.0 —
    # le tag s'est posé sur le dernier commit de `develop`, hors de
    # `main`, embarquant un commit non fusionné. Les quatorze tags
    # précédents du dépôt pointent tous sur un commit de fusion.
    lanceur("tag", f"v{version}", f"origin/{CIBLE}")
    lanceur("push", "origin", f"v{version}")

    # Le message nomme le commit réellement tagué : « posé sur main »
    # était affiché alors que le tag était ailleurs, ce qui a masqué
    # l'erreur jusqu'à l'échec de l'installation.
    pose = lanceur("rev-parse", "--short", f"v{version}")
    print(f"\n  Tag v{version} posé sur {CIBLE} ({pose}).\n")


# --- enchaînement ------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    version_module = _set_version()
    courante_pour_aide = version_module.version_courante()

    try:
        if arguments and arguments[0] == "--tag":
            taguer(git, version_module.version_courante())
            return 0

        if not arguments:
            # La syntaxe, et non une phrase de contexte : découper la
            # docstring donnait la citation de la demande, inutile à
            # qui cherche comment lancer la commande (constaté).
            print(
                "Usage :\n"
                "    python scripts/release.py X.Y.Z   prépare la version\n"
                "    python scripts/release.py --tag   tague, PR fusionnée\n"
                f"\nVersion courante : {courante_pour_aide}",
                file=sys.stderr,
            )
            return 1

        nouvelle = arguments[0].lstrip("v")
        courante = version_module.version_courante()

        # Toutes les vérifications d'abord : échouer après avoir écrit
        # laisserait un état à rattraper à la main.
        verifier_la_version(nouvelle, courante)
        verifier_le_depart(git)

        print(f"  {courante} → {nouvelle}")
        for fichier, nombre in version_module.poser(nouvelle):
            print(f"    {fichier:<22} {nombre} occurrence(s)")

        version_module.rafraichir_venv()
        commiter_et_pousser(git, nouvelle)
        annoncer_la_pr(nouvelle)
        return 0

    except Refus as motif:
        print(f"\n  Arrêt : {motif}\n", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
