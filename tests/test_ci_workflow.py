"""Le workflow d'intégration continue, vérifié sans être exécuté.

Il n'est lu que par GitHub : une erreur dans ses conditions ne se voit
ni à l'import, ni au lancement des tests — seulement en production, et
le symptôme est alors un tag posé au mauvais endroit, ou pas posé du
tout.

Ce fichier épingle les trois propriétés dont dépend la sûreté du
déploiement.
"""

from __future__ import annotations

from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
WORKFLOW = RACINE / ".github" / "workflows" / "tests.yml"


@pytest.fixture
def workflow():
    yaml = pytest.importorskip(
        "yaml", reason="pyyaml absent : `uv pip install pyyaml`"
    )
    return yaml.safe_load(WORKFLOW.read_text())


def test_the_workflow_exists():
    assert WORKFLOW.is_file()


def test_the_tests_do_not_run_twice_on_the_same_code(workflow):
    """Les tests ne tournent que sur la pull request.

    Relevé par l'utilisateur : « les tests on les a déjà faits
    avant ». Vérifié par `git diff` entre le dernier commit de la PR
    et le commit de fusion — contenu rigoureusement identique, parce
    que la protection de branche exige d'avoir intégré `main` avant
    de fusionner.

    Les relancer coûtait dix minutes pour refaire le même travail, et
    retardait d'autant la pose du tag.
    """
    pytest_job = workflow["jobs"]["pytest"]

    assert pytest_job.get("if") == "github.event_name == 'pull_request'", (
        f"les tests tournent hors PR : if={pytest_job.get('if')}"
    )


def test_nothing_reaches_main_untested(workflow):
    """Ce qui remplace `needs: pytest`, et le vaut.

    Le job `tag` n'attend plus les tests, puisqu'ils ne tournent plus
    sur `main`. La garantie vient désormais de la protection de
    branche : elle exige `pytest` vert ET la branche à jour avant
    toute fusion.

    Ce test ne peut pas vérifier un réglage GitHub. Il épingle
    l'autre moitié du contrat : les tests DOIVENT tourner sur chaque
    pull request, sans quoi la protection n'aurait rien à exiger.
    """
    declencheurs = workflow[True] if True in workflow else workflow["on"]

    assert "pull_request" in declencheurs, (
        "aucun test sur les PR : la protection de branche ne peut "
        "plus rien exiger, et du code non testé atteindrait `main`"
    )


def test_the_tag_job_runs_only_on_main(workflow):
    """Jamais depuis une pull request : le code n'y est pas en production.

    Le piège : sans la condition sur l'événement, une PR vers `main`
    taguerait la branche de travail.
    """
    condition = workflow["jobs"]["tag"]["if"]

    assert "refs/heads/main" in condition, condition
    assert "push" in condition, (
        f"le job peut partir sur autre chose qu'une fusion : {condition}"
    )


def test_the_tag_job_can_push(workflow):
    """Sans ce droit, la poussée échoue — et le job passe pour vert.

    Vérifié : un workflow sans `contents: write` ne peut pas créer de
    référence, et l'échec survient à la dernière ligne.
    """
    permissions = workflow["jobs"]["tag"].get("permissions", {})

    assert permissions.get("contents") == "write", permissions


def test_the_tag_job_never_forces(workflow):
    """Réécrire un tag publié se demande, cela ne s'automatise pas.

    Il a fallu le faire deux fois à la main dans cette session, en
    connaissance de cause. Un job qui le ferait seul écraserait une
    référence que d'autres ont pu récupérer.
    """
    etapes = workflow["jobs"]["tag"]["steps"]
    commandes = " ".join(e.get("run", "") for e in etapes)

    assert "--force" not in commandes, commandes
    assert "tag -f" not in commandes, commandes


def test_the_tag_job_skips_when_the_tag_exists(workflow):
    """Trois fusions sur huit ne changent pas la version (mesuré).

    Sans ce garde-fou, chacune ferait échouer le job sur
    « tag already exists » — et une CI qui rougit sans raison valable
    est une CI qu'on apprend à ignorer.
    """
    etapes = workflow["jobs"]["tag"]["steps"]
    commandes = " ".join(e.get("run", "") for e in etapes)

    assert "rev-parse" in commandes, (
        "le job ne vérifie pas si le tag existe déjà"
    )


def test_the_version_comes_from_pyproject(workflow):
    """Source unique : c'est elle que lit `importlib.metadata`.

    Un fichier de version séparé en ferait une seconde, et le jour où
    les deux divergent, le tag annoncerait autre chose que le paquet
    réellement installé.
    """
    etapes = workflow["jobs"]["tag"]["steps"]
    commandes = " ".join(e.get("run", "") for e in etapes)

    assert "pyproject.toml" in commandes, commandes


def test_the_tag_job_fetches_the_history(workflow):
    """Un clone superficiel ne rapporte pas les tags.

    Sans `fetch-depth: 0`, la vérification d'existence répondrait
    toujours « absent », et le job tenterait de reposer un tag qui
    existe — échec à chaque fusion sans version.
    """
    etapes = workflow["jobs"]["tag"]["steps"]
    checkout = [e for e in etapes if "checkout" in str(e.get("uses", ""))]

    assert checkout, "le job ne récupère pas le dépôt"
    assert checkout[0].get("with", {}).get("fetch-depth") == 0, (
        f"les tags ne seront pas connus : {checkout[0]}"
    )


# --- la release, au-delà du tag -----------------------------------------


def _commandes_du_job_tag(workflow) -> str:
    return " ".join(
        etape.get("run", "") for etape in workflow["jobs"]["tag"]["steps"]
    )


def test_a_release_is_published(workflow):
    """Un tag suffit à installer, pas à se voir.

    Signalé par l'utilisateur : les nouveaux tags n'apparaissaient pas
    dans l'onglet « Releases ». Un tag est une référence Git ; une
    release est un objet GitHub par-dessus, seul affiché dans l'onglet
    et dans le fil des personnes qui suivent le dépôt.

    Mesuré au moment du signalement : quatorze releases publiées, mais
    trois tags récents sans release — l'historique semblait s'arrêter
    à la v0.14.0.
    """
    assert "gh release create" in _commandes_du_job_tag(workflow)


def test_the_release_is_skipped_when_it_exists(workflow):
    """Même raison que pour le tag : trois fusions sur huit ne
    changent pas la version, et une CI qui rougit à tort est une CI
    qu'on apprend à ignorer."""
    commandes = _commandes_du_job_tag(workflow)

    assert "gh release view" in commandes, (
        "le job ne vérifie pas si la release existe déjà"
    )


def test_the_release_notes_are_generated(workflow):
    """Des notes écrites à la main seraient vite abandonnées.

    `--generate-notes` les tire des commits et des PR fusionnées :
    rien à rédiger, et le contenu suit ce qui a réellement changé.
    """
    assert "--generate-notes" in _commandes_du_job_tag(workflow)


def test_the_release_step_has_a_token(workflow):
    """Sans `GH_TOKEN`, `gh` échoue sur « not authenticated ».

    Le piège : l'étape semble correcte, et n'échoue qu'à l'exécution.
    """
    etapes = workflow["jobs"]["tag"]["steps"]
    release = [e for e in etapes if "gh release" in e.get("run", "")]

    assert release, "aucune étape ne publie de release"
    assert "GH_TOKEN" in release[0].get("env", {}), (
        f"jeton absent : {release[0].get('env')}"
    )


def test_the_release_comes_after_the_tag(workflow):
    """Une release sans son tag n'a rien à pointer.

    L'ordre des étapes est la seule chose qui le garantit, puisque
    les deux vivent dans le même job.
    """
    etapes = workflow["jobs"]["tag"]["steps"]
    rangs = {
        "tag": next(
            i for i, e in enumerate(etapes) if "git tag" in e.get("run", "")
        ),
        "release": next(
            i for i, e in enumerate(etapes)
            if "gh release create" in e.get("run", "")
        ),
    }

    assert rangs["tag"] < rangs["release"], rangs


# --- la version, vérifiée avant les tests -------------------------------


def _commandes(workflow, job) -> str:
    return " ".join(e.get("run", "") for e in workflow["jobs"][job]["steps"])


def test_the_version_is_checked_before_the_tests(workflow):
    """Échouer en quinze secondes, pas en dix minutes.

    Avant, une version déjà taguée passait toute la suite puis
    échouait dans le job `tag` — dix minutes pour apprendre une chose
    vérifiable d'emblée.
    """
    assert workflow["jobs"]["pytest"].get("needs") == "check_version", (
        "les tests ne dépendent pas de la vérification de version"
    )


def test_it_refuses_an_existing_tag(workflow):
    """La version doit être libre.

    Sans ce contrôle, le job `tag` échouerait après coup sur
    « tag already exists », et la PR aurait été fusionnée entre-temps.
    """
    assert "rev-parse" in _commandes(workflow, "check_version")


def test_it_compares_versions_numerically(workflow):
    """`sort -V` et non un tri de chaînes.

    En ordre alphabétique, « 0.9.0 » passe pour supérieur à
    « 0.14.0 » : une version qui recule serait acceptée, et les
    gestionnaires de paquets ne la proposeraient jamais comme mise à
    jour.
    """
    commandes = _commandes(workflow, "check_version")

    assert "sort -V" in commandes, (
        "comparaison de versions sans tri naturel"
    )


def test_the_check_reads_pyproject(workflow):
    """Source unique : la version ne s'écrit plus qu'à cet endroit."""
    assert "pyproject.toml" in _commandes(workflow, "check_version")


def test_the_check_fetches_the_tags(workflow):
    """Un clone superficiel ne rapporte pas les tags.

    Sans eux, la vérification répondrait toujours « version libre »,
    et le contrôle ne contrôlerait rien.
    """
    etapes = workflow["jobs"]["check_version"]["steps"]
    checkout = [e for e in etapes if "checkout" in str(e.get("uses", ""))]

    assert checkout and checkout[0].get("with", {}).get("fetch-depth") == 0, (
        f"les tags ne seront pas connus : {checkout}"
    )


# --- develop remis à niveau après la release ----------------------------


def test_develop_is_synced_after_the_release(workflow):
    """Demandé par l'utilisateur, et fait trois fois à la main.

    Sans cette remise à niveau, la pull request suivante affiche
    « This branch is out-of-date with the base branch » : la
    protection exige d'avoir intégré `main` avant de fusionner.
    """
    sync = workflow["jobs"]["sync_develop"]

    assert sync.get("needs") == "tag", (
        f"la synchronisation ne suit pas le tag : needs={sync.get('needs')}"
    )


def test_the_sync_checks_out_develop(workflow):
    """Le défaut invisible : sans `ref`, on récupère `main`.

    Le job fusionnerait alors `main` dans `main`, ne verrait rien à
    faire, et rapporterait un succès — `develop` resterait en arrière
    sans que rien ne le signale.
    """
    etapes = workflow["jobs"]["sync_develop"]["steps"]
    checkout = [e for e in etapes if "checkout" in str(e.get("uses", ""))]

    assert checkout, "le job ne récupère pas le dépôt"
    assert checkout[0].get("with", {}).get("ref") == "develop", (
        f"la branche récupérée n'est pas develop : {checkout[0].get('with')}"
    )


def test_the_sync_can_push(workflow):
    """Sans ce droit, la poussée échoue à la dernière ligne."""
    permissions = workflow["jobs"]["sync_develop"].get("permissions", {})

    assert permissions.get("contents") == "write", permissions


def test_a_conflict_aborts_instead_of_half_merging(workflow):
    """Une fusion en conflit ne doit rien laisser à moitié appliqué.

    Le piège : un `git merge` qui échoue laisse l'index en état de
    conflit. Pousser ensuite, ou laisser la branche ainsi, demanderait
    un rattrapage que personne n'attend d'un job automatique.
    """
    commandes = _commandes(workflow, "sync_develop")

    assert "merge --abort" in commandes, (
        "un conflit laisserait develop à moitié fusionné"
    )


def test_the_sync_never_rewrites_develop(workflow):
    """Ni rebase ni force : `develop` est partagé.

    Le réécrire casserait les clones des autres postes — et
    l'utilisateur travaille depuis plusieurs machines.
    """
    # Les lignes de COMMENTAIRE sont écartées : celle qui explique
    # pourquoi on n'utilise pas de rebase contient le mot, et le test
    # échouait sur sa propre justification.
    lignes = [
        ligne.strip()
        for ligne in _commandes(workflow, "sync_develop").splitlines()
        if ligne.strip() and not ligne.strip().startswith("#")
    ]
    code = " ".join(lignes)

    assert "git rebase" not in code, code
    assert "--force" not in code, code


def test_the_sync_is_idempotent(workflow):
    """Rejouer le job ne doit pas créer une fusion vide.

    Le job tourne à chaque poussée sur `main`, y compris celles qui ne
    changent pas la version : sans ce garde-fou, chacune ajouterait un
    commit de fusion sans contenu.
    """
    commandes = _commandes(workflow, "sync_develop")

    assert "merge-base --is-ancestor" in commandes, (
        "le job ne vérifie pas si develop contient déjà main"
    )
