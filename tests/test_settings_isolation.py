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

    Le docstring du module explique volontairement ce risque et cite
    `uv/tools` comme contre-exemple : il est exclu de l'inspection, sinon
    le test se déclenche sur sa propre documentation plutôt que sur du
    code qui écrirait réellement là.
    """
    source = inspect.getsource(settings_store)
    sans_docstring = source.replace(settings_store.__doc__ or "", "", 1)
    for interdit in ("__file__", "sys.prefix", "site-packages", "uv/tools"):
        assert interdit not in sans_docstring, (
            f"« {interdit} » suggère une écriture dans l'installation"
        )


def test_the_default_store_uses_the_platform_location():
    """QSettings sans chemin explicite = emplacement natif de la plateforme."""
    assert settings_store.ORGANISATION == "tortoisePy"
    assert settings_store.APPLICATION == "tortoisePy"
