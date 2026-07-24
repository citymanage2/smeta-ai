import json
from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost/smeta_ai"
    JWT_SECRET: str = "changeme-use-strong-secret-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = 168  # 7 days
    USER_PASSWORD: str = "user123"
    ADMIN_PASSWORD: str = "admin123"
    MAX_FILE_SIZE_MB: int = 20
    MAX_FILES_PER_REQUEST: int = 10
    TASK_TIMEOUT_SECONDS: int = 600
    CORS_ORIGINS: str = "*"
    VAT_RATE: float = 0.22
    # Наблюдаемость: включает вывод всех SQL-запросов SQLAlchemy в лог (только для отладки).
    SQL_ECHO: bool = False

    def get_cors_origins(self) -> List[str]:
        try:
            return json.loads(self.CORS_ORIGINS)
        except Exception:
            return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
