# tests/fixtures/builder.py
"""Construction de dépôts Git de test.

Utilise pygit2 directement plutôt que des sous-processus git : plus rapide,
et cohérent avec ce que le code testé manipule.
"""

from __future__ import annotations

from pathlib import Path

import pygit2


class RepoBuilder:
    """Construit un dépôt de test. Chaque méthode retourne self (chaînable)."""

    def __init__(self, path: Path):
        self.repo = pygit2.init_repository(str(path), bare=False, initial_head="master")
        self.signature = pygit2.Signature("Test", "test@example.com", 0, 0)
        self._counter = 0

    def commit(self, message: str, parents: list[str] | None = None) -> str:
        """Crée un commit avec un contenu de fichier unique. Retourne son OID.

        Les commits sont créés **détachés** (`ref=None`), puis la branche
        courante est déplacée explicitement. C'est nécessaire pour les
        racines multiples : écrire un commit sans parent sur une branche
        qui en a déjà une fait échouer libgit2 avec « current tip is not
        the first parent » (vérifié).

        `parents=None` enchaîne sur HEAD ; `parents=[]` crée une racine.
        """
        self._counter += 1
        blob = self.repo.create_blob(f"content {self._counter}\n".encode())
        builder = self.repo.TreeBuilder()
        builder.insert(f"file{self._counter}.txt", blob, pygit2.GIT_FILEMODE_BLOB)
        tree = builder.write()

        chain_from_head = parents is None
        if chain_from_head:
            try:
                parents = [str(self.repo.head.target)]
            except (pygit2.GitError, KeyError):
                parents = []

        oid = self.repo.create_commit(
            None,  # commit détaché : la ref est posée ensuite
            self.signature,
            self.signature,
            message,
            tree,
            [pygit2.Oid(hex=p) if isinstance(p, str) else p for p in parents],
        )

        if chain_from_head:
            self._advance_head(oid)

        return str(oid)

    def _advance_head(self, oid) -> None:
        """Fait pointer la branche courante sur `oid`, en la créant au besoin."""
        try:
            name = self.repo.head.name  # ex. "refs/heads/master"
            self.repo.references[name].set_target(oid)
        except (pygit2.GitError, KeyError):
            # Premier commit : la branche n'existe pas encore.
            self.repo.create_reference("refs/heads/master", oid)

    def branch(self, name: str, oid: str | None = None) -> RepoBuilder:
        """Crée la branche, ou la déplace si elle existe déjà.

        `master` existe dès le premier `commit()` sans parents explicites :
        sans ce `force`, toute fixture qui repositionne `master` échoue avec
        `AlreadyExistsError` (vérifié).
        """
        target = oid or str(self.repo.head.target)
        target_oid = pygit2.Oid(hex=target) if isinstance(target, str) else target
        ref_name = f"refs/heads/{name}"

        if ref_name in self.repo.references:
            # set_target fonctionne même sur la branche courante, là où
            # create_branch(force=True) refuse : « cannot force update
            # branch as it is the current HEAD » (vérifié).
            self.repo.references[ref_name].set_target(target_oid)
        else:
            self.repo.create_branch(name, self.repo.get(target_oid))
        return self

    def checkout(self, name: str) -> RepoBuilder:
        self.repo.checkout(f"refs/heads/{name}")
        return self

    def tag_lightweight(self, name: str, oid: str) -> RepoBuilder:
        self.repo.create_reference(f"refs/tags/{name}", oid)
        return self

    def tag_annotated(self, name: str, oid: str) -> RepoBuilder:
        self.repo.create_tag(
            name, oid, pygit2.GIT_OBJECT_COMMIT, self.signature, f"tag {name}"
        )
        return self

    def remote_ref(self, remote: str, branch: str, oid: str) -> RepoBuilder:
        """Crée une ref de suivi distant sans réseau."""
        self.repo.create_reference(f"refs/remotes/{remote}/{branch}", oid)
        return self
