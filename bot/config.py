from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    BOT_TOKEN: str = Field(..., description="Telegram Bot API Token")
    BOT_USERNAME: str = Field(default="", description="Telegram Bot Username without @")
    DB_PATH: str = Field(default="music_bot.db", description="Path to SQLite database")
    RATE_LIMIT: float = Field(default=1.0, description="Rate limit per user in seconds")
    PAGE_SIZE: int = Field(default=5, description="Tracks per search page")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


config = Settings()
