from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).parent.parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, env_file_encoding="utf-8")

    database_url: str = "sqlite+aiosqlite:///./tg_manager.db"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-4-5-20251001"

    # Telegram API credentials (get from my.telegram.org)
    telegram_api_id: int
    telegram_api_hash: str

    # Encryption key for storing session strings in DB (32 hex chars)
    session_encryption_key: str = "change-me-32-chars-exactly-here!!"


settings = Settings()
