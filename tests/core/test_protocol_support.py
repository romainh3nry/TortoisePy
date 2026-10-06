"""libgit2 peut être compilé sans SSH : le dire clairement.

Signalé par l'utilisateur sur une installation **Windows** : toute
commande réseau répondait « Unsupported URL protocol in git provider ».
Le message vient de libgit2, pas de l'application, et il ne dit ni quel
protocole manque, ni quoi faire.

La cause : les roues pygit2 pour Windows sont fréquemment publiées sans
libssh2, là où celles de macOS et Linux l'embarquent. Un remote en
`git@…` est alors injoignable, quels que soient les identifiants.

On vérifie donc le support AVANT de tenter la connexion, et on nomme la
sortie : passer le remote en HTTPS, qui est toujours compilé.
"""

from __future__ import annotations

import pytest

from tortoisepy.core.protocols import (
    ProtocolUnavailable,
    check_url_supported,
    protocol_of,
)


# --- reconnaissance du protocole ----------------------------------------


@pytest.mark.parametrize(
    "url, attendu",
    [
        ("git@github.com:org/repo.git", "ssh"),
        ("ssh://git@gitlab.example.com:2222/org/repo.git", "ssh"),
        ("https://github.com/org/repo.git", "https"),
        ("http://interne.example.com/repo.git", "https"),
        ("/chemin/local/repo.git", "local"),
        ("file:///chemin/local/repo.git", "local"),
        ("C:\\depots\\repo.git", "local"),
    ],
)
def test_the_protocol_is_recognised(url, attendu):
    """Un chemin Windows est local, pas une URL à protocole inconnu."""
    assert protocol_of(url) == attendu


# --- vérification du support --------------------------------------------


def test_a_supported_url_passes(monkeypatch):
    """Le cas courant ne doit rien coûter ni rien dire."""
    from tortoisepy.core import protocols

    monkeypatch.setattr(protocols, "_supporte", lambda nom: True)
    check_url_supported("git@github.com:org/repo.git")   # ne lève pas


def test_an_unsupported_ssh_url_is_refused(monkeypatch):
    """L'assertion centrale : le défaut signalé sur Windows."""
    from tortoisepy.core import protocols

    monkeypatch.setattr(protocols, "_supporte", lambda nom: nom != "ssh")

    with pytest.raises(ProtocolUnavailable) as leve:
        check_url_supported("git@github.com:org/repo.git")

    message = str(leve.value)
    assert "SSH" in message, f"le protocole manquant doit être nommé : {message}"
    assert "HTTPS" in message, (
        f"la sortie de secours doit être indiquée : {message}"
    )


def test_the_message_names_the_remote(monkeypatch):
    """Sans l'URL, l'utilisateur ne sait pas quel remote changer."""
    from tortoisepy.core import protocols

    monkeypatch.setattr(protocols, "_supporte", lambda nom: False)

    with pytest.raises(ProtocolUnavailable) as leve:
        check_url_supported("git@gitlab.example.com:equipe/vti.git")

    assert "gitlab.example.com" in str(leve.value)


def test_an_unsupported_https_url_is_refused(monkeypatch):
    """HTTPS manquant est plus rare, mais le message ne doit pas mentir.

    Le piège : conseiller « utilisez HTTPS » alors que c'est justement
    HTTPS qui manque. Vérifié, car l'implémentation naïve propose
    toujours la même sortie.
    """
    from tortoisepy.core import protocols

    monkeypatch.setattr(protocols, "_supporte", lambda nom: nom != "https")

    with pytest.raises(ProtocolUnavailable) as leve:
        check_url_supported("https://github.com/org/repo.git")

    message = str(leve.value)
    assert "HTTPS" in message
    assert "set-url origin https://" not in message, (
        "le message conseille HTTPS alors que c'est HTTPS qui manque"
    )


def test_a_local_path_needs_no_protocol(monkeypatch):
    """Un dépôt local ne traverse aucun réseau : rien à vérifier.

    Même si libgit2 était compilé sans HTTPS ni SSH, un remote local
    resterait utilisable — refuser ici bloquerait un cas qui marche.
    """
    from tortoisepy.core import protocols

    monkeypatch.setattr(protocols, "_supporte", lambda nom: False)

    check_url_supported("/chemin/local/repo.git")     # ne lève pas
    check_url_supported("file:///chemin/repo.git")    # ne lève pas


def test_an_unknown_protocol_is_not_refused(monkeypatch):
    """Un schéma exotique (`git://`) doit passer à libgit2, qui tranchera.

    Refuser nous-mêmes ce que nous ne savons pas classer ajouterait un
    faux négatif là où libgit2 sait peut-être faire.
    """
    from tortoisepy.core import protocols

    monkeypatch.setattr(protocols, "_supporte", lambda nom: False)
    check_url_supported("git://ancien.example.com/repo.git")  # ne lève pas


# --- état réel de l'installation ----------------------------------------


def test_the_real_installation_is_inspected(monkeypatch):
    """`_supporte` doit interroger pygit2, pas rendre une valeur figée.

    Sans cela, la vérification serait décorative : elle passerait
    partout, y compris là où le protocole manque — exactement le défaut
    qu'elle corrige.

    Trouvé par mutation : comparer à l'état RÉEL de cette machine ne
    prouve rien, puisque HTTPS et SSH y sont tous deux compilés et qu'un
    `return True` constant donnerait le même résultat. On simule donc une
    libgit2 amputée, seul cas qui sépare les deux implémentations.
    """
    import pygit2

    from tortoisepy.core.protocols import _supporte

    # L'état réel d'abord : la fonction doit le refléter.
    assert _supporte("https") == bool(
        pygit2.features & pygit2.enums.Feature.HTTPS
    )

    # Puis une installation SANS SSH, comme celle de l'utilisateur.
    sans_ssh = pygit2.features & ~pygit2.enums.Feature.SSH
    monkeypatch.setattr(pygit2, "features", sans_ssh)

    assert _supporte("ssh") is False, (
        "`_supporte` ne lit pas réellement les drapeaux de pygit2"
    )
    assert _supporte("https") is True, (
        "HTTPS reste compilé : ne pas le refuser au passage"
    )


# --- message rendu à l'utilisateur --------------------------------------


def test_the_message_reaches_the_user_unprefixed(monkeypatch, tmp_path):
    """`guarded` ne doit pas préfixer ce message de son nom de classe.

    « ProtocolUnavailable: SSH n'est pas disponible… » ferait passer un
    détail d'implémentation devant une phrase écrite pour être lue. Le
    cas général garde le préfixe, utile devant une erreur inattendue.
    """
    import subprocess

    import pygit2

    from tortoisepy.core import protocols
    from tortoisepy.core.operations import fetch_remote

    monkeypatch.setattr(protocols, "_supporte", lambda nom: nom != "ssh")

    w = tmp_path / "w"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(w)], check=True,
        capture_output=True,
    )
    env = {
        "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
        "PATH": "/usr/bin:/bin",
    }
    (w / "a.txt").write_text("a\n")
    for args in (["add", "."], ["commit", "-qm", "base"],
                 ["remote", "add", "origin",
                  "git@gitlab.example.com:equipe/vti.git"]):
        subprocess.run(
            ["git", "-C", str(w), *args], check=True, capture_output=True,
            env=env,
        )

    resultat = fetch_remote(pygit2.Repository(str(w)))

    assert not resultat.success
    assert resultat.git_error.startswith("SSH n'est pas disponible"), (
        f"message préfixé ou absent : {resultat.git_error!r}"
    )


def test_an_unexpected_error_keeps_its_class_name():
    """Le cas général ne change pas : nommer la classe aide au diagnostic."""
    from tortoisepy.core.results import guarded

    @guarded("Essai")
    def casse():
        raise TypeError("mauvais argument")

    assert casse().git_error == "TypeError: mauvais argument"
