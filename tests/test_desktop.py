"""Pose automatique de l'icône système — demandée par l'utilisateur.

Le Dock de macOS lit l'icône du bundle, pas celle de la fenêtre : sans
bundle, tortoisePy y apparaît sous les traits de l'interpréteur Python.
"""

from __future__ import annotations

import sys

import pytest

from tortoisepy.desktop import (
    install_bundle,
    install_if_missing,
    is_installed,
)


@pytest.fixture
def ailleurs(tmp_path, monkeypatch):
    """Un faux dossier personnel : ne rien écrire dans le vrai ~/Applications."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("TORTOISEPY_NO_DESKTOP_INSTALL", raising=False)
    return tmp_path / "Applications" / "tortoisePy.app"


@pytest.mark.skipif(sys.platform != "darwin", reason="bundle macOS")
def test_the_bundle_is_created(ailleurs):
    bundle = install_bundle(ailleurs)
    assert bundle is not None
    assert (bundle / "Contents" / "Info.plist").exists()
    assert (bundle / "Contents" / "Resources" / "tortoisepy.icns").exists()
    assert (bundle / "Contents" / "MacOS" / "tortoisepy").exists()


@pytest.mark.skipif(sys.platform != "darwin", reason="bundle macOS")
def test_the_launcher_is_executable(ailleurs):
    """Un lanceur non exécutable donnerait un bundle qui ne démarre pas."""
    import os

    bundle = install_bundle(ailleurs)
    lanceur = bundle / "Contents" / "MacOS" / "tortoisepy"
    assert os.access(lanceur, os.X_OK)


@pytest.mark.skipif(sys.platform != "darwin", reason="bundle macOS")
def test_the_launcher_points_at_this_interpreter(ailleurs):
    """Un `python3` du PATH pourrait ne pas connaître le paquet."""
    bundle = install_bundle(ailleurs)
    contenu = (bundle / "Contents" / "MacOS" / "tortoisepy").read_text()
    assert sys.executable in contenu


@pytest.mark.skipif(sys.platform != "darwin", reason="bundle macOS")
def test_it_installs_once_then_stops(ailleurs):
    """Posé au premier lancement, ignoré ensuite."""
    assert is_installed(ailleurs) is False

    assert install_bundle(ailleurs) is not None
    assert is_installed(ailleurs) is True

    # `install_if_missing` vise le vrai dossier personnel, que la fixture
    # a déplacé : il doit y trouver le bundle qu'on vient de créer.
    assert install_if_missing() is None


def test_the_opt_out_is_respected(tmp_path, monkeypatch):
    """Qui ne veut rien voir apparaître dans Applications peut refuser."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TORTOISEPY_NO_DESKTOP_INSTALL", "1")

    assert install_if_missing() is None
    assert not (tmp_path / "Applications").exists()


def test_nothing_is_installed_on_windows(monkeypatch):
    """Sur Windows, `setWindowIcon` suffit pour la barre des tâches."""
    monkeypatch.setattr(sys, "platform", "win32")
    assert install_if_missing() is None
    assert install_bundle() is None


def test_a_failure_never_raises(monkeypatch, tmp_path):
    """Une icône est un confort : son échec ne doit pas empêcher
    l'application de s'ouvrir."""
    if sys.platform != "darwin":
        pytest.skip("bundle macOS")

    def refuse(*args, **kwargs):
        raise OSError("disque plein")

    monkeypatch.setattr("pathlib.Path.mkdir", refuse)
    assert install_bundle(tmp_path / "Applications" / "x.app") is None
