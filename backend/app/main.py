import structlog
import os
import asyncio
from alembic.config import Config
from alembic import command
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.user import User
from app.utils.auth import hash_password, verify_password
from app.services import price_service
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
    """Create or update default user and admin accounts.

    If a user for a role already exists but the password hash doesn't match
    the current environment variable, update the hash. This ensures password
    changes via env vars take effect after redeployment.
    """
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
            else:
                # Update password hash if env var changed since last deploy
                if not verify_password(password, existing.password_hash):
                    existing.password_hash = hash_password(password)
                    logger.info("Updated password hash for user", role=role)

        await db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown."""
    logger.info("Starting Smeta AI backend...")
    try:
        alembic_cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, command.upgrade, alembic_cfg, "head")
        logger.info("Alembic migrations applied")
        await _initialize_users()
        async with AsyncSessionLocal() as db:
            await price_service.load_cache(db)
        works_count = len(price_service._works_cache)
        mats_count = len(price_service._materials_cache)
        if works_count == 0 and mats_count == 0:
            logger.warning("Price cache is empty — all prices will be sourced via web search")
        else:
            logger.info("Price cache loaded", works=works_count, materials=mats_count)
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

    # Rate limiting middleware
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    # CORS — hardcoded to ["*"] so no env var can silently break preflights.
    # Safe because allow_credentials=False (Bearer tokens, no cookies).
    # Must be added last so Starlette places it outermost (first to run).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    from app.routers import auth, tasks, results, admin, projects
    from app.routers.calculator import router as calculator_router
    from app.routers.estimate_versions import router as estimate_versions_router

    app.include_router(auth.router)
    app.include_router(tasks.router)
    app.include_router(results.router)
    app.include_router(admin.router)
    app.include_router(projects.router)
    app.include_router(calculator_router)
    app.include_router(estimate_versions_router)

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

    # SPA catch-all: serve index.html for all unknown GET paths so that
    # React Router works on hard refresh (F5) for /projects, /tasks/<id>, etc.
    _spa_index = Path(__file__).parent.parent.parent / "frontend" / "dist" / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        return FileResponse(str(_spa_index))

    return app


app = create_app()
