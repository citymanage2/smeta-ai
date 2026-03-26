"""
Integration tests: verify the actual PostgreSQL schema contains every table
and column that migrations 004–006 are supposed to create.

These tests connect to the real database via DATABASE_URL and inspect the
live schema. They will FAIL when alembic_version was stamped to 006 without
running the actual SQL (the 'stamp head' bug), and PASS after fix_production_db.py
resets the version and alembic upgrade head applies the missing migrations.

Skipped automatically when DATABASE_URL is not set (e.g., local dev with SQLite).
"""
import os
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection

DATABASE_URL = os.environ.get("DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL not set — skipping live schema tests",
)


# ---------------------------------------------------------------------------
# Shared async engine for all tests in this module
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="module")
async def pg_engine():
    engine = create_async_engine(DATABASE_URL, echo=False)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="module")
async def inspector(pg_engine):
    async with pg_engine.connect() as conn:
        insp = await conn.run_sync(lambda sync_conn: inspect(sync_conn))
        yield insp


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

async def get_table_names(conn: AsyncConnection) -> list[str]:
    return await conn.run_sync(lambda c: inspect(c).get_table_names())


async def get_column_names(conn: AsyncConnection, table: str) -> list[str]:
    return await conn.run_sync(
        lambda c: [col["name"] for col in inspect(c).get_columns(table)]
    )


# ---------------------------------------------------------------------------
# Tests: tables
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_projects_table_exists(pg_engine):
    """
    Migration 004 must create the 'projects' table.
    FAILS when DB was stamped to 006 without running migrations.
    """
    async with pg_engine.connect() as conn:
        tables = await get_table_names(conn)
    assert "projects" in tables, (
        "Table 'projects' does not exist. "
        "Likely cause: alembic_version was stamped to 006 without running "
        "migrations 004+. Run scripts/fix_production_db.py to repair."
    )


# ---------------------------------------------------------------------------
# Tests: columns on 'tasks'
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tasks_project_id_column_exists(pg_engine):
    """Migration 004 must add tasks.project_id (FK → projects.id)."""
    async with pg_engine.connect() as conn:
        cols = await get_column_names(conn, "tasks")
    assert "project_id" in cols, (
        "Column 'tasks.project_id' does not exist. Migration 004 not applied."
    )


@pytest.mark.asyncio
async def test_tasks_estimation_status_column_exists(pg_engine):
    """Migration 004 must add tasks.estimation_status."""
    async with pg_engine.connect() as conn:
        cols = await get_column_names(conn, "tasks")
    assert "estimation_status" in cols, (
        "Column 'tasks.estimation_status' does not exist. Migration 004 not applied."
    )


@pytest.mark.asyncio
async def test_tasks_cost_column_exists(pg_engine):
    """Migration 004 must add tasks.cost."""
    async with pg_engine.connect() as conn:
        cols = await get_column_names(conn, "tasks")
    assert "cost" in cols, (
        "Column 'tasks.cost' does not exist. Migration 004 not applied."
    )


# ---------------------------------------------------------------------------
# Tests: columns on 'task_results'
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_task_results_slot_column_exists(pg_engine):
    """Migration 004 must add task_results.slot."""
    async with pg_engine.connect() as conn:
        tables = await get_table_names(conn)
        if "task_results" not in tables:
            pytest.skip("task_results table does not exist")
        cols = await get_column_names(conn, "task_results")
    assert "slot" in cols, (
        "Column 'task_results.slot' does not exist. Migration 004 not applied."
    )


# ---------------------------------------------------------------------------
# Tests: alembic_version sanity
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_alembic_version_is_006(pg_engine):
    """
    After a correct deploy alembic_version must be '006'.
    Also verifies the alembic_version table itself exists.
    """
    async with pg_engine.connect() as conn:
        result = await conn.execute(text("SELECT version_num FROM alembic_version"))
        rows = result.fetchall()
    assert len(rows) == 1, (
        f"Expected 1 row in alembic_version, got {len(rows)}"
    )
    assert rows[0][0] == "006", (
        f"Expected alembic_version='006', got '{rows[0][0]}'"
    )
