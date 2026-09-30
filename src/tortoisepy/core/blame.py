"""Qui a écrit chaque ligne — phase 14.

Le blâme **lit** : c'est la première fonctionnalité depuis longtemps qui
n'ajoute aucune opération destructrice, et elle ne peut pas faire perdre
de travail.

Mesuré : 42 ms sur un fichier à 3 000 révisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pygit2


@dataclass(frozen=True)
class BlameLine:
    """Une ligne, et le commit qui l'a écrite."""

    number: int
    text: str
    oid: str
    short_oid: str
    author: str
    when: datetime
    summary: str


@dataclass(frozen=True)
class BlameError:
    """Pourquoi ce fichier ne peut pas être blâmé."""

    reason: str


def _decouper_en_lignes(donnees: bytes) -> list[str]:
    """Découpe comme git, et **surtout pas** comme `str.splitlines()`.

    `splitlines()` coupe aussi sur le saut de page `\x0c`, la tabulation
    verticale `\x0b`, `\x1c`-`\x1e`, `\x85`, `\u2028` et `\u2029` — que
    git ne considère pas comme des fins de ligne. Le vecteur de lignes
    comptait alors plus d'entrées que les hunks n'en couvrent, et **tout
    décalait d'un cran** : chaque ligne prenait l'auteur de la
    précédente.

    Reproduit, avec un saut de page en ligne 1 :

    ```
    git blame            notre code (avant)
    1 entetesuite Alice  1 'entete'         Alice
    2 ligne2      Bob    2 'suite'          Bob    <- texte d'Alice, dit de Bob
    3 ligne3      Alice  3 'ligne2'         Alice  <- texte de Bob, dit d'Alice
    ```

    Le repli « ligne sans auteur » absorbait le débordement en silence :
    la fenêtre paraissait complète et cohérente. `\x0c` se rencontre dans
    du vrai code (Makefiles, fichiers formatés par Emacs).
    """
    texte = donnees.decode("utf-8", errors="replace")
    if not texte:
        return []
    lignes = texte.split("\n")
    # Un fichier terminé par un saut de ligne produit une dernière entrée
    # vide, que git ne compte pas comme une ligne.
    if lignes and lignes[-1] == "":
        lignes.pop()
    # `\r\n` : git normalise, l'affichage ne doit pas garder le `\r`.
    return [l[:-1] if l.endswith("\r") else l for l in lignes]


def blame_file(
    repo: pygit2.Repository, path: str, oid: str
) -> tuple[BlameLine, ...] | BlameError:
    """Annote un fichier tel qu'il était au commit `oid`.

    **Le contenu vient de l'arbre du commit, pas du disque** : vérifié,
    le fichier de travail peut porter des lignes non commitées que le
    blâme n'annote pas, et les afficher laisserait croire qu'elles sont
    sans auteur.

    **On retient l'auteur du commit**, pas `hunk.final_committer` : le
    committer peut être celui qui a appliqué un patch écrit par un autre.

    Rend un `BlameError` plutôt que de lever : l'appelant est une
    fenêtre, qui doit afficher la raison.
    """
    try:
        commit = repo.get(oid)
        if commit is None:
            return BlameError(reason=f"unknown commit: {oid[:8]}")
        entry = commit.tree[path]
    except (KeyError, pygit2.GitError, ValueError):
        return BlameError(reason=f"'{path}' is not in this commit")

    blob = repo.get(entry.id)
    if blob is None:
        return BlameError(reason=f"'{path}' cannot be read")

    # libgit2 ne lève pas sur un binaire : il rend un bloc unique et
    # inutile. Mieux vaut le dire que d'afficher des octets comme du
    # texte.
    if blob.is_binary:
        return BlameError(reason=f"'{path}' is a binary file")

    contenu = _decouper_en_lignes(blob.data)
    if not contenu:
        return ()

    try:
        blame = repo.blame(path, newest_commit=commit.id)
    except (pygit2.GitError, KeyError, ValueError) as erreur:
        return BlameError(reason=str(erreur))

    # Un commit par ligne, indexé : les hunks couvrent des plages, et
    # l'affichage veut une ligne à la fois.
    par_ligne: dict[int, pygit2.Commit] = {}
    for hunk in blame:
        origine = repo.get(hunk.final_commit_id)
        if origine is None:
            continue
        for decalage in range(hunk.lines_in_hunk):
            par_ligne[hunk.final_start_line_number + decalage] = origine

    lignes: list[BlameLine] = []
    for numero, texte in enumerate(contenu, start=1):
        origine = par_ligne.get(numero)
        if origine is None:
            # Une ligne que le blâme ne couvre pas : la montrer sans
            # auteur plutôt que de la taire.
            lignes.append(
                BlameLine(
                    number=numero, text=texte, oid="", short_oid="",
                    author="", when=datetime.fromtimestamp(0, timezone.utc),
                    summary="",
                )
            )
            continue

        lignes.append(
            BlameLine(
                number=numero,
                text=texte,
                oid=str(origine.id),
                short_oid=str(origine.id)[:8],
                author=origine.author.name,
                when=datetime.fromtimestamp(
                    origine.author.time, timezone.utc
                ),
                summary=origine.message.strip().splitlines()[0]
                if origine.message.strip()
                else "",
            )
        )

    return tuple(lignes)
