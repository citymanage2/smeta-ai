import structlog
import os
import asyncio
import time
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
from sqlalchemy import select, text

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

# ПРИМЕЧАНИЕ: обработка задач, планировщик и обслуживающие поллеры
# (batch/resume/reclaim/cleanup) переехали в отдельный worker-процесс
# (app/worker.py). Web больше не обрабатывает задачи и не держит scheduler.


async def _initialize_users() -> None:
    """Bootstrap-аккаунты и backfill владельца legacy-данных.

    - Именованный админ (ADMIN_USERNAME + ADMIN_PASSWORD): под ним первый вход и
      создание остальных аккаунтов в UI; он же — владелец архива legacy-данных.
    - Legacy shared-пароли ролей (username IS NULL) — оставлены для переходной
      совместимости входа по общему паролю.
    - Индивидуальные аккаунты сотрудников теперь создаются только через UI
      (env-переменная USERS больше не обрабатывается).
    - Backfill: все проекты/задачи без владельца → на именованного админа + в архив.
    Хэш пароля обновляется, если env-переменная изменилась с прошлого деплоя.
    """
    async with AsyncSessionLocal() as db:
        # Именованный бутстрап-админ (username = ADMIN_USERNAME).
        admin_username = (settings.ADMIN_USERNAME or "admin").strip()
        result = await db.execute(select(User).where(User.username == admin_username))
        admin = result.scalar_one_or_none()
        if not admin:
            admin = User(
                username=admin_username,
                role="admin",
                full_name="Администратор",
                password_hash=hash_password(settings.ADMIN_PASSWORD),
            )
            db.add(admin)
            logger.info("Created named admin", username=admin_username)
        else:
            admin.role = "admin"
            admin.is_active = True
            if not verify_password(settings.ADMIN_PASSWORD, admin.password_hash):
                admin.password_hash = hash_password(settings.ADMIN_PASSWORD)
                logger.info("Updated named admin password", username=admin_username)
        # Нужен id админа для backfill — фиксируем запись.
        await db.flush()
        admin_id = admin.id

        # Legacy shared-пароли ролей (username IS NULL) — переходная совместимость.
        for role, password in [("user", settings.USER_PASSWORD), ("admin", settings.ADMIN_PASSWORD)]:
            result = await db.execute(
                select(User).where(User.role == role, User.username.is_(None))
            )
            existing = result.scalar_one_or_none()
            if not existing:
                db.add(User(role=role, password_hash=hash_password(password)))
                logger.info("Created default shared user", role=role)
            else:
                if not verify_password(password, existing.password_hash):
                    existing.password_hash = hash_password(password)
                    logger.info("Updated password hash for shared user", role=role)

        # Backfill владельца: legacy проекты/задачи без owner_id → админ + архив.
        # Идемпотентно: после перехода новые строки всегда с owner_id.
        res_p = await db.execute(
            text(
                "UPDATE projects SET owner_id = :aid, is_archived = true "
                "WHERE owner_id IS NULL"
            ),
            {"aid": admin_id},
        )
        res_t = await db.execute(
            text(
                "UPDATE tasks SET owner_id = :aid, is_archived = true "
                "WHERE owner_id IS NULL"
            ),
            {"aid": admin_id},
        )
        if res_p.rowcount or res_t.rowcount:
            logger.info(
                "Backfilled legacy owners to admin",
                projects=res_p.rowcount, tasks=res_t.rowcount, admin_id=admin_id,
            )

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
        # Обработка задач, reclaim зависших, batch/resume/cleanup поллеры —
        # в отдельном worker-процессе (app/worker.py). Web их не запускает.
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

    # Request-timing middleware (наблюдаемость): пишет длительность каждого
    # HTTP-ответа. Добавлен до CORS → CORS окажется снаружи, а тайминг обернёт
    # реальную обработку. Health-check и статику (SPA-ассеты, index.html) не
    # логируем, чтобы не засорять лог фоновым трафиком поллеров.
    _timing_skip_exact = {"/health", "/"}

    @app.middleware("http")
    async def request_timing_middleware(request: Request, call_next):
        path = request.url.path
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        if path not in _timing_skip_exact and not path.startswith("/assets"):
            logger.info(
                "request",
                method=request.method,
                path=path,
                status=response.status_code,
                duration_ms=duration_ms,
            )
        response.headers["X-Process-Time-Ms"] = str(duration_ms)
        return response

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
    from app.routers import admin_users
    from app.routers.calculator import router as calculator_router
    from app.routers.dashboard import router as dashboard_router
    from app.routers.estimate_versions import router as estimate_versions_router
    from app.routers.prices_catalog import router as prices_catalog_router
    from app.routers.workflow_cards import router as workflow_cards_router
    from app.routers.summary import router as summary_router
    from app.routers.retraining import router as retraining_router

    app.include_router(auth.router)
    app.include_router(tasks.router)
    app.include_router(results.router)
    app.include_router(admin.router)
    app.include_router(admin_users.router)
    app.include_router(projects.router)
    app.include_router(calculator_router)
    app.include_router(dashboard_router)
    app.include_router(estimate_versions_router)
    app.include_router(prices_catalog_router)
    app.include_router(workflow_cards_router, prefix="/api")
    app.include_router(summary_router, prefix="/api")
    app.include_router(retraining_router)

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
