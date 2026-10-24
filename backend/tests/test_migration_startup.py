"""
Tests to guard against the 'alembic stamp head && alembic upgrade head' bug.

Background: the deploy start command previously ran 'alembic stamp head' before
'alembic upgrade head'. stamp head marks the DB as already at HEAD without
running any migrations, so upgrade head becomes a no-op. This caused the
'projects' table and 'tasks.project_id' column to never be created on fresh
deploys.

The start command lives in the Dockerfile CMD; these static tests read it as
the source of truth.
"""
import os
import re

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DOCKERFILE = os.path.join(os.path.dirname(__file__), "..", "Dockerfile")


def _get_start_command(path: str = DOCKERFILE) -> str:
    """Return the deploy start command — the `sh -c` argument of the Dockerfile CMD."""
    with open(path) as f:
        content = f.read()
    # CMD ["sh", "-c", "<start command>"]
    m = re.search(r'CMD\s*\[.*?"-c",\s*"(.+?)"\s*\]', content, re.DOTALL)
    assert m, "CMD [\"sh\", \"-c\", ...] not found in Dockerfile"
    return m.group(1).strip()


# ---------------------------------------------------------------------------
# Static check — no stamp head in the start command
# ---------------------------------------------------------------------------


def test_start_command_has_no_stamp_head():
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


def test_start_command_upgrade_head_before_uvicorn():
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
