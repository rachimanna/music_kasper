import asyncio
import logging
from typing import Any, Dict, List, Optional

import aiohttp

from bot.services.base import BaseMusicProvider, ProviderError, Track

logger = logging.getLogger(__name__)


class DeezerMusicService(BaseMusicProvider):
    BASE_URL = "https://api.deezer.com"

    def __init__(self) -> None:
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10),
                headers={"User-Agent": "MusicKasperBot/2.0"},
            )
        return self._session

    async def _request(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        session = await self._get_session()
        try:
            async with session.get(f"{self.BASE_URL}{path}", params=params) as resp:
                if resp.status != 200:
                    raise ProviderError(f"Deezer HTTP {resp.status}")
                data = await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            raise ProviderError(f"Deezer request failed: {exc!r}") from exc

        if not isinstance(data, dict):
            raise ProviderError("Deezer returned unexpected payload")

        # Deezer отвечает HTTP 200 даже на ошибки (например, превышение квоты).
        if "error" in data:
            error = data["error"] or {}
            raise ProviderError(f"Deezer error {error.get('code')}: {error.get('message')}")
        return data

    @staticmethod
    def _parse_track(item: Dict[str, Any]) -> Optional[Track]:
        if not isinstance(item, dict) or item.get("id") is None:
            return None
        album = item.get("album") or {}
        artist = item.get("artist") or {}
        try:
            duration = int(item.get("duration") or 0)
        except (TypeError, ValueError):
            duration = 0
        return Track(
            id=str(item["id"]),
            title=item.get("title_short") or item.get("title") or "Без названия",
            artist=artist.get("name") or "Неизвестный исполнитель",
            duration=duration,
            preview_url=item.get("preview") or None,
            # 250x250 — подходит и для превью в inline, и для обложки аудио в Telegram (≤320px).
            cover_url=album.get("cover_medium") or album.get("cover_small") or None,
            external_url=item.get("link") or f"https://www.deezer.com/track/{item['id']}",
        )

    async def search(self, query: str, limit: int = 25) -> List[Track]:
        data = await self._request("/search", {"q": query, "limit": limit})
        tracks = [self._parse_track(item) for item in data.get("data") or []]
        return [t for t in tracks if t is not None]

    async def get_track(self, track_id: str) -> Optional[Track]:
        if not track_id.isdigit():
            return None
        try:
            data = await self._request(f"/track/{track_id}")
        except ProviderError as exc:
            logger.warning("Cannot fetch Deezer track %s: %s", track_id, exc)
            return None
        return self._parse_track(data)

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()


# Один общий экземпляр на всё приложение.
deezer = DeezerMusicService()
