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


class ResilientMusicDownloader:
    def __init__(self):
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        # Независимые шлюзы YouTube (не банятся Google)
        self.invidious_instances = [
            "https://inv.nadeko.net",
            "https://invidious.nerdvpn.de",
            "https://inv.tux.pizza",
        ]

    def _clean(self, text: str) -> str:
        t = text.replace("_", " ").replace("-", " ")
        t = re.sub(r'\(.*?\)|\[.*?\]', '', t)
        t = re.sub(r'\s+', ' ', t).strip()
        return t

    async def _download_stream(self, session: aiohttp.ClientSession, url: str, file_path: str, referer: str = "") -> bool:
        headers = self.headers.copy()
        if referer:
            headers["Referer"] = referer

        try:
            timeout = aiohttp.ClientTimeout(total=40)
            async with session.get(url, headers=headers, timeout=timeout, allow_redirects=True) as resp:
                if resp.status != 200:
                    return False

                with open(file_path, "wb") as f:
                    size = 0
                    while True:
                        chunk = await resp.content.read(1024 * 64)
                        if not chunk:
                            break
                        f.write(chunk)
                        size += len(chunk)

                if size > 400 * 1024:  # Больше 400 КБ - полная песня
                    logger.info(f"Full audio downloaded successfully: {round(size / 1024 / 1024, 2)} MB")
                    return True
                else:
                    if os.path.exists(file_path):
                        os.remove(file_path)
        except Exception as e:
            logger.warning(f"Download stream error: {e}")
            if os.path.exists(file_path):
                os.remove(file_path)
        return False

    async def _try_sefon(self, session: aiohttp.ClientSession, query: str, file_path: str) -> bool:
        """Поиск по базе Sefon (без защиты Cloudflare)"""
        try:
            encoded = urllib.parse.quote(query)
            search_url = f"https://sefon.pro/search/?q={encoded}"

            async with session.get(search_url, headers=self.headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return False
                html = await resp.text()

            # Ищем прямые ссылки на скачивание
            matches = re.findall(r'href=["\'](/download/mp3/\d+/)["\']', html)
            for link in matches[:2]:
                dl_url = f"https://sefon.pro{link}"
                if await self._download_stream(session, dl_url, file_path, "https://sefon.pro/"):
                    logger.info(f"Sefon SUCCESS for: '{query}'")
                    return True
        except Exception as e:
            logger.warning(f"Sefon error: {e}")
        return False

    async def _try_invidious(self, session: aiohttp.ClientSession, query: str, file_path: str) -> bool:
        """Загрузка через Invidious-шлюз (YouTube без бана по IP)"""
        for instance in self.invidious_instances:
            try:
                encoded = urllib.parse.quote(query)
                search_api = f"{instance}/api/v1/search?q={encoded}&type=video"

                async with session.get(search_api, headers=self.headers, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status != 200:
                        continue
                    results = await resp.json()

                if not results or not isinstance(results, list):
                    continue

                video_id = results[0].get("videoId")
                if not video_id:
                    continue

                # Качаем аудиопоток через локальный прокси инстанса
                stream_url = f"{instance}/latest_version?id={video_id}&itag=140&local=true"
                if await self._download_stream(session, stream_url, file_path):
                    logger.info(f"Invidious ({instance}) SUCCESS for: '{query}'")
                    return True
            except Exception as e:
                logger.warning(f"Invidious ({instance}) error: {e}")
                continue
        return False

    async def download_track(self, artist: str, title: str) -> Optional[Dict[str, str]]:
        clean_artist = self._clean(artist)
        clean_title = self._clean(title)
        
        # Варианты поисковых запросов
        queries = [
            f"{clean_artist} {clean_title}".strip(),
            clean_title.strip()
        ]

        file_path = os.path.join(DOWNLOAD_DIR, f"{abs(hash(artist + title))}.mp3")

        timeout = aiohttp.ClientTimeout(total=45)
        async with aiohttp.ClientSession(headers=self.headers, timeout=timeout) as session:
            for q in queries:
                logger.info(f"Trying Sefon for '{q}'...")
                if await self._try_sefon(session, q, file_path):
                    return {"file_path": file_path, "title": title, "artist": artist, "duration": 0}

                logger.info(f"Trying Invidious Proxy for '{q}'...")
                if await self._try_invidious(session, q, file_path):
                    return {"file_path": file_path, "title": title, "artist": artist, "duration": 0}

        return None


yt_service = ResilientMusicDownloader()
