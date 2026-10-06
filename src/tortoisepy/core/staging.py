"""Commiter une partie des changements d'un fichier — `git add -p`.

Demandé par l'utilisateur, et annoncé par le README comme « the biggest
gap » : commiter un fichier entier force à mélanger deux changements sans
rapport, ou à sortir au terminal — ce qui annule l'intérêt de
l'application.

Le principe tient en trois lignes : on part de la version **HEAD** du
fichier, on applique uniquement les hunks retenus, et le résultat devient
le contenu commité. Les hunks écartés restent dans l'arbre de travail,
non commités.

**Rien n'est écrit** (§7.0) : ni l'index de l'utilisateur, ni les refs,
ni le fichier sur disque. `commit_selection` bâtit déjà son arbre sur un
index temporaire en mémoire, donc le contenu composé n'a qu'à lui être
fourni — aucun index partiel ne touche le disque.

Aucune dépendance à Qt : `ui/` appelle ces fonctions, jamais pygit2
directement.
"""

from __future__ import annotations

import pygit2

from tortoisepy.core.changes import DiffHunk


def compose_partial_content(
    repo: pygit2.Repository, path: str, hunks: tuple[DiffHunk, ...]
) -> str:
    """Contenu du fichier avec **seulement** ces hunks appliqués.

    Part de la version HEAD et remplace, pour chaque hunk retenu, les
    lignes qu'il vise par celles qu'il propose. Un hunk écarté laisse
    donc la version HEAD à cet endroit.

    Lève `ValueError` si le fichier est absent de HEAD : un fichier non
    suivi n'a pas de version d'origine d'où partir, et rendre un contenu
    partiel tromperait. L'interface garde alors le tout-ou-rien.
    """
    origine = _lignes_de_head(repo, path)

    # Les hunks sont appliqués de la FIN vers le DÉBUT : chacun remplace
    # un nombre de lignes différent de celui qu'il insère, et traiter
    # dans l'ordre naturel décalerait les positions de tous les suivants.
    # Un fichier corrompu en silence serait le résultat.
    #
    # L'ordre d'arrivée n'est pas garanti — l'interface les donne dans
    # l'ordre d'affichage, mais rien ne l'impose — d'où le tri explicite.
    ordonnes = sorted(hunks, key=lambda h: h.old_start, reverse=True)

    resultat = list(origine)
    for hunk in ordonnes:
        debut = max(hunk.old_start - 1, 0)
        fin = debut + hunk.old_lines
        resultat[debut:fin] = _lignes_apres(hunk)

    return "".join(resultat)


def _lignes_de_head(repo: pygit2.Repository, path: str) -> list[str]:
    """Les lignes du fichier dans HEAD, sauts de ligne compris.

    `splitlines(keepends=True)` plutôt que `split("\\n")` : il préserve
    l'absence de saut de ligne final, que git signale explicitement et
    qu'il ne faut pas inventer.
    """
    try:
        arbre = repo.revparse_single("HEAD").peel(pygit2.Tree)
        entree = arbre[path]
    except (KeyError, pygit2.GitError, ValueError) as erreur:
        raise ValueError(
            f"« {path} » est absent de HEAD : pas de version d'origine "
            "d'où partir"
        ) from erreur

    blob = repo.get(entree.id)
    if blob is None:
        raise ValueError(f"« {path} » : contenu illisible dans HEAD")

    return blob.data.decode("utf-8", errors="replace").splitlines(
        keepends=True
    )


def _lignes_apres(hunk: DiffHunk) -> list[str]:
    """Les lignes que ce hunk laisse en place : contexte et ajouts.

    Une ligne supprimée (`-`) disparaît ; une ligne `=` ne porte que la
    mention « No newline at end of file », qui n'appartient pas au
    contenu.

    `raw` et non `content` : ce dernier est rogné pour l'affichage, ce
    qui ferait gagner un saut de ligne à un fichier qui n'en a pas.
    """
    return [
        ligne.raw or (ligne.content + "\n")
        for ligne in hunk.lines
        if ligne.origin in (" ", "+")
    ]
