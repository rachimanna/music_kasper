import logging
from typing import List, Optional
import aiohttp
from bot.services.base import BaseMusicProvider, Track

logger = logging.getLogger(__name__)


class DeezerMusicService(BaseMusicProvider):
    BASE_URL = "https://api.deezer.com"

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=10)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def search(self, query: str, limit: int = 25) -> List[Track]:
        session = await self._get_session()
        params = {"q": query, "limit": limit}

        try:
            async with session.get(f"{self.BASE_URL}/search", params=params) as resp:
                if resp.status != 200:
                    logger.error(f"Deezer search error, HTTP status: {resp.status}")
                    return []

                data = await resp.json()
                results = data.get("data", [])
                tracks: List[Track] = []

                for item in results:
                    tracks.append(
                        Track(
                            id=str(item.get("id")),
                            title=item.get("title_short") or item.get("title", "Без названия"),
                            artist=item.get("artist", {}).get("name", "Неизвестный исполнитель"),
                            duration=int(item.get("duration", 0)),
                            preview_url=item.get("preview"),
                            cover_url=item.get("album", {}).get("cover_big") or item.get("album", {}).get("cover_medium"),
                            external_url=item.get("link", "https://deezer.com")
                        )
                    )
                return tracks
        except Exception as e:
            logger.error(f"Error querying Deezer API: {e}", exc_info=True)
            return []

    async def get_track(self, track_id: str) -> Optional[Track]:
        session = await self._get_session()
        try:
            async with session.get(f"{self.BASE_URL}/track/{track_id}") as resp:
                if resp.status != 200:
                    return None
                item = await resp.json()
                if "error" in item:
                    return None

                return Track(
                    id=str(item.get("id")),
                    title=item.get("title_short") or item.get("title", "Без названия"),
                    artist=item.get("artist", {}).get("name", "Неизвестный исполнитель"),
                    duration=int(item.get("duration", 0)),
                    preview_url=item.get("preview"),
                    cover_url=item.get("album", {}).get("cover_big") or item.get("album", {}).get("cover_medium"),
                    external_url=item.get("link", "https://deezer.com")
                )
        except Exception as e:
            logger.error(f"Error fetching track {track_id}: {e}", exc_info=True)
            return None

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
