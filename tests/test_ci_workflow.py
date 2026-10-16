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


def test_the_tag_job_waits_for_the_tests(workflow):
    """LA propriété qui justifie de taguer depuis la CI.

    Sans `needs`, GitHub lance les deux jobs en parallèle : un tag
    pourrait être posé sur du code dont les tests échouent, et
    l'utilisateur l'installerait.
    """
    tag = workflow["jobs"]["tag"]

    assert tag.get("needs") == "pytest", (
        f"le job `tag` ne dépend pas des tests : needs={tag.get('needs')}"
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
