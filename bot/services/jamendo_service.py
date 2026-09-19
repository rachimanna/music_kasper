"""
Jamendo — легальный каталог музыки под лицензиями Creative Commons (https://www.jamendo.com).
Используется, чтобы найти ПОЛНУЮ версию трека, если исполнитель выложил её на Jamendo
и разрешил скачивание. Нужен бесплатный client_id: https://devportal.jamendo.com
"""
import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

import aiohttp

from bot.config import config
from bot.services.base import Track

logger = logging.getLogger(__name__)

_BRACKETS_RE = re.compile(r"\(.*?\)|\[.*?\]")
_NON_WORD_RE = re.compile(r"[^\w]+", re.UNICODE)


def _norm(text: str) -> str:
    """«Song (feat. X) - Remastered!» → «song remastered»."""
    text = _BRACKETS_RE.sub(" ", (text or "").lower())
    return " ".join(_NON_WORD_RE.sub(" ", text).split())


def _same(a: str, b: str) -> bool:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return False
    return a == b or (len(min(a, b, key=len)) >= 4 and (a in b or b in a))


@dataclass
class JamendoMatch:
    download_url: str
    license_url: Optional[str]
    share_url: Optional[str]
    duration: int


class JamendoService:
    BASE_URL = "https://api.jamendo.com/v3.0"

    def __init__(self) -> None:
        self.client_id = config.JAMENDO_CLIENT_ID.strip()
        self._session: Optional[aiohttp.ClientSession] = None

    def configured(self) -> bool:
        return bool(self.client_id)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    @staticmethod
    def _matches(item: Dict[str, Any], track: Track) -> bool:
        if not item.get("audiodownload_allowed") or not item.get("audiodownload"):
            return False
        if not (_same(item.get("artist_name", ""), track.artist) and _same(item.get("name", ""), track.title)):
            return False
        # Защита от совпадения названий у разных песен: длительность должна быть близкой.
        try:
            duration = int(item.get("duration") or 0)
        except (TypeError, ValueError):
            duration = 0
        if track.duration and duration and abs(track.duration - duration) > 15:
            return False
        return True

    async def find_full_track(self, track: Track) -> Optional[JamendoMatch]:
        """Полная версия трека на Jamendo или None, если её там нет."""
        if not self.configured():
            return None

        params = {
            "client_id": self.client_id,
            "format": "json",
            "limit": 20,
            "search": f"{track.artist} {track.title}",
            "audiodlformat": "mp32",
            "audioformat": "mp32",
        }
        try:
            session = await self._get_session()
            async with session.get(f"{self.BASE_URL}/tracks/", params=params) as resp:
                if resp.status != 200:
                    logger.warning("Jamendo HTTP %s", resp.status)
                    return None
                data = await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            logger.warning("Jamendo request failed: %s", exc)
            return None

        headers = data.get("headers") or {}
        if headers.get("status") != "success":
            logger.warning("Jamendo error: %s", headers.get("error_message") or headers)
            return None

        for item in data.get("results") or []:
            if self._matches(item, track):
                logger.info("Jamendo match for %s: track %s", track.full_name, item.get("id"))
                return JamendoMatch(
                    download_url=item["audiodownload"],
                    license_url=item.get("license_ccurl") or None,
                    share_url=item.get("shareurl") or None,
                    duration=int(item.get("duration") or 0),
                )
        return None


jamendo = JamendoService()
