"""
Tests to guard against the 'alembic stamp head && alembic upgrade head' bug.

Background: the deploy start command previously ran 'alembic stamp head' before
'alembic upgrade head'. stamp head marks the DB as already at HEAD without
running any migrations, so upgrade head becomes a no-op. This caused the
'projects' table and 'tasks.project_id' column to never be created on fresh
deploys.

The deploy has since moved from the Render native runtime (startCommand in
render.yaml) to a Docker runtime, so the start command now lives in the
Dockerfile CMD. These static tests read that CMD as the source of truth.

Two test levels:
  1. Static — reads the Dockerfile CMD, fails fast if stamp head is present.
  2. Integration — runs alembic upgrade head against a real PostgreSQL DB
     and checks that 'projects' table and 'tasks.project_id' column exist.
     Skipped automatically when DATABASE_URL is not set.
"""
import os
import re
import subprocess
import sys
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DOCKERFILE = os.path.join(os.path.dirname(__file__), "..", "Dockerfile")
BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..")


def _get_start_command(path: str = DOCKERFILE) -> str:
    """Return the deploy start command — the `sh -c` argument of the Dockerfile CMD."""
    with open(path) as f:
        content = f.read()
    # CMD ["sh", "-c", "<start command>"]
    m = re.search(r'CMD\s*\[.*?"-c",\s*"(.+?)"\s*\]', content, re.DOTALL)
    assert m, "CMD [\"sh\", \"-c\", ...] not found in Dockerfile"
    return m.group(1).strip()


# ---------------------------------------------------------------------------
# Level 1: static check — no stamp head in startCommand
# ---------------------------------------------------------------------------


def test_render_yaml_start_command_has_no_stamp_head():
    """
    The deploy start command must NOT contain 'alembic stamp head'.

    When stamp head precedes upgrade head, it marks the DB as fully migrated
    without actually running any migration SQL.  upgrade head then sees no
    pending migrations and exits immediately.  The result: fresh databases
    never receive the schema changes introduced by migrations 004–006
    (projects table, tasks.project_id, etc.).
    """
    cmd = _get_start_command()
    assert "alembic stamp head" not in cmd, (
        f"Dockerfile CMD contains 'alembic stamp head' which "
        f"prevents migrations from running on fresh databases.\n"
        f"Current command: {cmd}\n"
        f"Fix: remove 'alembic stamp head &&' — upgrade head is a no-op "
        f"when the DB is already at HEAD, so stamp is never needed."
    )


def test_render_yaml_start_command_has_upgrade_head():
    """The deploy start command must contain 'alembic upgrade head'."""
    cmd = _get_start_command()
    assert "alembic upgrade head" in cmd, (
        f"Dockerfile CMD is missing 'alembic upgrade head'.\n"
        f"Current command: {cmd}"
    )


def test_render_yaml_upgrade_head_before_uvicorn():
    """upgrade head must appear before uvicorn in the start command."""
    cmd = _get_start_command()
    upgrade_pos = cmd.find("alembic upgrade head")
    uvicorn_pos = cmd.find("uvicorn")
    assert upgrade_pos != -1 and uvicorn_pos != -1, (
        "Both 'alembic upgrade head' and 'uvicorn' must be in the start command"
    )
    assert upgrade_pos < uvicorn_pos, (
        "alembic upgrade head must run before uvicorn"
    )


def test_start_command_has_no_obsolete_fix_script():
    """
    The deploy start command must NOT invoke scripts/fix_production_db.py.

    That script was a one-shot repair for the historical 'stamp head' bug: it
    reset alembic_version from '006' back to '003' on an already-broken
    production DB so upgrade head would re-apply migrations 004–006. Fresh
    Docker deploys run a clean 'alembic upgrade head', so the repair must not
    be part of the routine start command — running it on every boot would be a
    destructive no-op at best. The script is retained in scripts/ for manual,
    one-off use only.
    """
    cmd = _get_start_command()
    assert "fix_production_db.py" not in cmd, (
        "fix_production_db.py must NOT be in the deploy start command — it is a "
        "one-shot manual repair, not part of routine startup.\n"
        f"Current command: {cmd}"
    )


# ---------------------------------------------------------------------------
# Level 2: integration — real migrations on PostgreSQL
# ---------------------------------------------------------------------------


DATABASE_URL = os.environ.get("DATABASE_URL", "")


@pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL not set — skipping live migration test",
)
def test_upgrade_head_creates_projects_table():
    """
    Running 'alembic upgrade head' (no stamp) on a fresh schema must create
    the 'projects' table.
    """
    import sqlalchemy as sa

    sync_url = DATABASE_URL.replace("+asyncpg", "")
    engine = sa.create_engine(sync_url)

    with engine.connect() as conn:
        inspector = sa.inspect(conn)
        tables_before = set(inspector.get_table_names())

    # Drop alembic_version to simulate fresh deploy
    with engine.begin() as conn:
        conn.execute(sa.text("DROP TABLE IF EXISTS alembic_version"))
        conn.execute(sa.text("DROP TABLE IF EXISTS projects CASCADE"))

    # Run upgrade head WITHOUT stamp
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": DATABASE_URL},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"alembic upgrade head failed:\n{result.stdout}\n{result.stderr}"
    )

    # Verify schema
    with engine.connect() as conn:
        inspector = sa.inspect(conn)
        assert "projects" in inspector.get_table_names(), (
            "projects table was NOT created by alembic upgrade head"
        )
        task_cols = {c["name"] for c in inspector.get_columns("tasks")}
        assert "project_id" in task_cols, (
            "tasks.project_id column was NOT created by alembic upgrade head"
        )

    engine.dispose()


@pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL not set — skipping live migration test",
)
def test_stamp_head_then_upgrade_head_skips_migrations():
    """
    Demonstrates the bug: stamp head followed by upgrade head leaves a fresh
    database without the projects table.

    This test is intentionally marked xfail when stamp head is absent from
    render.yaml (i.e., after the fix), because the buggy scenario can no
    longer be triggered by the deploy command.
    """
    import sqlalchemy as sa

    sync_url = DATABASE_URL.replace("+asyncpg", "")
    engine = sa.create_engine(sync_url)

    # Simulate empty schema
    with engine.begin() as conn:
        conn.execute(sa.text("DROP TABLE IF EXISTS alembic_version"))
        conn.execute(sa.text("DROP TABLE IF EXISTS projects CASCADE"))

    # Run stamp head (marks DB as at HEAD without running SQL)
    stamp = subprocess.run(
        [sys.executable, "-m", "alembic", "stamp", "head"],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": DATABASE_URL},
        capture_output=True,
        text=True,
    )
    assert stamp.returncode == 0

    # Run upgrade head — should be a no-op now
    upgrade = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": DATABASE_URL},
        capture_output=True,
        text=True,
    )
    assert upgrade.returncode == 0

    # After stamp+upgrade, projects table should NOT exist (the bug)
    with engine.connect() as conn:
        inspector = sa.inspect(conn)
        tables = inspector.get_table_names()

    engine.dispose()

    assert "projects" not in tables, (
        "Expected projects table to be ABSENT after stamp+upgrade (demonstrating "
        "the bug), but it was present. This means alembic ran migrations anyway "
        "— the bug may be fixed at the alembic level."
    )
