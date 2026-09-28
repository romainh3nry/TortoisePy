import pygit2


def test_pygit2_importable():
    assert pygit2.LIBGIT2_VERSION


def test_repository_has_required_methods(tmp_path):
    """Les méthodes dont dépendent les tâches 4 à 9.

    Testées sur une INSTANCE : `references` est une propriété, absente de la
    classe. La tester sur `pygit2.Repository` donnerait un faux négatif.
    """
    repo = pygit2.init_repository(str(tmp_path / "probe"))
    required = [
        "descendant_of",
        "walk",
        "references",
        "revparse_single",
        "listall_stashes",
    ]
    missing = [n for n in required if not hasattr(repo, n)]
    assert not missing, f"API pygit2 manquante : {missing}"


def test_no_pygit2_api_enumerates_all_merge_bases():
    """Vérifie la limite qui impose le parcours du DAG en tâche 6.

    Aucune API pygit2 ne retourne TOUS les merge-bases : merge_base,
    merge_base_many et merge_base_octopus retournent un OID unique.
    Si une version future expose une forme « all », ce test échoue — et
    c'est le signal pour reconsidérer l'algorithme de la tâche 6.
    """
    list_apis = [n for n in ("merge_bases", "merge_bases_many")
                 if hasattr(pygit2.Repository, n)]
    assert not list_apis, (
        f"pygit2 expose maintenant {list_apis} : réexaminer le parcours "
        "du DAG de la tâche 6, qui n'est peut-être plus nécessaire"
    )
    single = [n for n in ("merge_base", "merge_base_many", "merge_base_octopus")
              if hasattr(pygit2.Repository, n)]
    print(f"\nAPI merge-base (OID unique) : {single}")


def test_discover_repository_returns_none_when_absent(tmp_path):
    """Vérifié sur pygit2 1.20.0 : retourne None, ne lève pas.

    Une version antérieure de la spec §8 affirmait l'inverse. Le code
    testera `is None`, avec un try/except en ceinture et bretelles.
    """
    result = pygit2.discover_repository(str(tmp_path))
    assert result is None, (
        f"discover_repository retourne {result!r} au lieu de None — "
        "réexaminer la gestion d'erreur de la CLI"
    )
