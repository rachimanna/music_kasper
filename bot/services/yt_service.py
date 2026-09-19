import asyncio
import os
import re
import urllib.parse
import logging
from typing import Optional, Dict
import aiohttp

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = "/tmp/music_cache"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


class DirectMusicDownloader:
    def __init__(self):
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        }

    def _clean_query(self, query: str) -> str:
        # Убираем подчеркивания и лишние спецсимволы, ломающие поиск
        q = query.replace("_", " ").replace("-", " ")
        q = re.sub(r'\(.*?\)|\[.*?\]', '', q)
        q = re.sub(r'\s+', ' ', q).strip()
        return q

    async def _download_file(self, session: aiohttp.ClientSession, url: str, file_path: str) -> bool:
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return False
                with open(file_path, "wb") as f:
                    while True:
                        chunk = await resp.content.read(1024 * 64)
                        if not chunk:
                            break
                        f.write(chunk)
            
            # Проверяем, что скачалась именно полноценная песня (> 300 КБ)
            if os.path.exists(file_path) and os.path.getsize(file_path) > 300 * 1024:
                return True
        except Exception as e:
            logger.error(f"Download stream error: {e}")
        return False

    async def _try_muzofond(self, session: aiohttp.ClientSession, query: str, file_path: str) -> bool:
        try:
            encoded = urllib.parse.quote(query)
            url = f"https://muzofond.fm/search/{encoded}"
            async with session.get(url) as resp:
                if resp.status != 200:
                    return False
                html = await resp.text()

            # Ищем прямые data-url ссылки на MP3
            matches = re.findall(r'data-url=["\']([^"\']+\.mp3[^"\']*)["\']', html)
            if not matches:
                matches = re.findall(r'data-url=["\']([^"\']+)["\']', html)

            for match in matches[:3]:
                dl_url = match if match.startswith("http") else f"https://muzofond.fm{match}"
                if await self._download_file(session, dl_url, file_path):
                    logger.info(f"Successfully downloaded from Muzofond: {query}")
                    return True
        except Exception as e:
            logger.warning(f"Muzofond error: {e}")
        return False

    async def _try_hitmo(self, session: aiohttp.ClientSession, query: str, file_path: str) -> bool:
        try:
            encoded = urllib.parse.quote(query)
            url = f"https://rus.hitmotop.com/search?q={encoded}"
            async with session.get(url) as resp:
                if resp.status != 200:
                    return False
                html = await resp.text()

            matches = re.findall(r'href=["\']([^"\']+)["\'][^>]*class=["\'][^"\']*track__download-btn', html)
            if not matches:
                matches = re.findall(r'class=["\'][^"\']*track__download-btn[^"\']*["\'][^>]*href=["\']([^"\']+)["\']', html)

            for match in matches[:3]:
                dl_url = match if match.startswith("http") else f"https://rus.hitmotop.com{match}"
                if await self._download_file(session, dl_url, file_path):
                    logger.info(f"Successfully downloaded from Hitmo: {query}")
                    return True
        except Exception as e:
            logger.warning(f"Hitmo error: {e}")
        return False

    async def _try_mp3party(self, session: aiohttp.ClientSession, query: str, file_path: str) -> bool:
        try:
            encoded = urllib.parse.quote(query)
            url = f"https://mp3party.net/search?q={encoded}"
            async with session.get(url) as resp:
                if resp.status != 200:
                    return False
                html = await resp.text()

            matches = re.findall(r'href=["\'](/download/[^"\']+)["\']', html)
            for match in matches[:3]:
                dl_url = f"https://mp3party.net{match}"
                if await self._download_file(session, dl_url, file_path):
                    logger.info(f"Successfully downloaded from Mp3Party: {query}")
                    return True
        except Exception as e:
            logger.warning(f"Mp3Party error: {e}")
        return False

    async def download_track(self, query: str) -> Optional[Dict[str, str]]:
        clean_q = self._clean_query(query)
        file_path = os.path.join(DOWNLOAD_DIR, f"{abs(hash(clean_q))}.mp3")

        timeout = aiohttp.ClientTimeout(total=25)
        async with aiohttp.ClientSession(headers=self.headers, timeout=timeout) as session:
            # 1. Первая база: Muzofond
            if await self._try_muzofond(session, clean_q, file_path):
                return {"file_path": file_path, "title": clean_q, "artist": "Music", "duration": 0}

            # 2. Вторая база: Hitmo
            if await self._try_hitmo(session, clean_q, file_path):
                return {"file_path": file_path, "title": clean_q, "artist": "Music", "duration": 0}

            # 3. Третья база: Mp3Party
            if await self._try_mp3party(session, clean_q, file_path):
                return {"file_path": file_path, "title": clean_q, "artist": "Music", "duration": 0}

        return None


yt_service = DirectMusicDownloader()
