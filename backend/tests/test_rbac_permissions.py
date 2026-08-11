"""Unit-тесты матрицы прав (app/utils/permissions.py).

Чистая логика ролей/видимости, без БД и HTTP.
"""
import pytest

from app.models.project import Project
from app.models.task import Task
from app.utils import permissions as perm


def _user(role, sub=None):
    """JWT-payload как его видят зависимости (sub = owner_id строкой)."""
    return {"role": role, "sub": str(sub) if sub is not None else role}


# --- normalize_role / is_* ---

def test_normalize_role_legacy_and_unknown_map_to_pm():
    assert perm.normalize_role("user") == perm.ROLE_PM
    assert perm.normalize_role(None) == perm.ROLE_PM
    assert perm.normalize_role("garbage") == perm.ROLE_PM
    assert perm.normalize_role("admin") == perm.ROLE_ADMIN
    assert perm.normalize_role("head_of_sales") == perm.ROLE_SALES_HEAD
    assert perm.normalize_role("project_manager") == perm.ROLE_PM


def test_is_admin_and_is_manager():
    assert perm.is_admin("admin")
    assert not perm.is_admin("head_of_sales")
    assert perm.is_manager("admin")
    assert perm.is_manager("head_of_sales")
    assert not perm.is_manager("project_manager")
    assert not perm.is_manager("user")  # legacy → pm


def test_can_reassign_only_managers():
    assert perm.can_reassign("admin")
    assert perm.can_reassign("head_of_sales")
    assert not perm.can_reassign("project_manager")


# --- visibility_filter: списки без фильтра по владельцу ---

@pytest.mark.parametrize("role", ["admin", "head_of_sales", "project_manager", "user", None])
def test_visibility_filter_is_none_for_every_role(role):
    """Проекты и задачи общие: список не сужается ни для кого."""
    assert perm.visibility_filter(Project, _user(role, 2)) is None
    assert perm.visibility_filter(Task, _user(role, 3)) is None


def test_visibility_filter_none_without_uid():
    # legacy shared-токен без owner_id — тоже видит всё.
    assert perm.visibility_filter(Task, {"role": "project_manager", "sub": "project_manager"}) is None


# --- can_access / can_edit: доступ к чужому ресурсу ---

@pytest.mark.parametrize("role", ["admin", "head_of_sales", "project_manager", "user", None])
def test_any_role_accesses_any_resource(role):
    u = _user(role, 2)
    assert perm.can_access(999, u)      # чужой владелец
    assert perm.can_access(None, u)     # без владельца
    assert perm.can_access(2, u)        # свой


def test_pm_accesses_foreign_resource():
    """Раньше было главное ограничение: ПМ видел только своё. Теперь — всё."""
    pm = _user("project_manager", 7)
    assert perm.can_access(8, pm)
    assert perm.can_edit(8, pm)


def test_pm_without_uid_accesses_everything():
    u = {"role": "project_manager", "sub": "project_manager"}
    assert perm.can_access(7, u)
    assert perm.can_access(None, u)


def test_can_access_shared_visible_to_everyone():
    # общие (is_shared) ресурсы по-прежнему доступны — флаг ничего не сужает
    pm = _user("project_manager", 7)
    assert perm.can_access(999, pm, is_shared=True)
    assert perm.can_access(None, pm, is_shared=True)
    assert perm.can_access(999, pm, is_shared=False)


def test_can_edit_is_can_access():
    assert perm.can_edit is perm.can_access
