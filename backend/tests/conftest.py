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
from app.models.project import Project    # noqa: F401
from app.utils.auth import hash_password, create_access_token

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
    # Patch the database module so the lifespan does not connect to PostgreSQL
    import app.database as db_module
    original_engine = db_module.engine
    original_session_local = db_module.AsyncSessionLocal

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

SEEDED_TASK_ID = "a1000000-0000-0000-0000-000000000001"


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
