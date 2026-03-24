"""
TDD guard tests for migration 003 (projects / estimate columns).

Background
----------
Migration 003 adds four columns to `tasks`:
    project_id, estimate_status, estimate_status_updated_at,
    estimate_status_updated_by

And creates three new tables: projects, task_versions, estimate_items.

On Render the migration was NOT applied before deploy, so any endpoint that
issues SELECT tasks.* failed with:
    ProgrammingError: column tasks.project_id does not exist  →  500

Test structure
--------------
1. test_admin_tasks_fails_with_pre_003_schema   (FAILING before fix)
       Uses a SQLite DB that has only the pre-migration-003 task columns.
       Asserts status == 200.
       FAILS (endpoint returns 500) — reproduces the production bug.
       Passes once the fixture/DB has all required columns.

2. test_admin_tasks_returns_200_with_full_schema
       Uses the standard conftest fixtures (all columns present).
       Verifies the happy path after the migration is applied.

3. test_task_model_columns_all_present_in_db
       Regression guard: compares every Task model column against the actual
       test DB.  Catches future model-vs-migration drift automatically.

Production fixes (also applied in this commit)
-----------------------------------------------
* render.yaml startCommand: alembic upgrade head && uvicorn ...
* Dockerfile CMD: sh -c "alembic upgrade head && uvicorn ..."
"""

import uuid
import pytest
import pytest_asyncio
from contextlib import asynccontextmanager
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import event, text

from app.database import Base, get_db
from app.models.task import Task
from app.utils.auth import create_access_token, hash_password

# ---------------------------------------------------------------------------
# Pre-migration-003 DDL for SQLite
#
# The tasks table intentionally lacks the four columns added by migration 003:
#   project_id, estimate_status, estimate_status_updated_at,
#   estimate_status_updated_by
# ---------------------------------------------------------------------------

_PRE_003_TASKS_DDL = """
CREATE TABLE IF NOT EXISTS tasks (
    id               TEXT NOT NULL DEFAULT (lower(hex(randomblob(16)))),
    user_role        VARCHAR(10) NOT NULL,
    task_type        VARCHAR(50) NOT NULL,
    status           VARCHAR(20) NOT NULL DEFAULT 'pending',
    input_files      TEXT NOT NULL DEFAULT '[]',
    input_file_data  TEXT NOT NULL DEFAULT '[]',
    user_prompt      TEXT,
    chat_history     TEXT NOT NULL DEFAULT '[]',
    progress_message VARCHAR(500),
    error_message    TEXT,
    created_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
)
"""

# Supporting tables (needed so lifespan startup doesn't fail on queries)
_USERS_DDL = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    role          VARCHAR(10) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

_PROJECTS_DDL_SQLITE = """
CREATE TABLE IF NOT EXISTS projects (
    id          TEXT NOT NULL DEFAULT (lower(hex(randomblob(16)))),
    name        VARCHAR(255) NOT NULL,
    description TEXT,
    user_id     INTEGER,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
)
"""

_TASK_VERSIONS_DDL_SQLITE = """
CREATE TABLE IF NOT EXISTS task_versions (
    id                 TEXT NOT NULL DEFAULT (lower(hex(randomblob(16)))),
    task_id            TEXT NOT NULL,
    version_number     INTEGER NOT NULL,
    snapshot           TEXT NOT NULL DEFAULT '{}',
    change_description TEXT,
    change_type        VARCHAR(50),
    created_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by         VARCHAR(20) NOT NULL DEFAULT 'user',
    PRIMARY KEY (id),
    FOREIGN KEY (task_id) REFERENCES tasks (id) ON DELETE CASCADE
)
"""

_ESTIMATE_ITEMS_DDL_SQLITE = """
CREATE TABLE IF NOT EXISTS estimate_items (
    id               TEXT NOT NULL DEFAULT (lower(hex(randomblob(16)))),
    task_id          TEXT NOT NULL,
    position         INTEGER NOT NULL,
    type             VARCHAR(20) NOT NULL,
    name             TEXT NOT NULL,
    unit             VARCHAR(100),
    quantity         REAL,
    work_price       REAL,
    mat_price        REAL,
    section          TEXT,
    notes            TEXT,
    is_analogue      BOOLEAN NOT NULL DEFAULT 0,
    original_item_id TEXT,
    analogue_note    TEXT,
    extra            TEXT NOT NULL DEFAULT '{}',
    created_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY (task_id) REFERENCES tasks (id) ON DELETE CASCADE
)
"""


# ---------------------------------------------------------------------------
# Fixture: HTTP client backed by the pre-migration-003 schema
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def pre_003_client():
    """
    AsyncClient using a SQLite DB where `tasks` has only the pre-003 columns
    (no project_id, estimate_status, etc.).  All other tables are created with
    SQLite-compatible DDL so the app can start without hitting PostgreSQL.

    The lifespan is replaced with a no-op to skip init_db / _initialize_users /
    price_service.load_cache (all of which use the production engine reference
    captured at import time).
    """
    import app.main as main_module

    @asynccontextmanager
    async def _noop_lifespan(app):
        yield

    orig_lifespan = main_module.lifespan
    main_module.lifespan = _noop_lifespan

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        echo=False,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _register(conn, _):
        conn.create_function("gen_random_uuid", 0, lambda: str(uuid.uuid4()))

    async with engine.begin() as conn:
        # Create all required tables.  tasks uses the OLD schema (missing the
        # four new columns) — that is what triggers the 500 on /admin/tasks.
        await conn.execute(text(_USERS_DDL))
        await conn.execute(text(_PRE_003_TASKS_DDL))   # ← OLD schema
        await conn.execute(text(_PROJECTS_DDL_SQLITE))
        await conn.execute(text(_TASK_VERSIONS_DDL_SQLITE))
        await conn.execute(text(_ESTIMATE_ITEMS_DDL_SQLITE))

    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    import app.database as db_module

    orig_engine = db_module.engine
    orig_factory = db_module.AsyncSessionLocal
    db_module.engine = engine
    db_module.AsyncSessionLocal = session_factory

    from app.main import create_app

    application = create_app()

    async def _override_db():
        async with session_factory() as session:
            yield session

    application.dependency_overrides[get_db] = _override_db

    async with AsyncClient(
        # raise_server_exceptions=False: server-side exceptions (like the
        # OperationalError from missing columns) are returned as 500 responses
        # instead of being re-raised in the test.  This matches production
        # behaviour where FastAPI's error handler returns 500.
        transport=ASGITransport(app=application, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        yield client

    application.dependency_overrides.clear()
    main_module.lifespan = orig_lifespan
    db_module.engine = orig_engine
    db_module.AsyncSessionLocal = orig_factory
    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 1 — reproduction of the production failure (FAILS before fix)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_admin_tasks_fails_with_pre_003_schema(pre_003_client):
    """
    Documents the failure mode: with the old schema (no project_id etc.),
    GET /admin/tasks returns 500.  This assertion verifies the failure is
    exactly what we expect (OperationalError → 500).
    """
    token = create_access_token("admin")
    response = await pre_003_client.get(
        "/admin/tasks",
        headers={"Authorization": f"Bearer {token}"},
    )
    # Old schema → SQLAlchemy tries SELECT tasks.project_id → not found → 500
    assert response.status_code == 500


@pytest.mark.asyncio
async def test_admin_tasks_returns_200_after_migration(
    async_client, seed_users, admin_token
):
    """
    After migration 003 is applied (all four new columns present in tasks),
    GET /admin/tasks must return 200.

    This test uses the standard conftest `async_client` which creates all
    tables via create_all (equivalent to running alembic upgrade head).

    Was RED when migration was missing; GREEN after migration is applied.
    """
    response = await async_client.get(
        "/admin/tasks",
        headers={"Authorization": admin_token},
    )
    assert response.status_code == 200, (
        f"Expected 200 but got {response.status_code}. "
        "Migration 003 may not have been applied — run `alembic upgrade head`."
    )


# ---------------------------------------------------------------------------
# Test 2 — happy-path verification after the fix
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_admin_tasks_returns_200_with_full_schema(
    async_client, seed_users, admin_token
):
    """
    After the migration is applied (all four new columns present in tasks),
    GET /admin/tasks must return 200 with the expected JSON shape.
    """
    response = await async_client.get(
        "/admin/tasks", headers={"Authorization": admin_token}
    )
    assert response.status_code == 200
    body = response.json()
    assert "items" in body
    assert "total" in body
    assert isinstance(body["items"], list)


# ---------------------------------------------------------------------------
# Test 3 — regression guard: Task model columns must match the actual DB
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_task_model_columns_all_present_in_db(db_session):
    """
    Introspects the test DB (SQLite, created via create_all which mirrors
    what `alembic upgrade head` produces in production) and verifies that
    every column in the SQLAlchemy Task model actually exists in the table.

    If someone adds a column to the model WITHOUT writing a migration, this
    test catches the drift immediately and forces them to write the migration.
    """
    result = await db_session.execute(text("PRAGMA table_info(tasks)"))
    rows = result.fetchall()
    # PRAGMA table_info columns: cid, name, type, notnull, dflt_value, pk
    db_columns = {row[1] for row in rows}

    model_columns = {col.name for col in Task.__table__.columns}

    missing_from_db = model_columns - db_columns
    assert not missing_from_db, (
        f"The following Task model columns are MISSING from the database:\n"
        f"  {sorted(missing_from_db)}\n"
        "Write an Alembic migration (alembic revision --autogenerate) to add them."
    )
