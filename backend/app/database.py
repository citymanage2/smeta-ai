from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import settings
import structlog

logger = structlog.get_logger()

def _make_async_url(url: str) -> str:
    """Ensure the database URL uses the asyncpg driver."""
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


# SSL к managed Postgres (Timeweb DBaaS и т.п.), управляется DB_SSL_MODE:
#   '' → без TLS (локальная разработка);
#   'require'/'true'/'prefer' → ssl=True (шифрование без проверки серта — достаточно
#      для managed-БД в приватной сети);
#   'verify-ca'/'verify-full' → реальная проверка серверного серта по системным CA
#      (verify-full также сверяет hostname). Раньше любой непустой режим давал лишь
#      ssl=True — 'verify-full' не проверял серт (P3-c исправлено).
_connect_args: dict = {
    "server_settings": {
        "tcp_keepalives_idle": "60",
        "tcp_keepalives_interval": "10",
        "tcp_keepalives_count": "5",
    }
}
import ssl as _ssl

_ssl_mode = settings.DB_SSL_MODE.strip().lower()
if _ssl_mode in ("verify-ca", "verify-full"):
    _ssl_ctx = _ssl.create_default_context()
    if _ssl_mode == "verify-ca":
        _ssl_ctx.check_hostname = False  # проверяем цепочку CA, но не hostname
    _connect_args["ssl"] = _ssl_ctx
elif _ssl_mode:
    # require/prefer/true → TLS-шифрование БЕЗ проверки серта. Именно это нужно для
    # managed-БД с самоподписанным сертификатом (asyncpg ssl=True его бы ОТВЕРГ —
    # CERTIFICATE_VERIFY_FAILED). check_hostname=False обязателен ДО verify_mode.
    _ssl_ctx = _ssl.create_default_context()
    _ssl_ctx.check_hostname = False
    _ssl_ctx.verify_mode = _ssl.CERT_NONE
    _connect_args["ssl"] = _ssl_ctx

engine = create_async_engine(
    _make_async_url(settings.DATABASE_URL),
    echo=settings.SQL_ECHO,
    pool_pre_ping=True,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    # Явно: ожидание свободного соединения не должно быть бесконечным и не должно
    # быть «магической» константой библиотеки — потолок пулов мы считаем вручную
    # под max_connections managed-БД (см. config.DB_POOL_SIZE).
    pool_timeout=settings.DB_POOL_TIMEOUT_S,
    pool_recycle=1800,
    connect_args=_connect_args,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


