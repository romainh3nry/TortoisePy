"""Modèle du menu contextuel — §7.3, §7.4, §7.5.

Ce module ne construit aucun widget : il décide **quelles entrées existent
et lesquelles sont actives**, en fonction du type de nœud et de l'état du
dépôt. Le widget Qt traduit ensuite ce modèle. Séparer les deux rend la
logique testable sans interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tortoisepy.core.model import DisplayNode, NodeKind, RefType
from tortoisepy.core.operations import PROTECTED_BRANCHES, local_name_for
from tortoisepy.core.state import RepositoryState


@dataclass(frozen=True)
class MenuEntry:
    label: str
    action: str | None = None
    enabled: bool = True
    children: tuple["MenuEntry", ...] = field(default_factory=tuple)

    needs_confirmation: bool = False
    """Indication documentaire — **elle ne déclenche rien**.

    La vraie porte est `dialogs.confirmation_for`, interrogée par
    `actions.execute_action` (ou par l'appelant, pour les actions que la
    fenêtre principale pilote elle-même). Ce champ n'est lu par aucun
    consommateur.

    Il a coûté cher une fois : « Drop stash » le portait, un test
    l'affirmait, et pourtant le stash était détruit même quand
    l'utilisateur refusait — `confirmation_for` n'avait pas de branche
    `drop_stash` (trouvé en revue finale de la phase 11). **Poser ce
    drapeau ne protège rien** : il faut ajouter la branche correspondante
    et la tester au niveau de `execute_action`.
    """

    branch: str | None = None
    """Branche visée, quand le nœud en porte plusieurs.

    Plusieurs branches peuvent partager un commit, donc un même nœud du
    graphe. Sans cette précision, l'action retombait sur la première de la
    liste et les autres étaient inatteignables (signalé par l'utilisateur).
    `None` laisse l'action choisir elle-même, comme avant.
    """

    @property
    def is_separator(self) -> bool:
        return self.action == "separator"


SEPARATOR = MenuEntry(label="—", action="separator")


def build_menu_model(
    nodes: tuple[DisplayNode, ...], state: RepositoryState
) -> tuple[MenuEntry, ...]:
    """Menu correspondant à la sélection courante.

    Une sélection vide ne produit aucun menu ; deux nœuds activent les
    actions de comparaison (§7.4).
    """
    if not nodes:
        return ()

    if len(nodes) >= 2:
        return _comparison_menu(nodes)

    return _single_node_menu(nodes[0], state)


def _comparison_menu(nodes: tuple[DisplayNode, ...]) -> tuple[MenuEntry, ...]:
    """§7.4 : menu de deux nœuds sélectionnés."""
    return (
        MenuEntry("Compare revisions", "compare_revisions"),
        MenuEntry("Show log of differences", "show_log_of_differences"),
        SEPARATOR,
        MenuEntry("Copy SHA-1 to clipboard", "copy_hash"),
    )


def _single_node_menu(
    node: DisplayNode, state: RepositoryState
) -> tuple[MenuEntry, ...]:
    """§7.3 : menu hiérarchisé d'un nœud."""
    busy = state.operation_in_progress is not None
    dirty = state.has_unstaged_changes or state.has_staged_changes

    is_branch = _has_local_branch(node)
    is_current = _is_current(node, state)
    actionable = node.kind is not NodeKind.STASH and not busy

    # Une branche AUTRE que la courante sur ce nœud reste une cible
    # légitime : plusieurs branches partagent souvent un commit, et
    # `is_current` vaut alors vrai pour tout le nœud — ce qui grisait
    # checkout et merge même vers les voisines (signalé par l'utilisateur).
    others = [b for b in _local_branches(node) if b != state.head_branch]

    # Une distante est une cible légitime depuis la phase 21 : le checkout
    # crée la locale du même nom. Un nœud qui n'en portait aucune avait
    # l'entrée grisée, obligeant à passer par « Branch from revision… ».
    distantes_utiles = [
        d for d in _remote_branches(node)
        if local_name_for(d) != state.head_branch
    ]
    can_checkout = bool(others or distantes_utiles) and not busy
    can_merge = bool(others) and not busy
    can_modify_branch = is_branch and not busy

    entries: list[MenuEntry] = [
        _branch_entry(
            "Switch / Checkout to revision",
            "checkout_branch",
            node,
            enabled=can_checkout,
            needs_confirmation=dirty,
            exclude=state.head_branch,
            include_remotes=True,
        ),
        SEPARATOR,
        MenuEntry(
            "Create",
            children=(
                MenuEntry("Branch from revision…", "create_branch", enabled=actionable),
                MenuEntry("Tag from revision…", "create_tag", enabled=actionable),
            ),
        ),
        MenuEntry(
            "Stash changes…",
            "stash_changes",
            # Grisé sur un arbre propre : `repo.stash()` lèverait
            # « nothing to stash » (vérifié), et proposer une action qui
            # échouera toujours n'apprend rien.
            enabled=dirty and not busy,
        ),
        MenuEntry(
            "Integrate",
            children=(
                _branch_entry(
                    "Merge…",
                    "merge_branch",
                    node,
                    enabled=can_merge,
                    needs_confirmation=dirty,
                    exclude=state.head_branch,
                ),
                MenuEntry(
                    "Rebase…",
                    "rebase_branch",
                    # C'est la branche COURANTE qu'on rebase : l'entrée
                    # vaut pour elle, où que l'on ait cliqué.
                    enabled=not busy and state.head_branch is not None,
                    needs_confirmation=dirty,
                ),
                MenuEntry(
                    "Cherry Pick this commit…",
                    "cherry_pick",
                    enabled=actionable,
                    needs_confirmation=dirty,
                ),
            ),
        ),
        MenuEntry(
            "Undo",
            children=(
                MenuEntry(
                    "Reset (current branch) to this…",
                    "reset_to",
                    enabled=actionable,
                    needs_confirmation=True,
                ),
                MenuEntry(
                    "Revert change by this commit…",
                    "revert_commit",
                    enabled=actionable,
                    needs_confirmation=True,
                ),
            ),
        ),
        MenuEntry(
            "Remote",
            children=(
                MenuEntry(
                    "Fetch",
                    "fetch_remote",
                    # Fetch ne touche ni à l'arbre de travail ni aux
                    # branches locales : il reste actif même pendant un
                    # merge en cours, et sur un nœud tag ou stash.
                    enabled=True,
                ),
                MenuEntry(
                    "Push",
                    "push_branch",
                    # Grisé hors de la branche courante : pousser une autre
                    # branche demanderait un checkout, qui existe déjà (§9).
                    enabled=is_current,
                ),
                MenuEntry(
                    "Push (force with lease)…",
                    "force_push_branch",
                    # Comme Push : seulement la branche courante. Toujours
                    # visible (D16) — la faire apparaître selon l'état
                    # dérouterait, et supposerait un fetch récent.
                    enabled=is_current,
                    needs_confirmation=True,
                ),
                MenuEntry(
                    "Pull",
                    "pull_branch",
                    # Comme Push : seulement sur la branche courante ;
                    # récupérer dans une autre demanderait un checkout, qui
                    # existe déjà.
                    enabled=is_current,
                ),
            ),
        ),
        MenuEntry(
            "Branch",
            children=(
                _branch_entry(
                    "Rename branch…",
                    "rename_branch",
                    node,
                    enabled=can_modify_branch,
                ),
                _branch_entry(
                    "Delete branch",
                    "delete_branch",
                    node,
                    enabled=can_modify_branch and not is_current,
                    needs_confirmation=True,
                    # Supprimer la branche courante est refusé de toute
                    # façon : ne pas la proposer.
                    exclude=state.head_branch,
                ),
                _remote_branch_entry(node, enabled=not busy),
            ),
        ),
    ]

    # Des conflits SANS opération en cours existent : vérifié, un index
    # peut les porter alors que `.git/MERGE_HEAD` a disparu (fermeture
    # brutale, nettoyage partiel). L'utilisateur était alors bloqué — le
    # checkout refusait, et le menu ne proposait aucune sortie.
    if busy or state.has_conflicts:
        entries.append(SEPARATOR)
        if state.has_conflicts:
            # Fermer la fenêtre de conflits ne les résout pas, et rien
            # d'autre ne sait la rouvrir : les deux seuls appels sont des
            # gestionnaires d'échec, sur le moment. Sans cette entrée,
            # l'utilisateur qui la ferme n'a plus aucun chemin vers ses
            # propres conflits (§6 promet qu'elle se rouvre).
            entries.append(
                MenuEntry(
                    "Resolve conflicts…",
                    "open_conflicts",
                    enabled=True,
                )
            )
        # « Abort None » serait du charabia : sans opération nommée, on
        # parle de ce que l'utilisateur voit — ses conflits.
        libelle = (
            f"Abort {state.operation_in_progress}"
            if state.operation_in_progress
            else "Discard conflicts and reset"
        )
        entries.append(
            MenuEntry(
                libelle,
                "abort_operation",
                enabled=True,
                needs_confirmation=True,
            )
        )

    if node.kind is NodeKind.STASH:
        entries.append(SEPARATOR)
        entries.extend((
            MenuEntry("Apply stash", "apply_stash", enabled=not busy),
            MenuEntry("Pop stash", "pop_stash", enabled=not busy),
            MenuEntry(
                "Drop stash",
                "drop_stash",
                enabled=not busy,
                # Le seul des trois qui détruit du travail sans le rendre.
                needs_confirmation=True,
            ),
        ))

    entries.append(SEPARATOR)
    entries.append(
        MenuEntry(
            "Commit…",
            "open_commit",
            # Toujours actif : c'est une fenêtre de consultation, même
            # sans modification en cours.
            enabled=True,
        )
    )
    entries.append(SEPARATOR)
    entries.append(MenuEntry("Show log", "show_log"))
    entries.append(MenuEntry("Copy SHA-1 to clipboard", "copy_hash"))

    return tuple(entries)


def _local_branches(node: DisplayNode) -> tuple[str, ...]:
    """Noms des branches locales portées par ce nœud, triés."""
    return tuple(
        sorted(
            ref.name
            for ref in node.refs
            if ref.type is RefType.LOCAL_BRANCH
        )
    )


def _remote_branches(node: DisplayNode) -> tuple[str, ...]:
    """Branches distantes portées par ce nœud, `remote/branche` en entier.

    **Indépendant des branches locales.** Une première version partait
    de `_local_branches` et gardait celles ayant une jumelle distante :
    l'entrée restait alors grisée sur un nœud ne portant que
    `origin/test-nav`, sans copie locale (signalé par l'utilisateur) —
    or c'est le cas le plus utile, celui où l'on nettoie une branche du
    serveur qu'on ne suit pas.

    Le nom complet est conservé : `origin/x` et `upstream/x` sont deux
    cibles différentes, et l'action doit savoir à quel serveur parler.
    """
    return tuple(
        sorted(
            r.name
            for r in node.refs
            if r.type is RefType.REMOTE_BRANCH
            and "/" in r.name
            and not r.name.endswith("/HEAD")
            # `main`, `master`, `develop` : le cœur les refuse de toute
            # façon, et proposer une entrée vouée à l'échec n'apprend
            # rien. Git ne protège que la branche par défaut du serveur.
            and r.name.split("/", 1)[1] not in PROTECTED_BRANCHES
        )
    )


def _remote_branch_entry(node: DisplayNode, *, enabled: bool) -> MenuEntry:
    """« Delete remote branch… », une entrée ou un sous-menu.

    Deux entrées distinctes plutôt qu'une case à cocher : supprimer sur
    le serveur est le seul des deux gestes qu'on ne peut pas défaire
    seul. Grisée si le nœud ne porte aucune branche distante — il n'y
    aurait alors rien à supprimer là-bas.
    """
    distantes = _remote_branches(node)
    label = "Delete remote branch…"

    if len(distantes) <= 1:
        return MenuEntry(
            label,
            "delete_remote_branch",
            enabled=enabled and bool(distantes),
            needs_confirmation=True,
            branch=distantes[0] if distantes else None,
        )

    # Plusieurs serveurs, ou plusieurs branches : chacune est nommée,
    # sinon l'action retomberait sur la première et les autres seraient
    # inatteignables — le défaut déjà corrigé pour les branches locales.
    return MenuEntry(
        label,
        enabled=enabled,
        children=tuple(
            MenuEntry(
                nom,
                "delete_remote_branch",
                enabled=enabled,
                needs_confirmation=True,
                branch=nom,
            )
            for nom in distantes
        ),
    )


def _branch_entry(
    label: str,
    action: str,
    node: DisplayNode,
    *,
    enabled: bool,
    needs_confirmation: bool = False,
    exclude: str | None = None,
    only: set[str] | None = None,
    include_remotes: bool = False,
) -> MenuEntry:
    """Entrée simple, ou sous-menu quand le nœud porte plusieurs branches.

    Plusieurs branches partagent souvent un commit — juste après un
    `git branch`, par exemple. Le nœud est alors unique et l'action
    retombait sur la première de la liste : les autres étaient
    inatteignables (signalé par l'utilisateur). Avec un sous-menu, chaque
    branche est nommée, comme dans TortoiseGit.

    `exclude` retire la branche courante des propositions : on ne bascule
    pas sur la branche où l'on est déjà.

    `only` restreint les propositions à un sous-ensemble : supprimer une
    branche distante n'a de sens que pour celles qui existent vraiment
    sur un serveur, et un sous-menu proposant les autres mènerait à un
    échec garanti.

    `include_remotes` ajoute les branches distantes aux cibles (phase 21).
    Réservé au checkout : basculer sur `origin/x` crée la locale `x`, ce
    qui a du sens, alors que fusionner ou supprimer une distante n'a pas
    la même signification et garde son chemin propre.
    """
    branches = [b for b in _local_branches(node) if b != exclude]
    if only is not None:
        branches = [b for b in branches if b in only]

    if include_remotes:
        # Une distante dont la locale est déjà proposée ferait doublon :
        # « test-branch » et « origin/test-branch » mènent au même endroit.
        deja = set(branches)
        branches += [
            distante
            for distante in _remote_branches(node)
            if local_name_for(distante) not in deja
            and local_name_for(distante) != exclude
        ]

    if len(branches) <= 1:
        return MenuEntry(
            label,
            action,
            enabled=enabled,
            needs_confirmation=needs_confirmation,
            branch=branches[0] if branches else None,
        )

    return MenuEntry(
        label,
        enabled=enabled,
        children=tuple(
            MenuEntry(
                name,
                action,
                enabled=enabled,
                needs_confirmation=needs_confirmation,
                branch=name,
            )
            for name in branches
        ),
    )


def _has_local_branch(node: DisplayNode) -> bool:
    return any(ref.type is RefType.LOCAL_BRANCH for ref in node.refs)


def _is_current(node: DisplayNode, state: RepositoryState) -> bool:
    """Le nœud porte-t-il la branche courante ?"""
    if any(ref.type is RefType.HEAD for ref in node.refs):
        return True
    if state.head_branch is None:
        return False
    return any(
        ref.type is RefType.LOCAL_BRANCH and ref.name == state.head_branch
        for ref in node.refs
    )
