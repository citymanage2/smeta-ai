from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    BOT_TOKEN: str
    ANTHROPIC_API_KEY: str
    # Абсолютный путь к Obsidian vault, например: /Users/admin/Desktop/MyVault
    VAULT_PATH: str

    model_config = {"env_file": Path(__file__).parent / ".env", "env_file_encoding": "utf-8"}

    @property
    def vault(self) -> Path:
        return Path(self.VAULT_PATH)


settings = Settings()
