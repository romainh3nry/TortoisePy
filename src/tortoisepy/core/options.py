"""Filtrage des refs affichées.

Un dépôt professionnel accumule les tags : mesuré sur un dépôt réel, 413 des
710 refs étaient des tags de version. Chacun devient un nœud et tire sa
propre chaîne de jonctions — le graphe passe de quelques dizaines de nœuds
utiles à plusieurs milliers, et devient illisible.

Les filtres vivent ici, dans `core/`, et non dans `ui/` : ils changent le
graphe construit, pas seulement son rendu.
"""

from __future__ import annotations

from dataclasses import dataclass

from tortoisepy.core.model import Ref, RefType


@dataclass(frozen=True)
class GraphOptions:
    """Ce qui entre dans le graphe.

    Par défaut : branches locales, branches distantes et HEAD. Les tags sont
    masqués — ils sont nombreux et rarement structurants pour comprendre où
    en sont les branches.
    """

    show_local_branches: bool = True
    show_remote_branches: bool = True
    show_tags: bool = False
    show_stashes: bool = True

    def accepts(self, ref: Ref) -> bool:
        if ref.type is RefType.LOCAL_BRANCH:
            return self.show_local_branches
        if ref.type is RefType.REMOTE_BRANCH:
            return self.show_remote_branches
        if ref.type is RefType.TAG:
            return self.show_tags
        # HEAD est toujours conservé : sans lui, le nœud courant n'est plus
        # identifiable et le graphe perd son repère principal.
        return True

    def filter(self, refs: tuple[Ref, ...]) -> tuple[Ref, ...]:
        return tuple(ref for ref in refs if self.accepts(ref))
