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
    cache.get(repo_linear.repo, build, options_key=("tags", True))
    cache.get(repo_linear.repo, build, options_key=("tags", True))
    assert len(appels) == 1, "même clé : pas de reconstruction"

    cache.get(repo_linear.repo, build, options_key=("tags", False))
    assert len(appels) == 2, "clé changée : reconstruction attendue"


def test_the_options_key_is_optional(repo_linear):
    """Les appels existants restent valides."""
    cache = GraphCache()
    premier = cache.get(repo_linear.repo, lambda r: "graphe")
    assert cache.get(repo_linear.repo, lambda r: "autre") == premier
