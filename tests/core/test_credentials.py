"""Identifiants HTTPS délégués à Git — §7.3.

Contexte : signalé par l'utilisateur sur le dépôt `portfolio`, un push
HTTPS échouait sur « remote authentication required but no callback set ».
libgit2 ne consulte pas le gestionnaire d'identifiants de Git ; il faut le
lui donner.
"""

from __future__ import annotations

import subprocess

import pytest

from tortoisepy.core.credentials import (
    Credentials,
    credentials_for,
    is_https,
    remember,
)


def test_recognises_https():
    assert is_https("https://github.com/a/b.git") is True
    assert is_https("http://interne/a.git") is True


def test_ssh_is_not_https():
    """SSH garde l'agent : aucun mot de passe ne doit être manipulé."""
    assert is_https("git@github.com:a/b.git") is False
    assert is_https("ssh://git@host/a.git") is False


def test_ssh_url_yields_no_credentials():
    assert credentials_for("git@github.com:a/b.git") is None


def test_url_without_host_is_rejected():
    assert credentials_for("https://") is None


def test_unknown_host_returns_none():
    """Sans identifiant connu, `git credential fill` sort en 128.

    Le test vaut aussi comme garde anti-blocage : `GIT_TERMINAL_PROMPT=0`
    empêche Git de poser une question sur un terminal inexistant.
    """
    assert credentials_for("https://hote-qui-nexiste-pas.invalid/x.git") is None


def test_password_never_appears_in_repr():
    """Un secret ne doit jamais fuir dans une trace ou un journal."""
    text = repr(Credentials(username="alice", password="s3cr3t-token"))
    assert "s3cr3t-token" not in text
    assert "alice" in text


def test_credentials_are_frozen():
    import dataclasses

    creds = Credentials(username="a", password="b")
    with pytest.raises(dataclasses.FrozenInstanceError):
        creds.username = "autre"


def test_newline_in_password_is_refused():
    """Le protocole de `git credential` est ligne par ligne.

    Un saut de ligne permettrait d'injecter une clé arbitraire dans la
    requête ; on refuse plutôt que de corrompre l'échange.
    """
    piege = Credentials(username="a", password="b\nhost=evil.example")
    assert remember("https://github.com/a/b.git", piege) is False


def test_newline_in_username_is_refused():
    piege = Credentials(username="a\nhost=evil.example", password="b")
    assert remember("https://github.com/a/b.git", piege) is False


def test_remember_refuses_a_non_https_url():
    assert remember("git@github.com:a/b.git", Credentials("a", "b")) is False


def test_query_includes_host_and_protocol(monkeypatch):
    """La requête doit suivre le format documenté de `git credential`."""
    vues = {}

    def faux_run(cmd, **kwargs):
        vues["cmd"] = cmd
        vues["input"] = kwargs.get("input", "")
        vues["env"] = kwargs.get("env", {})
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", faux_run)
    credentials_for("https://github.com/romain/projet.git")

    assert vues["cmd"][:3] == ["git", "credential", "fill"]
    assert "protocol=https" in vues["input"]
    assert "host=github.com" in vues["input"]
    assert "path=romain/projet.git" in vues["input"]
    # La garde anti-blocage doit être posée.
    assert vues["env"].get("GIT_TERMINAL_PROMPT") == "0"


def test_parses_the_helper_answer(monkeypatch):
    def faux_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, 0,
            stdout="protocol=https\nhost=github.com\nusername=alice\npassword=tok\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", faux_run)
    found = credentials_for("https://github.com/a/b.git")
    assert found == Credentials(username="alice", password="tok")


def test_partial_answer_is_rejected(monkeypatch):
    """Un identifiant sans mot de passe ne sert à rien."""
    def faux_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, 0, stdout="protocol=https\nusername=alice\n", stderr=""
        )

    monkeypatch.setattr(subprocess, "run", faux_run)
    assert credentials_for("https://github.com/a/b.git") is None


def test_a_timeout_does_not_propagate(monkeypatch):
    """Le helper peut ouvrir une fenêtre système ; on abandonne proprement."""
    def faux_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 15)

    monkeypatch.setattr(subprocess, "run", faux_run)
    assert credentials_for("https://github.com/a/b.git") is None


def test_missing_git_binary_does_not_propagate(monkeypatch):
    def faux_run(cmd, **kwargs):
        raise OSError("git introuvable")

    monkeypatch.setattr(subprocess, "run", faux_run)
    assert credentials_for("https://github.com/a/b.git") is None


def test_port_is_kept_in_the_query(monkeypatch):
    """Un hébergeur interne peut écouter sur un port non standard."""
    vues = {}

    def faux_run(cmd, **kwargs):
        vues["input"] = kwargs.get("input", "")
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", faux_run)
    credentials_for("https://gitlab.interne:8443/eq/projet.git")
    assert "host=gitlab.interne:8443" in vues["input"]
