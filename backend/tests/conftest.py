"""
Async test fixtures for Smeta AI backend tests.

Uses an in-memory SQLite database so no PostgreSQL is needed.
All fixtures are async-compatible via pytest-asyncio auto mode.
"""
import uuid
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import event, text

from app.database import Base, get_db
from app.models.task import Task          # noqa: F401  (registers with Base.metadata)
from app.models.result import TaskResult  # noqa: F401
from app.models.user import User          # noqa: F401
from app.models.price import PriceWork, PriceMaterial  # noqa: F401
from app.models.price_list import PriceList             # noqa: F401
# Migration-003 models — imported here so Base.metadata knows about them before
# the session-scoped create_tables fixture runs.  These tables use
#   server_default=text("gen_random_uuid()")
# which SQLite rejects in CREATE TABLE DEFAULT constraints.  We pre-create them
# below with SQLite built-in equivalents (randomblob/hex/lower) so that
# Base.metadata.create_all (checkfirst=True by default) simply skips them.
from app.models.project import Project                  # noqa: F401
from app.models.task_version import TaskVersion         # noqa: F401
from app.models.estimate_item import EstimateItem       # noqa: F401
from app.utils.auth import hash_password, create_access_token

# ---------------------------------------------------------------------------
# SQLite-compatible CREATE TABLE statements for all UUID-primary-key tables.
#
# PostgreSQL's gen_random_uuid() is not a valid SQLite DEFAULT expression.
# SQLite rejects function calls in DEFAULT unless wrapped in parentheses AND
# the function is a recognised built-in.  We use randomblob/hex/lower which
# are SQLite built-ins.  These tables are pre-created before create_all so
# that create_all (checkfirst=True by default) skips them.
# ---------------------------------------------------------------------------

# tasks: includes ALL columns from the current model (migration-003 added
# project_id, estimate_status, estimate_status_updated_at,
# estimate_status_updated_by).
_TASKS_DDL = """
CREATE TABLE IF NOT EXISTS tasks (
    id                         TEXT NOT NULL DEFAULT (lower(hex(randomblob(16)))),
    user_role                  VARCHAR(10) NOT NULL,
    task_type                  VARCHAR(50) NOT NULL,
    status                     VARCHAR(20) NOT NULL DEFAULT 'pending',
    input_files                TEXT NOT NULL DEFAULT '[]',
    input_file_data            TEXT NOT NULL DEFAULT '[]',
    user_prompt                TEXT,
    chat_history               TEXT NOT NULL DEFAULT '[]',
    progress_message           VARCHAR(500),
    error_message              TEXT,
    project_id                 TEXT,
    estimate_status            VARCHAR(50) NOT NULL DEFAULT 'uploaded',
    estimate_status_updated_at TIMESTAMP,
    estimate_status_updated_by VARCHAR(20) NOT NULL DEFAULT 'manual',
    created_at                 TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at                 TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
)
"""

_PROJECTS_DDL = """
CREATE TABLE IF NOT EXISTS projects (
    id          TEXT NOT NULL DEFAULT (lower(hex(randomblob(16)))),
    name        VARCHAR(255) NOT NULL,
    description TEXT,
    user_id     INTEGER,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL
)
"""

_TASK_VERSIONS_DDL = """
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

_ESTIMATE_ITEMS_DDL = """
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
# Test engine — SQLite in-memory
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)

# Register gen_random_uuid() as a SQLite user-defined function so the Task
# model's server_default=text("gen_random_uuid()") works at the DB level.
@event.listens_for(test_engine.sync_engine, "connect")
def _register_sqlite_functions(dbapi_connection, connection_record):
    dbapi_connection.create_function("gen_random_uuid", 0, lambda: str(uuid.uuid4()))


TestSessionLocal = async_sessionmaker(
    test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# ---------------------------------------------------------------------------
# Session-scoped: create / drop tables once per test session
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="session", autouse=True)
async def create_tables():
    async with test_engine.begin() as conn:
        # Pre-create all tables that use gen_random_uuid() in their DEFAULT
        # constraint using SQLite-compatible built-ins.  create_all below
        # (checkfirst=True by default) will skip pre-existing tables.
        await conn.execute(text(_TASKS_DDL))         # must come before task_versions/estimate_items
        await conn.execute(text(_PROJECTS_DDL))
        await conn.execute(text(_TASK_VERSIONS_DDL))
        await conn.execute(text(_ESTIMATE_ITEMS_DDL))
        # Create all remaining tables (users, task_results, price_*, etc.)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


# ---------------------------------------------------------------------------
# Function-scoped DB session — rolls back after every test
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db_session():
    async with TestSessionLocal() as session:
        yield session
        await session.rollback()


# ---------------------------------------------------------------------------
# Token fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def user_token() -> str:
    return f"Bearer {create_access_token('user')}"


@pytest.fixture
def admin_token() -> str:
    return f"Bearer {create_access_token('admin')}"


# ---------------------------------------------------------------------------
# App fixture — override get_db with test session
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def test_app(db_session: AsyncSession):
    """Return the FastAPI app with get_db overridden to use the test session."""
    from contextlib import asynccontextmanager

    import app.database as db_module
    import app.main as main_module

    original_engine = db_module.engine
    original_session_local = db_module.AsyncSessionLocal
    original_lifespan = main_module.lifespan

    # Replace the lifespan with a no-op so the startup sequence
    # (init_db, _initialize_users, price_service.load_cache) is skipped.
    # Tables are already created by the session-scoped create_tables fixture.
    # _initialize_users uses app.main.AsyncSessionLocal (a local import-time
    # binding) which still points to the production engine even after patching
    # db_module.AsyncSessionLocal — patching lifespan avoids this entirely.
    @asynccontextmanager
    async def _noop_lifespan(app):
        yield

    main_module.lifespan = _noop_lifespan
    db_module.engine = test_engine
    db_module.AsyncSessionLocal = TestSessionLocal

    from app.main import create_app
    application = create_app()

    # Override the get_db dependency so all routes use our test session
    async def override_get_db():
        yield db_session

    application.dependency_overrides[get_db] = override_get_db

    yield application

    # Restore
    application.dependency_overrides.clear()
    main_module.lifespan = original_lifespan
    db_module.engine = original_engine
    db_module.AsyncSessionLocal = original_session_local


# ---------------------------------------------------------------------------
# Async HTTP client
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def async_client(test_app):
    """Async httpx client wired directly to the test app (no network)."""
    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        yield client


# ---------------------------------------------------------------------------
# Seed data — inserted once per test function (uses db_session)
# ---------------------------------------------------------------------------

SEEDED_TASK_ID = "00000000-0000-0000-0000-000000000001"


@pytest_asyncio.fixture
async def seed_users(db_session: AsyncSession):
    """Seed User rows and a sample Task + TaskResult into the test DB."""
    # Users
    user = User(role="user", password_hash=hash_password("user123"))
    admin = User(role="admin", password_hash=hash_password("admin123"))
    db_session.add(user)
    db_session.add(admin)
    await db_session.flush()

    # Task with a known ID (explicit, bypasses server_default)
    task = Task(
        id=SEEDED_TASK_ID,
        user_role="user",
        task_type="LIST_FROM_TZ",
        status="completed",
        input_files=[
            {"name": "test.pdf", "mime_type": "application/pdf", "size_bytes": 100}
        ],
        input_file_data=[
            {
                "name": "test.pdf",
                "mime_type": "application/pdf",
                "size_bytes": 100,
                "content_b64": "dGVzdA==",  # base64("test")
            }
        ],
        chat_history=[],
    )
    db_session.add(task)
    await db_session.flush()

    # TaskResult linked to the seeded task
    result = TaskResult(
        task_id=SEEDED_TASK_ID,
        file_name="result.xlsx",
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        file_data=b"fake-excel-content",
    )
    db_session.add(result)
    await db_session.commit()

    yield

    # Cleanup — handled by db_session rollback fixture, but ensure explicit clean
    await db_session.execute(text("DELETE FROM task_results"))
    await db_session.execute(text("DELETE FROM tasks"))
    await db_session.execute(text("DELETE FROM users"))
    await db_session.commit()
