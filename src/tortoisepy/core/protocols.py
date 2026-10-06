"""Quels protocoles réseau cette installation de libgit2 sait parler.

Signalé par l'utilisateur sur une installation **Windows** : toute
commande réseau répondait « Unsupported URL protocol in git provider ».
Le message vient de libgit2 et ne dit ni quel protocole manque, ni quoi
faire — il laisse croire à un défaut de l'application ou du dépôt.

La cause : libgit2 est compilé avec ou sans SSH selon la roue pygit2
installée. Celles de Windows sont fréquemment publiées sans libssh2, là
où macOS et Linux l'embarquent. Un remote en `git@…` est alors
injoignable, quels que soient les identifiants.

Ce module le vérifie **avant** la connexion, pour nommer le protocole
manquant et la sortie de secours.

Aucune dépendance à Qt : `ui/` appelle ces fonctions, jamais pygit2
directement.
"""

from __future__ import annotations

import pygit2

from tortoisepy.core.results import WrittenMessage


class ProtocolUnavailable(WrittenMessage):
    """Le protocole de cette URL n'est pas compilé dans libgit2.

    Hérite de `WrittenMessage` pour que `guarded` affiche son texte tel
    quel : il est déjà rédigé pour l'utilisateur, et le préfixer du nom
    de la classe n'ajouterait qu'un détail d'implémentation.
    """


def protocol_of(url: str) -> str:
    """« ssh », « https », « local », ou « inconnu ».

    Un chemin Windows (« C:\\dépôts\\repo.git ») est local : le prendre
    pour une URL à protocole inconnu le ferait refuser à tort.
    """
    if url.startswith(("https://", "http://")):
        return "https"
    if url.startswith(("ssh://", "git@")):
        return "ssh"
    if url.startswith("file://"):
        return "local"

    # Chemin absolu POSIX, relatif, ou lettre de lecteur Windows.
    if url.startswith(("/", ".")) or (
        len(url) > 2 and url[1] == ":" and url[2] in "\\/"
    ):
        return "local"

    return "inconnu"


def check_url_supported(url: str) -> None:
    """Lève `ProtocolUnavailable` si libgit2 ne sait pas parler ce protocole.

    Ne dit rien dans le cas courant : la vérification est une poignée de
    comparaisons, et le silence est la réponse attendue.

    Un protocole **inconnu** passe : refuser ce que nous ne savons pas
    classer ajouterait un faux négatif là où libgit2 sait peut-être
    faire. Un chemin **local** passe aussi — il ne traverse aucun réseau,
    donc il reste utilisable même sans HTTPS ni SSH compilés.
    """
    protocole = protocol_of(url)
    if protocole in ("local", "inconnu"):
        return
    if _supporte(protocole):
        return

    raise ProtocolUnavailable(_message(protocole, url))


def _message(protocole: str, url: str) -> str:
    """Nomme le protocole manquant, le remote, et la sortie.

    L'URL figure dans le message : sans elle, l'utilisateur ne sait pas
    quel remote changer quand le dépôt en a plusieurs.
    """
    if protocole == "ssh":
        return (
            f"SSH n'est pas disponible dans cette installation de libgit2, "
            f"et le remote « {url} » l'exige.\n\n"
            "Cela arrive avec les paquets pygit2 de Windows, publiés sans "
            "libssh2. Deux sorties : passer le remote en HTTPS "
            "(git remote set-url origin https://…), ou installer un "
            "pygit2 compilé avec SSH."
        )

    # HTTPS manquant est plus rare : surtout ne pas conseiller HTTPS.
    return (
        f"HTTPS n'est pas disponible dans cette installation de libgit2, "
        f"et le remote « {url} » l'exige.\n\n"
        "Il faut un pygit2 compilé avec le support HTTPS, ou un remote "
        "en SSH (git remote set-url origin git@…)."
    )


def _supporte(protocole: str) -> bool:
    """Ce protocole est-il compilé dans la libgit2 chargée ?

    Interroge pygit2 à chaque appel plutôt que de figer le résultat : une
    constante calculée à l'import serait invisible aux tests et ne
    vaudrait pas mieux qu'une supposition.
    """
    drapeaux = {
        "https": pygit2.enums.Feature.HTTPS,
        "ssh": pygit2.enums.Feature.SSH,
    }
    drapeau = drapeaux.get(protocole)
    if drapeau is None:
        return True
    return bool(pygit2.features & drapeau)
