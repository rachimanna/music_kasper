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


class RobustMusicDownloader:
    def __init__(self):
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        }

    def _clean_query(self, query: str) -> str:
        # Заменяем подчеркивания и дефисы на пробелы
        q = query.replace("_", " ").replace("-", " ")
        # Удаляем круглые и квадратные скобки (например, (Official Video), [Remix])
        q = re.sub(r'\(.*?\)|\[.*?\]', '', q)
        # Удаляем странные спецсимволы
        q = re.sub(r'[^\w\s\d]', ' ', q)
        q = re.sub(r'\s+', ' ', q).strip()
        return q

    async def _download_file(self, session: aiohttp.ClientSession, url: str, file_path: str) -> bool:
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with session.get(url, headers=self.headers, timeout=timeout, allow_redirects=True) as resp:
                if resp.status != 200:
                    return False

                # Проверяем, что это аудиофайл, а не страница ошибки или капчи
                content_type = resp.headers.get("Content-Type", "").lower()
                if "html" in content_type or "text" in content_type:
                    return False

                with open(file_path, "wb") as f:
                    size = 0
                    while True:
                        chunk = await resp.content.read(1024 * 64)
                        if not chunk:
                            break
                        f.write(chunk)
                        size += len(chunk)

                # Песня считается полной, если размер больше 800 КБ (не огрызок)
                if size > 800 * 1024:
                    return True
                else:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                    return False
        except Exception as e:
            logger.warning(f"Error streaming from {url}: {e}")
            if os.path.exists(file_path):
                os.remove(file_path)
        return False

    async def _try_drivemusic(self, session: aiohttp.ClientSession, query: str, file_path: str) -> bool:
        try:
            encoded = urllib.parse.quote(query)
            url = f"https://drivemusic.me/?do=search&subaction=search&story={encoded}"
            async with session.get(url, headers=self.headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return False
                html = await resp.text()

            # Ищем прямые ссылки на скачивание треков
            matches = re.findall(r'href=["\']((?:https://drivemusic\.me)?/dl/[^"\']+)["\']', html)
            for link in matches[:3]:
                dl_url = link if link.startswith("http") else f"https://drivemusic.me{link}"
                if await self._download_file(session, dl_url, file_path):
                    logger.info(f"Downloaded full track from DriveMusic: '{query}'")
                    return True
        except Exception as e:
            logger.warning(f"DriveMusic error: {e}")
        return False

    async def _try_mp3uk(self, session: aiohttp.ClientSession, query: str, file_path: str) -> bool:
        try:
            encoded = urllib.parse.quote(query)
            url = f"https://mp3uk.net/index.php?do=search&subaction=search&story={encoded}"
            async with session.get(url, headers=self.headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return False
                html = await resp.text()

            matches = re.findall(r'href=["\']((?:https://mp3uk\.net)?/mp3/files/[^"\']+\.mp3)["\']', html)
            for link in matches[:3]:
                dl_url = link if link.startswith("http") else f"https://mp3uk.net{link}"
                if await self._download_file(session, dl_url, file_path):
                    logger.info(f"Downloaded full track from Mp3UK: '{query}'")
                    return True
        except Exception as e:
            logger.warning(f"Mp3UK error: {e}")
        return False

    async def _try_musmore(self, session: aiohttp.ClientSession, query: str, file_path: str) -> bool:
        try:
            encoded = urllib.parse.quote(query)
            url = f"https://musmore.com/search?q={encoded}"
            async with session.get(url, headers=self.headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return False
                html = await resp.text()

            matches = re.findall(r'href=["\'](/download/[^"\']+)["\']', html)
            for link in matches[:3]:
                dl_url = f"https://musmore.com{link}"
                if await self._download_file(session, dl_url, file_path):
                    logger.info(f"Downloaded full track from Musmore: '{query}'")
                    return True
        except Exception as e:
            logger.warning(f"Musmore error: {e}")
        return False

    async def download_track(self, query: str) -> Optional[Dict[str, str]]:
        clean_q = self._clean_query(query)
        file_path = os.path.join(DOWNLOAD_DIR, f"{abs(hash(clean_q))}.mp3")

        timeout = aiohttp.ClientTimeout(total=35)
        async with aiohttp.ClientSession(headers=self.headers, timeout=timeout) as session:
            # 1. Первая скоростная база (DriveMusic)
            if await self._try_drivemusic(session, clean_q, file_path):
                return {"file_path": file_path, "title": clean_q, "artist": "Music", "duration": 0}

            # 2. Вторая база (Mp3UK)
            if await self._try_mp3uk(session, clean_q, file_path):
                return {"file_path": file_path, "title": clean_q, "artist": "Music", "duration": 0}

            # 3. Третья база (Musmore)
            if await self._try_musmore(session, clean_q, file_path):
                return {"file_path": file_path, "title": clean_q, "artist": "Music", "duration": 0}

        return None


yt_service = RobustMusicDownloader()
