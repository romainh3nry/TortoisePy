"""Le script de déploiement — vérifié, jamais exécuté pour de vrai.

Demandé par l'utilisateur : « une commande unique permettant de set la
version, merge develop dans main, créer le tag ».

Ce qu'il fait, et ce qu'il ne fait PAS. Le script s'arrête avant la
fusion, et c'est délibéré : la pull request est le seul moment où
quelqu'un regarde ce qui part en production, et c'est là que la CI
rend son verdict. Automatiser les trois étapes mécaniques — version,
commit, poussée — supprime les erreurs d'enchaînement sans supprimer
le jugement.

L'incident du 2026-10-15 est la raison d'être de ce script : la montée
de version avait été commitée sans être poussée, la fusion s'est faite
entre-temps, et le tag v0.14.0 s'est posé sur un commit déclarant
0.13.0. Deux gardes en découlent directement, chacun avec son test :
pousser AVANT d'annoncer, et vérifier la version de `main` AVANT de
taguer.

Aucun test n'écrit dans le vrai dépôt : les commandes Git sont
interceptées.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent


def _charger():
    """Charge `scripts/release.py`, dont la place interdit l'import."""
    spec = importlib.util.spec_from_file_location(
        "release", RACINE / "scripts" / "release.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def release():
    return _charger()


class FauxGit:
    """Enregistre les commandes au lieu de les exécuter.

    `reponses` permet de simuler l'état du dépôt : branche courante,
    arbre sale, version lue sur `main`.
    """

    def __init__(self, reponses: dict[str, str] | None = None):
        self.appels: list[list[str]] = []
        self.reponses = reponses or {}
        self.code = 0

    def __call__(self, *args, **kwargs):
        self.appels.append(list(args))
        cle = " ".join(args)
        for motif, valeur in self.reponses.items():
            if motif in cle:
                return valeur
        return ""

    def a_fait(self, *fragments: str) -> bool:
        """Une commande contenant tous ces fragments a-t-elle été lancée ?"""
        return any(
            all(f in " ".join(appel) for f in fragments)
            for appel in self.appels
        )


# --- le script existe et se tient ---------------------------------------


def test_the_script_exists():
    assert (RACINE / "scripts" / "release.py").is_file()


def test_it_reuses_the_version_script(release):
    """La logique de version n'est pas dupliquée.

    `set-version.py` connaît les quatre fichiers à modifier et son
    propre test garde cette liste à jour. La réécrire ici créerait deux
    sources de vérité, dont une finirait périmée.
    """
    source = (RACINE / "scripts" / "release.py").read_text()

    assert "set-version" in source or "set_version" in source, (
        "le script ne réutilise pas `set-version.py`"
    )


# --- les vérifications AVANT d'agir -------------------------------------


def test_it_refuses_outside_develop(release):
    """Déployer depuis une autre branche publierait n'importe quoi."""
    git = FauxGit({"rev-parse --abbrev-ref": "une-branche"})

    with pytest.raises(release.Refus) as motif:
        release.verifier_le_depart(git)

    assert "develop" in str(motif.value)


def test_it_refuses_a_dirty_tree(release):
    """Un arbre sale emporterait des modifications non relues.

    Le piège : `set-version.py` modifie quatre fichiers, et le commit
    qui suit ramasserait tout ce qui traîne à côté.
    """
    git = FauxGit({
        "rev-parse --abbrev-ref": "develop",
        "status --porcelain": " M src/un_fichier.py",
    })

    with pytest.raises(release.Refus) as motif:
        release.verifier_le_depart(git)

    assert "modification" in str(motif.value).lower()


def test_it_refuses_when_behind_origin(release):
    """Déployer en retard écraserait le travail d'un autre poste.

    Vérifié sur ce projet : l'utilisateur travaille depuis plusieurs
    machines.
    """
    git = FauxGit({
        "rev-parse --abbrev-ref": "develop",
        "status --porcelain": "",
        "rev-list --count origin/develop..develop": "0",
        "rev-list --count develop..origin/develop": "2",
    })

    with pytest.raises(release.Refus) as motif:
        release.verifier_le_depart(git)

    assert "origin" in str(motif.value)


def test_a_clean_start_is_accepted(release):
    """Le cas nominal ne doit pas être refusé par excès de prudence."""
    git = FauxGit({
        "rev-parse --abbrev-ref": "develop",
        "status --porcelain": "",
        "rev-list --count": "0",
    })

    release.verifier_le_depart(git)  # ne lève pas


# --- la version ---------------------------------------------------------


def test_it_refuses_a_malformed_version(release):
    """« 1.2 » ou « v.1 » doivent échouer avant toute écriture."""
    for mauvaise in ("1.2", "v", "abc", "1.2.3.4", ""):
        with pytest.raises(release.Refus):
            release.verifier_la_version(mauvaise, courante="0.14.0")


def test_it_refuses_a_version_that_goes_backwards(release):
    """Publier 0.13.0 après 0.14.0 casserait l'ordre des releases.

    Les gestionnaires de paquets comparent les versions : une version
    inférieure ne serait jamais proposée comme mise à jour.
    """
    with pytest.raises(release.Refus) as motif:
        release.verifier_la_version("0.13.0", courante="0.14.0")

    assert "0.14.0" in str(motif.value)


def test_it_refuses_the_current_version(release):
    """Rejouer la version courante ne produirait aucun changement."""
    with pytest.raises(release.Refus):
        release.verifier_la_version("0.14.0", courante="0.14.0")


def test_a_higher_version_is_accepted(release):
    release.verifier_la_version("0.15.0", courante="0.14.0")
    release.verifier_la_version("1.0.0", courante="0.14.0")
    # Le piège du tri de chaînes : « 0.9.0 » > « 0.14.0 » en texte.
    release.verifier_la_version("0.15.0", courante="0.9.0")


# --- l'incident du 2026-10-15 : pousser AVANT d'annoncer ---------------


def test_it_pushes_before_announcing(release):
    """Le garde né de l'incident.

    La montée de version avait été commitée sans être poussée, la
    fusion s'est faite entre-temps, et le tag s'est posé sur un commit
    déclarant l'ancienne version. L'ordre n'est donc pas un détail de
    confort : commit PUIS poussée, dans la même exécution.
    """
    git = FauxGit()
    release.commiter_et_pousser(git, "0.15.0")

    commits = [i for i, a in enumerate(git.appels) if "commit" in " ".join(a)]
    pousses = [i for i, a in enumerate(git.appels) if "push" in " ".join(a)]

    assert commits and pousses, "le script ne commite ou ne pousse pas"
    assert commits[0] < pousses[0], "la poussée précède le commit"


def test_the_commit_names_the_version(release):
    """L'historique doit se lire sans ouvrir le diff."""
    git = FauxGit()
    release.commiter_et_pousser(git, "0.15.0")

    assert git.a_fait("commit", "0.15.0")


def test_it_only_commits_the_version_files(release):
    """Le commit ne doit pas ramasser ce qui traîne.

    `git commit -a` emporterait tout fichier modifié à côté — et le
    départ est justement vérifié propre, donc ce serait un ajout
    silencieux.
    """
    git = FauxGit()
    release.commiter_et_pousser(git, "0.15.0")

    ajouts = [a for a in git.appels if "add" in a]
    assert ajouts, "rien n'est indexé"
    for ajout in ajouts:
        assert "-A" not in ajout and "." not in ajout, (
            f"indexation trop large : {ajout}"
        )


# --- l'incident, deuxième garde : vérifier main AVANT de taguer --------


def test_it_refuses_to_tag_when_main_lags(release):
    """LE garde qui aurait évité l'incident du 2026-10-15.

    Le tag v0.14.0 s'est posé sur un commit déclarant 0.13.0, parce
    que le commit de version n'était pas encore dans `main`. Un
    utilisateur installant depuis ce tag aurait obtenu le bon code
    sous le mauvais numéro.
    """
    git = FauxGit({"show origin/main:pyproject.toml": 'version = "0.13.0"'})

    with pytest.raises(release.Refus) as motif:
        release.taguer(git, "0.15.0")

    assert "0.13.0" in str(motif.value)
    assert not git.a_fait("tag"), "le tag a été posé malgré le refus"


def test_it_tags_when_main_is_up_to_date(release):
    """Le cas nominal : `main` déclare bien la version attendue."""
    git = FauxGit({"show origin/main:pyproject.toml": 'version = "0.15.0"'})

    release.taguer(git, "0.15.0")

    assert git.a_fait("tag", "v0.15.0")
    assert git.a_fait("push", "v0.15.0")


def test_the_tag_lands_on_main_not_on_head(release):
    """Le tag doit viser `origin/main`, pas la branche courante.

    Constaté en l'utilisant pour de vrai, sur la 0.15.0 : `git tag v…`
    sans cible tague `HEAD`. Le tag s'est posé sur le dernier commit
    de `develop`, hors de `main`, et embarquait donc un commit non
    fusionné — alors que les quatorze tags précédents du dépôt
    pointent tous sur un commit de fusion.

    Le script affichait pourtant « posé sur main ». Un message qui ne
    décrit pas ce qui s'est passé est pire que pas de message.
    """
    git = FauxGit({"show origin/main:pyproject.toml": 'version = "0.15.0"'})

    release.taguer(git, "0.15.0")

    poses = [a for a in git.appels if a and a[0] == "tag"]
    assert poses, "aucun tag posé"
    for appel in poses:
        assert "origin/main" in appel, (
            f"le tag ne vise pas main : {appel} — il tombera sur HEAD"
        )


def test_the_tag_carries_the_v_prefix(release):
    """Les quatorze tags du dépôt sont nommés `vX.Y.Z`.

    Un `0.15.0` sans `v` casserait les URL d'installation et le tri.
    """
    git = FauxGit({"show origin/main:pyproject.toml": 'version = "0.15.0"'})

    release.taguer(git, "0.15.0")

    poses = [a for a in git.appels if "tag" in a]
    assert all("v0.15.0" in " ".join(a) for a in poses), poses


def test_it_never_forces_the_tag(release):
    """Déplacer un tag publié est un geste à demander, pas à automatiser.

    Il a fallu le faire une fois, le 2026-10-15, en connaissance de
    cause. Un script qui le ferait seul réécrirait une référence que
    d'autres ont pu récupérer.
    """
    git = FauxGit({"show origin/main:pyproject.toml": 'version = "0.15.0"'})

    release.taguer(git, "0.15.0")

    for appel in git.appels:
        texte = " ".join(appel)
        assert "--force" not in texte and " -f " not in f" {texte} ", (
            f"le script force une référence : {texte}"
        )


# --- la pull request : affichée, pas créée ------------------------------


def test_it_shows_the_pull_request_url(release, capsys):
    """Choix de l'utilisateur : « on affiche le lien, ça suffit ».

    `gh` n'est pas authentifié sur ce poste, et dépendre d'un jeton
    ferait échouer le déploiement le jour où il expire.
    """
    release.annoncer_la_pr("0.15.0")

    sortie = capsys.readouterr().out
    assert "github.com/romainh3nry/TortoisePy" in sortie
    assert "compare" in sortie, "le lien n'ouvre pas une comparaison"
    assert "develop" in sortie


def test_it_does_not_call_gh(release):
    """Le script ne doit pas dépendre de `gh`.

    Le piège : l'ajouter « au cas où » rendrait le déploiement
    dépendant d'une authentification que l'utilisateur a explicitement
    écartée.
    """
    import ast

    arbre = ast.parse((RACINE / "scripts" / "release.py").read_text())
    chaines_appelees: list[str] = []
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Call):
            for argument in noeud.args:
                if isinstance(argument, ast.Constant) and isinstance(
                    argument.value, str
                ):
                    chaines_appelees.append(argument.value)

    assert "gh" not in chaines_appelees, "le script invoque `gh`"


# --- le script ne fusionne jamais lui-même ------------------------------


def test_it_never_merges(release):
    """La fusion reste un geste humain (choix de l'utilisateur, option A).

    C'est le seul moment où quelqu'un regarde ce qui part en
    production, et celui où la protection de branche exige une CI
    verte.
    """
    # On cherche un APPEL, pas une mention : la docstring cite la
    # demande de l'utilisateur, qui contient le mot « merge ». Une
    # recherche textuelle naïve échouait là-dessus.
    import ast

    arbre = ast.parse((RACINE / "scripts" / "release.py").read_text())
    chaines_appelees: list[str] = []
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Call):
            for argument in noeud.args:
                if isinstance(argument, ast.Constant) and isinstance(
                    argument.value, str
                ):
                    chaines_appelees.append(argument.value)

    assert not any("merge" in c for c in chaines_appelees), (
        f"le script lance une fusion : {chaines_appelees}"
    )


# --- le code de sortie, qui pilote tout script appelant ----------------


def test_a_refusal_exits_non_zero(release, monkeypatch, capsys):
    """Un script d'automatisation qui ment sur son succès est dangereux.

    Vérifié : sans ce test, rien ne garantissait que `main` rende 1
    après un refus — et un enchaînement `release.py && autre-chose`
    aurait continué sur un échec.
    """
    assert release.main(["0.1.0"]) == 1, "une version qui recule rend 0"
    assert release.main(["pas-une-version"]) == 1
    assert release.main([]) == 1, "l'usage rend 0"


def test_a_refusal_writes_to_stderr(release, capsys):
    """Les messages d'erreur ne doivent pas se perdre dans stdout.

    Un `release.py > journal.txt` doit laisser l'erreur visible au
    terminal.
    """
    release.main(["0.1.0"])

    flux = capsys.readouterr()
    assert "Arrêt" in flux.err, f"stderr vide, stdout : {flux.out!r}"
