from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional


class ProviderError(Exception):
    """Музыкальный сервис недоступен или вернул ошибку (а не «ничего не найдено»)."""


@dataclass
class Track:
    id: str
    title: str
    artist: str
    duration: int
    preview_url: Optional[str]
    cover_url: Optional[str]
    external_url: str

    @property
    def full_name(self) -> str:
        return f"{self.artist} — {self.title}"


class BaseMusicProvider(ABC):
    @abstractmethod
    async def search(self, query: str, limit: int = 25) -> List[Track]:
        """Поиск треков. Бросает ProviderError, если сервис недоступен."""

    @abstractmethod
    async def get_track(self, track_id: str) -> Optional[Track]:
        """Трек по ID или None, если не найден."""

    async def close(self) -> None:
        """Освободить ресурсы (сессии и т.п.)."""
