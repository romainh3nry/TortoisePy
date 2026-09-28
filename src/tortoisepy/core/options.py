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

    Par défaut : branches locales, branches distantes, tags et HEAD. Les
    nœuds de jonction sans ref sont masqués (voir `show_junctions`).

    Les tags étaient masqués dans une version antérieure, sur l'hypothèse
    qu'ils saturaient le graphe. Mesuré : les masquer ne faisait passer un
    dépôt de 8281 à 7988 nœuds. La cause était ailleurs — les jonctions.
    """

    show_local_branches: bool = True
    show_remote_branches: bool = True
    show_tags: bool = True
    show_stashes: bool = True

    show_junctions: bool = False
    """Afficher les nœuds de jonction sans ref (merge-bases, divergences).

    Masqués par défaut : mesuré sur un dépôt réel de 518 nœuds, 234 étaient
    des jonctions — plus nombreuses que les refs elles-mêmes. Les retirer
    ramène le graphe à 284 nœuds en préservant TOUTES les refs (298/298) et
    sans déconnecter le graphe.

    Ce sont les points de merge-base et de divergence : utiles pour
    comprendre la topologie, encombrants pour lire les branches."""

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
