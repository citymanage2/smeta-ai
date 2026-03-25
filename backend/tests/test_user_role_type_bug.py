"""
Regression tests for:
  operator does not exist: user_role = character varying

Root cause: users.role column was created as PostgreSQL enum type 'user_role'
by an old deployment that had sa.Enum('user', 'admin', name='user_role') in
the User model.  init_db() uses create_all() which never alters existing
columns, so after the model was updated to String(10) the production DB
column remained an enum — causing startup to fail on:

    select(User).where(User.role == role)   ← 'role' is varchar param,
                                              column type is enum 'user_role'

Fix: alembic migration 003 must ALTER the column to VARCHAR and DROP the
obsolete enum type.
"""

import os
import pytest
import pytest_asyncio
from sqlalchemy import Column, Integer, select
from sqlalchemy import Enum as SAEnum
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


# ---------------------------------------------------------------------------
# Minimal "broken" model that reproduces the old schema
# ---------------------------------------------------------------------------

class _BrokenBase(DeclarativeBase):
    pass


class _UserBrokenEnum(_BrokenBase):
    """Replica of the User model as it was before the fix: role is Enum."""
    __tablename__ = "users_broken_enum"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role: Mapped[str] = mapped_column(
        SAEnum("user", "admin", name="user_role"), nullable=False
    )


# ---------------------------------------------------------------------------
# Test 1 (FAILS until migration 003 is created)
# ---------------------------------------------------------------------------

def test_migration_003_fixes_user_role_enum():
    """
    Migration 003 must exist to convert users.role from the 'user_role' enum
    type to VARCHAR(10) on the production Render PostgreSQL database.

    This test FAILS until the migration file is present.
    """
    migrations_dir = os.path.join(
        os.path.dirname(__file__), "..", "alembic", "versions"
    )
    fix_files = sorted(f for f in os.listdir(migrations_dir) if f.startswith("003"))
    assert fix_files, (
        "Migration 003 is missing. "
        "It must ALTER TABLE users ALTER COLUMN role TYPE VARCHAR(10) "
        "and DROP TYPE IF EXISTS user_role. "
        "Production error: operator does not exist: user_role = character varying"
    )

    # Also verify the migration body does the right thing
    migration_path = os.path.join(migrations_dir, fix_files[0])
    with open(migration_path) as f:
        content = f.read()

    assert "users" in content, "Migration must reference the 'users' table"
    assert "role" in content, "Migration must alter the 'role' column"
    assert "user_role" in content, "Migration must handle the 'user_role' enum type"


# ---------------------------------------------------------------------------
# Test 2 — query against the broken schema (SQLite: passes; PG: would crash)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_broken_enum_schema_documents_production_failure():
    """
    Creates the old broken schema (Enum column) in SQLite, inserts a user,
    and runs the exact startup query.

    On SQLite this succeeds (no strict type enforcement).
    On PostgreSQL with the old schema it raises:
      operator does not exist: user_role = character varying

    The purpose is to document the broken state and confirm that
    test_user_role_filter_works_with_varchar covers the fixed path.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(_BrokenBase.metadata.create_all)

    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as db:
        db.add(_UserBrokenEnum(role="admin"))
        await db.commit()

        # This query works in SQLite but fails on PostgreSQL with enum column.
        result = await db.execute(
            select(_UserBrokenEnum).where(_UserBrokenEnum.role == "admin")
        )
        user = result.scalar_one_or_none()
        assert user is not None

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 3 — query against the CORRECT schema (must pass after fix)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_user_role_filter_works_with_varchar(db_session: AsyncSession):
    """
    Regression: select(User).where(User.role == role) must work when
    users.role is VARCHAR(10), not a PostgreSQL enum type.

    This is the exact query executed in main.py _initialize_users() on startup.
    """
    from app.models.user import User
    from app.utils.auth import hash_password

    db_session.add(User(role="user", password_hash=hash_password("user123")))
    db_session.add(User(role="admin", password_hash=hash_password("admin123")))
    await db_session.flush()

    for role in ("user", "admin"):
        result = await db_session.execute(select(User).where(User.role == role))
        found = result.scalar_one_or_none()
        assert found is not None, f"Query returned None for role='{role}'"
        assert found.role == role
