import tempfile
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Все настройки читаются из переменных окружения или файла .env."""

    # --- Telegram ---
    BOT_TOKEN: str = Field(..., description="Токен бота от @BotFather")
    # Заполняется автоматически при старте через get_me(), вручную задавать не нужно.
    BOT_USERNAME: str = Field(default="", description="Юзернейм бота без @")

    # --- База данных и поиск ---
    DB_PATH: str = Field(default="music_bot.db")
    RATE_LIMIT: float = Field(default=1.0, description="Минимальный интервал между запросами пользователя, сек (0 = выкл)")
    PAGE_SIZE: int = Field(default=5, ge=1, le=10, description="Треков на одной странице")
    SEARCH_LIMIT: int = Field(default=25, ge=1, le=100, description="Сколько треков запрашивать у Deezer")
    INLINE_LIMIT: int = Field(default=15, ge=1, le=50, description="Сколько результатов показывать в inline-режиме")
    SEARCH_CACHE_TTL: int = Field(default=6 * 3600, ge=0, description="Сколько секунд хранить кэш поиска")
    SESSION_TTL: int = Field(default=3 * 24 * 3600, ge=60, description="Сколько секунд работают кнопки страниц")
    MAX_QUERY_LENGTH: int = Field(default=100, ge=10)

    # --- Источник полных аудиофайлов ---
    # Шаблон ссылки на ПОЛНЫЙ файл. Поддерживает {id}, {artist}, {title}.
    AUDIO_SOURCE_URL_TEMPLATE: str = Field(default="")
    DOWNLOAD_DIR: str = Field(default="", description="Пусто = системная временная папка (работает и в Termux)")
    MAX_SOURCE_SIZE_MB: int = Field(default=100, ge=1, description="Максимальный размер скачиваемого исходника")
    MAX_UPLOAD_SIZE_MB: int = Field(default=49, ge=1, le=50, description="Лимит Telegram Bot API на отправку — 50 МБ")
    AUDIO_BITRATE_KBPS: int = Field(default=192, ge=64, le=320)
    AUDIO_DOWNLOAD_TIMEOUT: int = Field(default=300, ge=10, description="Общий таймаут скачивания, сек")
    FFMPEG_TIMEOUT: int = Field(default=300, ge=10)
    MAX_CONCURRENT_DOWNLOADS: int = Field(default=3, ge=1)
    UPLOAD_TIMEOUT: int = Field(default=300, ge=30, description="Таймаут загрузки файла в Telegram, сек")

    # --- Веб-сервер для Render (health-check) ---
    WEB_SERVER_ENABLED: bool = Field(default=True)
    PORT: int = Field(default=8080)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def download_path(self) -> Path:
        base = Path(self.DOWNLOAD_DIR) if self.DOWNLOAD_DIR else Path(tempfile.gettempdir())
        return base / "music_kasper"

    @property
    def max_source_bytes(self) -> int:
        return self.MAX_SOURCE_SIZE_MB * 1024 * 1024

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024


config = Settings()
