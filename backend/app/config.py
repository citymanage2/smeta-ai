import json
from pydantic_settings import BaseSettings
from pydantic import model_validator
from typing import List, Any


class Settings(BaseSettings):
    ANTHROPIC_API_KEY: str = ""
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost/smeta_ai"
    JWT_SECRET: str = "changeme-use-strong-secret-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = 24
    USER_PASSWORD: str = "user123"
    ADMIN_PASSWORD: str = "admin123"
    MAX_FILE_SIZE_MB: int = 20
    MAX_FILES_PER_REQUEST: int = 10
    TASK_TIMEOUT_SECONDS: int = 600
    CORS_ORIGINS: List[str] = ["http://localhost:5173", "http://localhost:3000"]

    @model_validator(mode="before")
    @classmethod
    def parse_list_fields(cls, values: Any) -> Any:
        if isinstance(values, dict) and "CORS_ORIGINS" in values:
            v = values["CORS_ORIGINS"]
            if isinstance(v, str):
                try:
                    parsed = json.loads(v)
                    values["CORS_ORIGINS"] = parsed
                except Exception:
                    values["CORS_ORIGINS"] = [o.strip() for o in v.split(",") if o.strip()]
        return values

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
