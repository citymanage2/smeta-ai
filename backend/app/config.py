import json
from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    ANTHROPIC_API_KEY: str = ""
    # Посредник для обхода геоблока Anthropic с РФ-IP.
    #   ANTHROPIC_BASE_URL пусто → SDK идёт напрямую на api.anthropic.com (локально);
    #   задан → трафик через посредника (агрегатор или свой прокси в ЕС).
    ANTHROPIC_BASE_URL: str = ""
    # Только для СВОЕГО прокси: прокидывается как заголовок X-Proxy-Secret,
    # чтобы прокси не был открытым. Агрегатору не нужен — оставить пустым.
    ANTHROPIC_PROXY_SECRET: str = ""
    OPENAI_API_KEY: str = ""
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost/smeta_ai"
    JWT_SECRET: str = "changeme-use-strong-secret-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = 168  # 7 days
    USER_PASSWORD: str = "user123"
    ADMIN_PASSWORD: str = "admin123"
    # Индивидуальные аккаунты для сидинга: "login:pass:role;login2:pass2:role2".
    # role необязателен (по умолчанию user). Пусто → только общие пароли (legacy).
    USERS: str = ""
    MAX_FILE_SIZE_MB: int = 20
    MAX_FILES_PER_REQUEST: int = 10
    TASK_TIMEOUT_SECONDS: int = 600
    CORS_ORIGINS: str = "*"
    VAT_RATE: float = 0.22
    # Наблюдаемость: включает вывод всех SQL-запросов SQLAlchemy в лог (только для отладки).
    SQL_ECHO: bool = False

    # --- Durable-очередь и worker ---
    WORKER_CONCURRENCY: int = 4          # сколько job worker гонит одновременно
    ANTHROPIC_MAX_CONCURRENCY: int = 6   # глобальный семафор вызовов Anthropic (защита от 429)
    FAST_CHUNK_CONCURRENCY: int = 4      # параллельность чанков внутри задачи (было в task_processor)
    JOB_VISIBILITY_TIMEOUT_S: int = 900  # зависшая running-job (без heartbeat) → reclaim
    JOB_POLL_INTERVAL_S: float = 2.0     # интервал опроса очереди worker'ом
    JOB_MAX_ATTEMPTS: int = 3            # после стольких attempts job → failed
    JOB_DRAIN_TIMEOUT_S: int = 25        # сколько ждём текущие job при SIGTERM (< грейса Timeweb)
    # Пул asyncpg под число слотов (env, чтобы поднять при масштабировании воркеров).
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    # SSL к managed Postgres (Phase 4 деплоя):
    #   '' → без TLS (локально);
    #   'require' → TLS без проверки серта (достаточно для managed в приватной сети);
    #   'verify-ca'/'verify-full' → TLS с проверкой серта по системным CA.
    DB_SSL_MODE: str = ""

    # --- S3-хранилище файлов (Timeweb Cloud Storage) ---
    # Бинарь файлов выносится из PostgreSQL BLOB в объектное хранилище.
    # S3_ENABLED — feature-flag для постепенного включения (dual-read/new-write).
    S3_ENABLED: bool = False
    S3_ENDPOINT_URL: str = "https://s3.twcstorage.ru"
    S3_REGION: str = "ru-1"
    S3_BUCKET: str = ""
    S3_ACCESS_KEY_ID: str = ""
    S3_SECRET_ACCESS_KEY: str = ""

    def get_cors_origins(self) -> List[str]:
        try:
            return json.loads(self.CORS_ORIGINS)
        except Exception:
            return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
