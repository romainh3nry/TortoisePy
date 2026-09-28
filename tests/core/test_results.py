import pygit2
import pytest

from tortoisepy.core.results import OperationResult, failed, guarded, succeeded


def test_is_frozen():
    r = succeeded("Test")
    with pytest.raises(AttributeError):
        r.success = False


def test_succeeded_marks_the_repository_changed_by_default():
    r = succeeded("Checkout de master")
    assert r.success is True
    assert r.repository_changed is True
    assert r.git_error is None
    assert r.summary == "Checkout de master"


def test_succeeded_without_change():
    """Copier un hash réussit sans rien modifier."""
    r = succeeded("Hash copié", repository_changed=False)
    assert r.success is True
    assert r.repository_changed is False


def test_failed_leaves_the_repository_untouched_by_default():
    r = failed("Merge", "1 conflict prevents checkout")
    assert r.success is False
    assert r.repository_changed is False
    assert r.git_error == "1 conflict prevents checkout"


def test_failure_can_still_have_changed_the_repository():
    """§7.6 : un merge en conflit échoue MAIS a modifié l'index."""
    r = failed("Merge", "conflits", repository_changed=True)
    assert r.success is False
    assert r.repository_changed is True


def test_guarded_passes_through_a_successful_result():
    @guarded("Opération")
    def op():
        return succeeded("Opération réussie")

    assert op().success is True


def test_guarded_converts_a_pygit2_error():
    @guarded("Merge de feature")
    def op():
        raise pygit2.GitError("1 conflict prevents checkout")

    result = op()
    assert result.success is False
    assert result.summary == "Merge de feature"
    assert "conflict" in result.git_error


def test_guarded_never_raises():
    @guarded("Opération")
    def op():
        raise KeyError("ref introuvable")

    result = op()  # ne doit pas lever
    assert result.success is False


def test_guarded_reports_change_on_error_when_declared():
    """Une opération interactive modifie le dépôt avant d'échouer."""
    @guarded("Merge", changed_on_error=True)
    def op():
        raise pygit2.GitError("conflits")

    result = op()
    assert result.success is False
    assert result.repository_changed is True


def test_guarded_lets_through_a_result_object_unchanged():
    """Si l'opération retourne déjà un résultat, il est préservé tel quel."""
    original = failed("Déjà échoué", "raison", repository_changed=True)

    @guarded("Ignoré")
    def op():
        return original

    assert op() is original


def test_guarded_preserves_function_metadata():
    @guarded("Opération")
    def nommee():
        """Docstring."""
        return succeeded("ok")

    assert nommee.__name__ == "nommee"
    assert nommee.__doc__ == "Docstring."


def test_guarded_catches_unexpected_exception_types():
    """Une TypeError de pygit2 ne doit pas remonter jusqu'à l'UI.

    Une version antérieure n'attrapait que GitError, KeyError, ValueError et
    OSError : tout autre type traversait le décorateur, contre la règle de
    §7.6 (« aucune opération ne lève »).
    """
    @guarded("Opération")
    def op():
        raise TypeError("mauvais type d'argument")

    result = op()
    assert result.success is False
    assert "TypeError" in result.git_error


def test_guarded_still_lets_keyboard_interrupt_through():
    """Interrompre le programme doit rester possible."""
    @guarded("Opération")
    def op():
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        op()
