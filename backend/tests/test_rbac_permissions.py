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


# --- visibility_filter ---

def test_visibility_filter_manager_is_none():
    assert perm.visibility_filter(Project, _user("admin", 2)) is None
    assert perm.visibility_filter(Task, _user("head_of_sales", 3)) is None


def test_visibility_filter_pm_scopes_to_owner():
    cond = perm.visibility_filter(Project, _user("project_manager", 5))
    # SQLAlchemy binary expression: owner_id == 5
    compiled = str(cond.compile(compile_kwargs={"literal_binds": True}))
    assert "owner_id" in compiled and "5" in compiled


def test_visibility_filter_pm_without_uid_sees_only_shared():
    # legacy shared-токен: uid None → видит только общие (is_shared).
    cond = perm.visibility_filter(Task, {"role": "project_manager", "sub": "project_manager"})
    compiled = str(cond.compile(compile_kwargs={"literal_binds": True})).lower()
    assert "is_shared" in compiled


def test_visibility_filter_pm_includes_shared():
    cond = perm.visibility_filter(Project, _user("project_manager", 5))
    compiled = str(cond.compile(compile_kwargs={"literal_binds": True})).lower()
    assert "owner_id" in compiled and "is_shared" in compiled


def test_can_access_shared_visible_to_everyone():
    # общий ресурс доступен любому ПМ, даже чужой owner_id
    pm = _user("project_manager", 7)
    assert perm.can_access(999, pm, is_shared=True)
    assert perm.can_access(None, pm, is_shared=True)
    # без флага — чужой недоступен
    assert not perm.can_access(999, pm, is_shared=False)


# --- can_access / can_edit ---

@pytest.mark.parametrize("role", ["admin", "head_of_sales"])
def test_manager_can_access_any(role):
    assert perm.can_access(999, _user(role, 2))
    assert perm.can_access(None, _user(role, 2))


def test_pm_accesses_only_own():
    u = _user("project_manager", 7)
    assert perm.can_access(7, u)
    assert not perm.can_access(8, u)
    assert not perm.can_access(None, u)


def test_pm_without_uid_accesses_nothing():
    u = {"role": "project_manager", "sub": "project_manager"}
    assert not perm.can_access(7, u)
    assert not perm.can_access(None, u)


def test_can_edit_is_can_access():
    assert perm.can_edit is perm.can_access
