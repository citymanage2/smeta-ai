import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import settings
from app.database import init_db, AsyncSessionLocal
from app.models.user import User
from app.utils.auth import hash_password
from sqlalchemy import select

# Configure structlog
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ]
)

logger = structlog.get_logger()

# Rate limiter
limiter = Limiter(key_func=get_remote_address)


async def _initialize_users() -> None:
    """Create default user and admin accounts if they don't exist."""
    async with AsyncSessionLocal() as db:
        for role, password in [("user", settings.USER_PASSWORD), ("admin", settings.ADMIN_PASSWORD)]:
            result = await db.execute(select(User).where(User.role == role))
            existing = result.scalar_one_or_none()
            if not existing:
                user = User(
                    role=role,
                    password_hash=hash_password(password),
                )
                db.add(user)
                logger.info("Created default user", role=role)

        await db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown."""
    logger.info("Starting Smeta AI backend...")
    try:
        await init_db()
        await _initialize_users()
        logger.info("Startup complete")
    except Exception as e:
        logger.error("Startup failed", error=str(e))
        raise

    yield

    logger.info("Shutting down Smeta AI backend...")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Smeta AI",
        description="Автоматизированное составление строительных смет с помощью ИИ",
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.get_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Rate limiting middleware
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    # Include routers
    from app.routers import auth, tasks, results, admin

    app.include_router(auth.router)
    app.include_router(tasks.router)
    app.include_router(results.router)
    app.include_router(admin.router)

    # Global error handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error("Unhandled exception", error=str(exc), path=request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Внутренняя ошибка сервера"},
        )

    @app.get("/", include_in_schema=False)
    async def root():
        return RedirectResponse(url="/docs")

    @app.get("/health", tags=["system"])
    async def health_check():
        return {"status": "ok", "service": "Smeta AI"}

    return app


app = create_app()
