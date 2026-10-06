"""Retenir les fenêtres filles sans les laisser s'accumuler.

Quatre listes et quatre méthodes `_forget_*` quasi identiques vivaient
dans `MainWindow`, qui atteignait 1999 lignes et 79 méthodes — le
fichier où le plus de régressions sont apparues. À cette taille, on ne
voit plus les interactions.

Le besoin est toujours le même, et double :

  - **retenir** la fenêtre, sans quoi le ramasse-miettes la détruit
    aussitôt ouverte (piège vécu plusieurs fois dans ce projet) ;
  - **l'oublier** une fois fermée, sans quoi la liste grossit sans fin
    au fil d'une session — chaque fenêtre morte gardant son
    `Repository`, son arbre de fichiers et sa vue de diff.

Aucune dépendance à pygit2 : c'est un détail d'interface.
"""

from __future__ import annotations

from typing import Iterator

import shiboken6


def still_alive(widget) -> bool:
    """Le widget Qt existe-t-il encore côté C++ ?

    Un wrapper Python peut survivre à l'objet C++ que Qt a détruit
    (`WA_DeleteOnClose`) : y toucher lève alors un `RuntimeError` de
    shiboken. `isValid` est le seul test fiable.
    """
    return shiboken6.isValid(widget)


class ChildWindows:
    """Les fenêtres filles ouvertes, retenues puis oubliées.

    Se parcourt et se mesure comme une liste, ce qui garde lisibles les
    appels existants (`if self._log_windows:`, `len(...)`).
    """

    def __init__(self) -> None:
        self._fenetres: list = []

    def add(self, window) -> None:
        """Retient la fenêtre et s'abonne à sa destruction.

        L'abonnement est posé ici plutôt que par l'appelant : l'oublier
        était justement l'erreur que cette classe doit rendre
        impossible.
        """
        destruction = getattr(window, "destroyed", None)
        if destruction is not None:
            destruction.connect(self.forget)
        self._fenetres.append(window)

    def forget(self, window=None) -> None:
        """Retire les fenêtres détruites, et `window` si elle est donnée.

        On ne vise pas `window` directement : son wrapper Python peut
        survivre à l'objet C++, et le toucher lèverait un `RuntimeError`
        de shiboken. On filtre donc sur la validité, ce qui reste
        correct même si le signal arrive deux fois.
        """
        self._fenetres = [
            candidate
            for candidate in self._fenetres
            if candidate is not window and still_alive(candidate)
        ]

    def last(self):
        """La dernière fenêtre ouverte, ou `None`.

        Le code appelant et les tests visent presque toujours celle-ci.
        """
        return self._fenetres[-1] if self._fenetres else None

    def __iter__(self) -> Iterator:
        return iter(self._fenetres)

    def __len__(self) -> int:
        return len(self._fenetres)

    def __getitem__(self, index):
        return self._fenetres[index]

    def __eq__(self, autre) -> bool:
        """Se compare à une liste, comme le faisait l'attribut d'avant.

        Quatre tests écrivaient `== []` avant l'extraction. Casser cette
        comparaison les aurait obligés à changer sans qu'aucun
        comportement ne bouge : un remaniement qui force à réécrire ses
        tests en dit long sur ce qu'il a vraiment déplacé.
        """
        if isinstance(autre, ChildWindows):
            return self._fenetres == autre._fenetres
        if isinstance(autre, list):
            return self._fenetres == autre
        return NotImplemented

    __hash__ = None   # mutable : ne doit pas servir de clé
