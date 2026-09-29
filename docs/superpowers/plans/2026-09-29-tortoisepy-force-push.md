# Force push (with lease) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettre de pousser une branche réécrite par un rebase, sans jamais
écraser le travail d'un tiers.

**Architecture:** `push_branch` gagne un paramètre `force_with_lease`. Le bail
est vérifié **avant** tout envoi, en comparant `refs/remotes/<remote>/<branche>`
à ce que le serveur annonce via `remote.connect()` + `list_heads()`. S'il est
rompu, on n'envoie rien. Le refspec passe de `refs/heads/X:refs/heads/X` à
`+refs/heads/X:refs/heads/X`.

**Tech Stack:** Python 3.13, pygit2 1.20.1, PySide6 6.11.2, pytest.

**Spec:** `docs/superpowers/specs/2026-09-29-tortoisepy-force-push-design.md`

## Global Constraints

- **Ne jamais lancer de commande git sur CE dépôt** (add, commit, branch,
  checkout, stash, push, reset). L'utilisateur gère git lui-même. `git` dans
  un dépôt jetable sous `tmp_path` est attendu et normal.
- **Ne pas modifier** `src/tortoisepy/ui/theme.py`, `src/tortoisepy/layout/**`,
  `src/tortoisepy/ui/graph_items.py` — le rendu du graphe est validé.
- `src/tortoisepy/core/**` n'importe jamais Qt (`tests/test_architecture.py`).
- **§7.0** : l'application n'écrit dans un dépôt QUE sur action explicite de
  l'utilisateur dans l'interface. `remote.connect()`/`list_heads()` n'écrivent
  pas — vérifié par empreinte `.git`.
- **`--force` inconditionnel n'existe nulle part.** Aucun chemin ne produit un
  refspec `+` sans contrôle de bail préalable (D15).
- Commentaires et docstrings **en français**, expliquant le *pourquoi* ;
  libellés visibles **en anglais**.
- Le push normal reste inchangé : les tests de la phase 7 restent verts.

## Review Focus

1. **Un remote sans la branche** (première publication) — `list_heads()` ne
   renvoie aucune ref pour elle. Le bail doit alors être considéré comme
   **tenu** (rien à écraser), pas rompu.
2. **Pas de ref de suivi locale** (`refs/remotes/origin/X` absent) — on ne sait
   rien du serveur, donc **refuser** : c'est exactement le cas que
   `--force-with-lease` protège.
3. **Remote injoignable** — `connect()` lève. Le message doit parler de
   connexion, pas de bail rompu.
4. **Remote `pushurl`-only** — la phase 7 a vérifié un segfault libgit2 ; le
   refus doit intervenir **avant** `connect()` comme avant `push()`.
5. **Le serveur refuse quand même** — `push_update_reference` signale un rejet
   même après un bail tenu (protection de branche côté serveur). Ne pas
   annoncer un succès.

---

### Task 1: Le bail — vérifier sans écrire

**Files:**
- Modify: `src/tortoisepy/core/operations.py`
- Test: `tests/core/test_push_operation.py`

**Interfaces:**
- Produces: `lease_holds(repo, branch, remote_name) -> tuple[bool, str | None]`
  — `(True, None)` si le bail tient, `(False, raison)` sinon.

**Vérifié (ne pas redécouvrir) :** `remote.ls_remotes` **n'existe pas** sur
pygit2 1.20 ; c'est `remote.connect(callbacks=...)` puis `remote.list_heads()`.
Les objets rendus sont des `RemoteHead` avec les attributs `.name` et `.oid`
— **non indexables** (`t["name"]` lève `TypeError`).

**Piège vérifié :** `push_negotiation` ne sert à rien ici. Son `dst` est la
valeur que la ref *deviendra* (notre nouveau commit), pas la position du
serveur. Un contrôle bâti dessus refuserait **tous** les push après rebase.

- [ ] **Step 1: Écrire les tests**

```python
# à ajouter dans tests/core/test_push_operation.py


def _serveur_et_clone(tmp_path, nom="moi"):
    """Un dépôt nu et un clone qui a poussé « main »."""
    bare = tmp_path / "serveur.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], capture_output=True)
    work = tmp_path / nom
    subprocess.run(["git", "clone", "-q", str(bare), str(work)], capture_output=True)
    (work / "f.txt").write_text("a\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "base")
    run_git(work, "push", "-q", "origin", "HEAD")
    return bare, work


def test_the_lease_holds_when_nobody_moved_the_branch(tmp_path):
    from tortoisepy.core.operations import lease_holds

    _, work = _serveur_et_clone(tmp_path)
    tient, raison = lease_holds(pygit2.Repository(str(work)), "main", "origin")
    assert tient is True
    assert raison is None


def test_the_lease_breaks_when_someone_else_pushed(tmp_path):
    """Le cœur de --force-with-lease : ne pas écraser un inconnu."""
    from tortoisepy.core.operations import lease_holds

    bare, work = _serveur_et_clone(tmp_path)
    autre = tmp_path / "collegue"
    subprocess.run(["git", "clone", "-q", str(bare), str(autre)], capture_output=True)
    (autre / "g.txt").write_text("collegue\n")
    run_git(autre, "add", ".")
    run_git(autre, "commit", "-q", "-m", "travail du collegue")
    run_git(autre, "push", "-q", "origin", "HEAD")

    tient, raison = lease_holds(pygit2.Repository(str(work)), "main", "origin")
    assert tient is False
    assert "fetch" in (raison or "").lower()


def test_the_lease_holds_for_a_branch_the_server_does_not_have(tmp_path):
    """Review Focus 1 : une première publication n'écrase rien."""
    from tortoisepy.core.operations import lease_holds

    _, work = _serveur_et_clone(tmp_path)
    run_git(work, "checkout", "-q", "-b", "toute-neuve")
    tient, _ = lease_holds(pygit2.Repository(str(work)), "toute-neuve", "origin")
    assert tient is True


def test_the_lease_breaks_without_a_tracking_ref(tmp_path):
    """Review Focus 2 : ne rien savoir du serveur, c'est ne pas forcer."""
    from tortoisepy.core.operations import lease_holds

    _, work = _serveur_et_clone(tmp_path)
    repo = pygit2.Repository(str(work))
    # Le serveur a la branche, mais nous n'avons aucune ref de suivi.
    repo.references.delete("refs/remotes/origin/main")
    tient, raison = lease_holds(pygit2.Repository(str(work)), "main", "origin")
    assert tient is False
    assert raison


def test_checking_the_lease_writes_nothing(tmp_path):
    """§7.0 : interroger le serveur ne touche pas au dépôt."""
    import hashlib

    from tortoisepy.core.operations import lease_holds

    _, work = _serveur_et_clone(tmp_path)

    def empreinte():
        h = hashlib.sha256()
        for racine, _, fichiers in os.walk(os.path.join(str(work), ".git")):
            for f in sorted(fichiers):
                p = os.path.join(racine, f)
                h.update(p.encode())
                try:
                    h.update(str(os.stat(p).st_mtime_ns).encode())
                except OSError:
                    pass
        return h.hexdigest()

    avant = empreinte()
    lease_holds(pygit2.Repository(str(work)), "main", "origin")
    assert empreinte() == avant
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/core/test_push_operation.py -q -k lease`
Expected: FAIL — `lease_holds` n'existe pas.

- [ ] **Step 3: Implémenter**

Dans `operations.py`, à côté de `_default_remote` :

```python
def lease_holds(
    repo: pygit2.Repository, branch: str, remote_name: str
) -> tuple[bool, str | None]:
    """Le serveur est-il encore là où nous le croyons ?

    C'est tout `--force-with-lease` : on n'écrase que ce qu'on a déjà vu.
    Le « bail », c'est `refs/remotes/<remote>/<branche>`, écrit par le
    dernier fetch ; on le compare à ce que le serveur annonce vraiment.

    **Lecture seule** (§7.0) : `connect()` + `list_heads()` n'écrivent
    rien dans `.git` — vérifié par empreinte.
    """
    remote = repo.remotes[remote_name]

    try:
        remote.connect(callbacks=PushCallbacks(remote.url or "", None))
        annoncees = {t.name: t.oid for t in remote.list_heads()}
    except (pygit2.GitError, KeyError, ValueError, OSError) as erreur:
        return False, f"cannot reach '{remote_name}': {erreur}"

    distant = annoncees.get(f"refs/heads/{branch}")
    if distant is None:
        # Le serveur ne connaît pas cette branche : rien à écraser, donc
        # rien à protéger. C'est une première publication.
        return True, None

    suivi = f"refs/remotes/{remote_name}/{branch}"
    if suivi not in repo.references:
        # Le serveur l'a, nous n'en savons rien : c'est précisément le
        # cas que le bail existe pour refuser.
        return False, (
            f"no local knowledge of '{remote_name}/{branch}' — fetch first"
        )

    attendu = repo.references[suivi].target
    if str(distant) != str(attendu):
        return False, (
            f"'{remote_name}/{branch}' has moved since your last fetch — "
            "someone else pushed. Fetch before forcing."
        )
    return True, None
```

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/core/test_push_operation.py -q`
Expected: PASS.

- [ ] **Step 5: Signaler les fichiers prêts** — ne commite pas.

---

### Task 2: `push_branch(force_with_lease=...)`

**Files:**
- Modify: `src/tortoisepy/core/operations.py`
- Test: `tests/core/test_push_operation.py`

**Interfaces:**
- Consumes: `lease_holds` (tâche 1)
- Produces: `push_branch(repo, remote_name=None, on_progress=None,
  force_with_lease=False)`

**Vérifié :** le push normal après un rebase échoue bien avec
`cannot push non-fastforwardable reference` — c'est le défaut que cette
tâche répare.

- [ ] **Step 1: Écrire les tests**

```python
# à ajouter dans tests/core/test_push_operation.py


def test_a_normal_push_is_still_not_forced(tmp_path):
    """Garde-fou D15 : aucun chemin ne force sans qu'on le demande."""
    from tortoisepy.core.operations import push_branch

    _, work = _serveur_et_clone(tmp_path)
    repo = pygit2.Repository(str(work))
    envoyes = []
    vrai_push = pygit2.Remote.push

    def espion(self, specs, **kwargs):
        envoyes.extend(specs)
        return vrai_push(self, specs, **kwargs)

    pygit2.Remote.push = espion
    try:
        push_branch(repo)
    finally:
        pygit2.Remote.push = vrai_push

    assert envoyes, "aucun refspec envoyé"
    assert not any(s.startswith("+") for s in envoyes), envoyes


def test_a_forced_push_lands_after_a_rebase(tmp_path):
    """La raison d'être de la phase : le push normal échouait ici."""
    from tortoisepy.core.operations import push_branch
    from tortoisepy.core.rebase import start_rebase

    bare, work = _serveur_et_clone(tmp_path)
    run_git(work, "checkout", "-q", "-b", "feature")
    (work / "g.txt").write_text("mon travail\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "mon travail")
    run_git(work, "push", "-q", "origin", "feature")

    run_git(work, "checkout", "-q", "main")
    (work / "h.txt").write_text("avance\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "-m", "avance main")
    run_git(work, "push", "-q", "origin", "main")
    run_git(work, "checkout", "-q", "feature")

    start_rebase(pygit2.Repository(str(work)), "main")

    refuse = push_branch(pygit2.Repository(str(work)))
    assert refuse.success is False, "le push normal devrait être rejeté"

    force = push_branch(pygit2.Repository(str(work)), force_with_lease=True)
    assert force.success is True, force.git_error

    serveur = pygit2.Repository(str(bare))
    local = pygit2.Repository(str(work))
    assert str(serveur.references["refs/heads/feature"].target) == str(
        local.references["refs/heads/feature"].target
    )


def test_a_forced_push_refuses_to_erase_a_colleague(tmp_path):
    """L'assertion qui compte : son commit est toujours là."""
    from tortoisepy.core.operations import push_branch

    bare, work = _serveur_et_clone(tmp_path)
    autre = tmp_path / "collegue"
    subprocess.run(["git", "clone", "-q", str(bare), str(autre)], capture_output=True)
    (autre / "g.txt").write_text("collegue\n")
    run_git(autre, "add", ".")
    run_git(autre, "commit", "-q", "-m", "travail du collegue")
    run_git(autre, "push", "-q", "origin", "HEAD")
    attendu = str(pygit2.Repository(str(autre)).head.target)

    (work / "f.txt").write_text("reecrit\n")
    run_git(work, "add", ".")
    run_git(work, "commit", "-q", "--amend", "-m", "base reecrit")

    result = push_branch(pygit2.Repository(str(work)), force_with_lease=True)
    assert result.success is False
    assert "fetch" in (result.git_error or "").lower()

    serveur = pygit2.Repository(str(bare))
    assert str(serveur.references["refs/heads/main"].target) == attendu, (
        "le commit du collègue a été écrasé"
    )
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/core/test_push_operation.py -q -k forced`
Expected: FAIL — `push_branch` n'accepte pas `force_with_lease`.

- [ ] **Step 3: Implémenter**

Modifier la signature et le docstring :

```python
def push_branch(
    repo: pygit2.Repository,
    remote_name: str | None = None,
    on_progress=None,
    force_with_lease: bool = False,
) -> OperationResult:
    """Pousse la branche courante vers son remote.

    `force_with_lease` réécrit la branche distante, **mais seulement si
    elle est encore là où notre dernier fetch l'a vue** : on remplace son
    propre historique, jamais celui d'un autre. `--force` inconditionnel
    n'existe nulle part dans cette application (D15) — c'est lui, et non
    le forçage en soi, que la phase 7 excluait.

    Un rebase réécrit les commits : sans cela, la branche ne peut plus
    être poussée du tout (vérifié : « cannot push non-fastforwardable
    reference »).
    """
```

Juste **avant** `callbacks = PushCallbacks(...)`, et donc après les refus
existants sur `pushurl`-only :

```python
    if force_with_lease:
        tient, raison = lease_holds(repo, branch, remote.name)
        if not tient:
            # Rien n'est envoyé : le refus arrive avant le moindre octet.
            return failed("Push", raison or "lease broken",
                          repository_changed=False)
```

Et le refspec :

```python
    # Le « + » est la marque du forçage. Il n'est posé qu'ici, après que
    # le bail a été vérifié : aucun chemin ne force à l'aveugle.
    prefixe = "+" if force_with_lease else ""
    remote.push(
        [f"{prefixe}refs/heads/{branch}:refs/heads/{branch}"],
        callbacks=callbacks,
    )
```

- [ ] **Step 4: Vérifier le succès**

Run: `.venv/bin/pytest tests/core/test_push_operation.py tests/core/test_push_state.py -q`
Expected: PASS.

- [ ] **Step 5: Signaler les fichiers prêts** — ne commite pas.

---

### Task 3: L'entrée de menu et le lancement

**Files:**
- Modify: `src/tortoisepy/ui/context_menu.py`
- Modify: `src/tortoisepy/ui/actions.py`
- Modify: `src/tortoisepy/ui/main_window.py`
- Test: `tests/ui/test_context_menu.py`, `tests/ui/test_main_window.py`

**Interfaces:**
- Consumes: `push_branch(..., force_with_lease=True)` (tâche 2)
- Produces: entrée « Push (force with lease)… », `MainWindow._start_push(force=True)`

**Vérifié :** `_start_push` (main_window.py:648) gère déjà confirmation,
arrière-plan, progression, identifiants et second essai. Il prend `force` en
paramètre plutôt que d'être dupliqué.

- [ ] **Step 1: Écrire les tests**

```python
# à ajouter dans tests/ui/test_context_menu.py


def test_force_push_is_offered_on_the_current_branch():
    entries = build_menu_model((_multi_branch_node(),), _on_main())
    entree = _find(entries, "Push (force with lease)…")
    assert entree is not None
    assert entree.action == "force_push_branch"
    assert entree.enabled is True


def test_force_push_is_greyed_out_elsewhere():
    """Comme Push : forcer une autre branche demanderait un checkout."""
    state = RepositoryState(
        head_oid="b" * 40, head_branch="autre", detached=False,
        has_unstaged_changes=False, has_staged_changes=False,
        has_conflicts=False, operation_in_progress=None, conflicted_paths=(),
    )
    entries = build_menu_model((_multi_branch_node(),), state)
    entree = _find(entries, "Push (force with lease)…")
    assert entree is not None
    assert entree.enabled is False
```

```python
# à ajouter dans tests/ui/test_main_window.py


def test_force_push_is_confirmed_before_anything_happens(window, monkeypatch):
    """§7.0 : refuser la confirmation n'envoie rien."""
    from tortoisepy.ui import main_window as module

    appels = []
    monkeypatch.setattr(module, "confirm", lambda *a, **k: False)
    monkeypatch.setattr(
        module.operations, "push_branch",
        lambda *a, **k: appels.append(k) or None,
    )
    window._start_push(force=True)
    assert not appels, "rien ne doit partir sans confirmation"


def test_the_confirmation_says_the_history_will_be_rewritten(window, monkeypatch):
    from tortoisepy.ui import main_window as module

    vus = []
    monkeypatch.setattr(
        module, "confirm", lambda parent, request: vus.append(request) or False
    )
    window._start_push(force=True)
    assert vus, "aucune confirmation demandée"
    texte = (vus[0].title + vus[0].message).lower()
    assert "force" in texte
    assert vus[0].destructive is True
```

- [ ] **Step 2: Vérifier l'échec**

Run: `.venv/bin/pytest tests/ui/test_context_menu.py tests/ui/test_main_window.py -q -k force`
Expected: FAIL — l'entrée et le paramètre n'existent pas.

- [ ] **Step 3: Menu et action**

Dans `context_menu.py`, juste après l'entrée « Push » :

```python
                MenuEntry(
                    "Push (force with lease)…",
                    "force_push_branch",
                    # Comme Push : seulement la branche courante. Toujours
                    # visible (D16) — la faire apparaître selon l'état
                    # dérouterait, et supposerait un fetch récent.
                    enabled=is_current,
                    needs_confirmation=True,
                ),
```

Dans `actions.py` :

```python
def _force_push_branch(ctx: ActionContext) -> OperationResult | None:
    """La fenêtre principale s'en charge : push en arrière-plan."""
    return None
```

et `"force_push_branch": _force_push_branch,` dans le registre.

- [ ] **Step 4: Lancement (`main_window.py`)**

Interception dans `_run_action`, à côté de `push_branch` :

```python
        if action == "force_push_branch":
            self._start_push(force=True)
            return
```

`_start_push` prend le paramètre et adapte **la confirmation** et **l'appel** :

```python
    def _start_push(self, confirmed: bool = False, force: bool = False) -> None:
```

Confirmation, à la place du `ConfirmationRequest` actuel :

```python
        if not confirmed:
            if force:
                request = ConfirmationRequest(
                    title="Push (force with lease)",
                    message=(
                        f"git push --force-with-lease {state.remote_name} "
                        f"{state.branch}\n\n"
                        f"This REPLACES the history of {state.remote_name}/"
                        f"{state.branch} with yours. It is refused if anyone "
                        "else pushed since your last fetch."
                    ),
                    destructive=True,
                )
            else:
                request = ConfirmationRequest(
                    title="Push",
                    message=(
                        f"git push {state.remote_name} {state.branch}\n\n"
                        f"{state.unpushed_count} commit(s) will be sent to the "
                        "shared server. This cannot be undone on your own."
                    ),
                    destructive=False,
                )
            if not confirm(self, request):
                return
```

L'appel, et le second essai après authentification :

```python
        worker = FetchWorker(
            lambda on_progress: operations.push_branch(
                self.repository,
                on_progress=on_progress,
                force_with_lease=force,
            )
        )
```

```python
        self._task.finished.connect(
            lambda result: self._on_push_finished(result, force)
        )
```

```python
    def _on_push_finished(self, result, force: bool = False) -> None:
        ...
        if _needs_authentication(result) and self._ask_and_store_credentials():
            self._start_push(confirmed=True, force=force)
            return
```

**Attention :** sans transmettre `force`, le second essai après saisie des
identifiants repartirait en push **normal** — et échouerait à nouveau.

- [ ] **Step 5: Vérifier le succès**

Run: `.venv/bin/pytest tests/ui/ -q`
Expected: PASS.

- [ ] **Step 6: Suite complète**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`
Expected: 830 + ~12 tests. **Deux échecs connus et sans rapport** :
`test_fetch_hides_the_bar_when_done` et `test_worker_reports_its_result`.

- [ ] **Step 7: Signaler les fichiers prêts** — ne commite pas. Donner le
décompte exact.

---

## Fin de phase 10

Une branche rebasée se pousse depuis le graphe, et le travail d'un tiers ne
peut pas être écrasé par ce chemin.

**Hors périmètre**, conformément à la spec §8 : `--force` inconditionnel,
forcer une autre branche que la courante, forcer plusieurs branches d'un coup,
et rattraper un bail rompu depuis l'interface.
