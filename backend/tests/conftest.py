"""
Async test fixtures for Smeta AI backend tests.

Uses an in-memory SQLite database so no PostgreSQL is needed.
All fixtures are async-compatible via pytest-asyncio auto mode.
"""
import io
import sys
import uuid
import pytest
import pytest_asyncio
from unittest.mock import MagicMock
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import event, text

# Mock weasyprint before importing app modules (to avoid system dependency errors on macOS)
weasyprint_mock = MagicMock()
html_class_mock = MagicMock()

def mock_write_pdf():
    return b"%PDF-1.4\n%Mock PDF content\nendstream"

html_class_mock.return_value.write_pdf = mock_write_pdf
weasyprint_mock.HTML = html_class_mock
sys.modules['weasyprint'] = weasyprint_mock

from app.database import Base, get_db
from app.models.task import Task          # noqa: F401  (registers with Base.metadata)
from app.models.task_input_file import TaskInputFile  # noqa: F401
from app.models.result import TaskResult  # noqa: F401
from app.models.user import User          # noqa: F401
from app.models.price import PriceWork, PriceMaterial  # noqa: F401
from app.models.price_list import PriceList             # noqa: F401
from app.models.project import Project    # noqa: F401
from app.models.history import TaskHistory  # noqa: F401
from app.utils.auth import hash_password, create_access_token
from app.services import storage_service


# ---------------------------------------------------------------------------
# In-memory fake S3 — после contract-фазы (035) байты файлов живут только в S3.
# Автоюз-фикстура подменяет boto3-клиент на in-memory dict и включает S3_ENABLED,
# так что роут-тесты гоняют реальный S3-путь приложения (как прод), без сети.
# ---------------------------------------------------------------------------

class _FakeS3:
    """Минимальный in-memory S3-клиент (только используемые операции)."""

    def __init__(self):
        self.store: dict[str, bytes] = {}

    def put_object(self, Bucket, Key, Body, **kw):
        self.store[Key] = Body
        return {}

    def get_object(self, Bucket, Key):
        from botocore.exceptions import ClientError
        if Key not in self.store:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": io.BytesIO(self.store[Key])}

    def delete_object(self, Bucket, Key):
        self.store.pop(Key, None)
        return {}

    def head_object(self, Bucket, Key):
        from botocore.exceptions import ClientError
        if Key not in self.store:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        return {}

    def list_objects_v2(self, Bucket, Prefix, ContinuationToken=None):
        keys = [k for k in self.store if k.startswith(Prefix)]
        return {"Contents": [{"Key": k} for k in keys], "IsTruncated": False}

    def delete_objects(self, Bucket, Delete):
        for o in Delete["Objects"]:
            self.store.pop(o["Key"], None)
        return {}


@pytest.fixture(autouse=True)
def fake_s3(monkeypatch):
    """Подменяет S3-клиент на in-memory fake и включает S3_ENABLED для всех тестов."""
    client = _FakeS3()
    monkeypatch.setattr(storage_service, "_client", client)
    monkeypatch.setattr(storage_service.settings, "S3_ENABLED", True)
    return client


async def store_result_row(db, task_id, slot, file_name, mime, data, **extra):
    """Тест-хелпер: положить байты результата в fake-S3 и вернуть TaskResult со
    storage_key (после contract-фазы 035 BLOB-колонки file_data больше нет).
    Строка добавляется в сессию; коммит — на стороне вызывающего."""
    from app.models.result import TaskResult
    key = storage_service.build_result_key(task_id, slot, file_name)
    await storage_service.put_object(key, data, mime)
    row = TaskResult(
        task_id=task_id, file_name=file_name, mime_type=mime,
        storage_key=key, size_bytes=len(data), slot=slot, **extra,
    )
    db.add(row)
    return row


async def store_input_row(db, task_id, file_index, file_name, mime, data, **extra):
    """Тест-хелпер: положить байты входного файла в fake-S3 и вернуть TaskInputFile."""
    key = storage_service.build_input_key(task_id, file_index, file_name)
    await storage_service.put_object(key, data, mime)
    row = TaskInputFile(
        task_id=task_id, file_index=file_index, file_name=file_name,
        mime_type=mime, size_bytes=len(data), storage_key=key, **extra,
    )
    db.add(row)
    return row

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
    return f"Bearer {create_access_token(1, 'user')}"


@pytest.fixture
def admin_token() -> str:
    return f"Bearer {create_access_token(2, 'admin')}"


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
async def seed_users(db_session: AsyncSession, fake_s3):
    """Seed User rows and a sample Task + input file + TaskResult into the test DB.

    Байты файлов кладём в fake-S3 (contract-фаза 035: BLOB-колонок больше нет),
    в БД — только storage_key.
    """
    # Users
    user = User(role="user", password_hash=hash_password("user123"))
    admin = User(role="admin", password_hash=hash_password("admin123"))
    db_session.add(user)
    db_session.add(admin)
    await db_session.flush()

    # Task with a known ID (explicit, bypasses server_default). input_file_data
    # хранит только метаданные (как после backfill — content_b64 вырезан).
    task = Task(owner_id=1, 
        id=SEEDED_TASK_ID,
        user_role="user",
        task_type="LIST_FROM_GRAND",
        status="completed",
        input_files=[
            {"name": "test.pdf", "mime_type": "application/pdf", "size_bytes": 4}
        ],
        input_file_data=[
            {"name": "test.pdf", "mime_type": "application/pdf", "size_bytes": 4}
        ],
        chat_history=[],
    )
    db_session.add(task)
    await db_session.flush()

    # Входной файл — байты b"test" в S3, в БД строка task_input_files со storage_key
    input_key = storage_service.build_input_key(SEEDED_TASK_ID, 0, "test.pdf")
    await storage_service.put_object(input_key, b"test", "application/pdf")
    db_session.add(TaskInputFile(
        task_id=SEEDED_TASK_ID,
        file_index=0,
        file_name="test.pdf",
        mime_type="application/pdf",
        size_bytes=4,
        storage_key=input_key,
    ))

    # TaskResult linked to the seeded task — байты в S3
    result_key = storage_service.build_result_key(SEEDED_TASK_ID, "result", "result.xlsx")
    await storage_service.put_object(
        result_key,
        b"fake-excel-content",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    result = TaskResult(
        task_id=SEEDED_TASK_ID,
        file_name="result.xlsx",
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        storage_key=result_key,
        size_bytes=len(b"fake-excel-content"),
    )
    db_session.add(result)
    await db_session.commit()

    yield

    # Cleanup — handled by db_session rollback fixture, but ensure explicit clean
    await db_session.execute(text("DELETE FROM task_input_files"))
    await db_session.execute(text("DELETE FROM task_results"))
    await db_session.execute(text("DELETE FROM tasks"))
    await db_session.execute(text("DELETE FROM users"))
    await db_session.commit()
