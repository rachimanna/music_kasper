import asyncio
import os
import re
import urllib.parse
import logging
from typing import Optional, Dict
import aiohttp
import yt_dlp

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = "/tmp/music_cache"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


class UltimateMusicDownloader:
    def __init__(self):
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        }

    def _get_search_queries(self, raw_query: str) -> list[str]:
        # Очищаем от подчеркиваний и мусора
        cleaned = raw_query.replace("_", " ").replace("-", " ")
        cleaned = re.sub(r'\(.*?\)|\[.*?\]', '', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()

        queries = [cleaned]
        words = cleaned.split()

        # Если автор был на латинице (Zaret khan Моника), добавляем поиск чисто по названию песни
        if len(words) >= 2:
            title_only = " ".join(words[1:])  # отрезаем первое слово (автора)
            if len(title_only) >= 3:
                queries.append(title_only)

        return queries

    async def _download_stream(self, session: aiohttp.ClientSession, url: str, referer: str, file_path: str) -> bool:
        headers = self.headers.copy()
        headers["Referer"] = referer

        try:
            timeout = aiohttp.ClientTimeout(total=30)
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

                # Если трек весит больше 500 КБ — это 100% полная песня
                if size > 500 * 1024:
                    logger.info(f"Full MP3 successfully downloaded ({round(size / 1024 / 1024, 2)} MB)")
                    return True
                else:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                    return False
        except Exception as e:
            logger.warning(f"Stream error from {url}: {e}")
            if os.path.exists(file_path):
                os.remove(file_path)
            return False

    async def _try_hitmo(self, session: aiohttp.ClientSession, query: str, file_path: str) -> bool:
        try:
            encoded = urllib.parse.quote(query)
            search_url = f"https://rus.hitmotop.com/search?q={encoded}"
            headers = self.headers.copy()
            headers["Referer"] = "https://rus.hitmotop.com/"

            async with session.get(search_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return False
                html = await resp.text()

            # Точный поиск прямых MP3-ссылок Hitmo вида /get/track/123456.mp3
            links = re.findall(r'(/get/track/\d+\.mp3)', html)
            if not links:
                links = re.findall(r'href=["\']([^"\']+/get/track/[^"\']+)["\']', html)

            for link in links[:2]:
                dl_url = link if link.startswith("http") else f"https://rus.hitmotop.com{link}"
                if await self._download_stream(session, dl_url, "https://rus.hitmotop.com/", file_path):
                    logger.info(f"Hitmo hit for query: '{query}'")
                    return True
        except Exception as e:
            logger.warning(f"Hitmo search error: {e}")
        return False

    async def _try_muzofond(self, session: aiohttp.ClientSession, query: str, file_path: str) -> bool:
        try:
            encoded = urllib.parse.quote(query)
            search_url = f"https://muzofond.fm/search/{encoded}"
            headers = self.headers.copy()
            headers["Referer"] = "https://muzofond.fm/"

            async with session.get(search_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return False
                html = await resp.text()

            links = re.findall(r'data-url=["\'](https?://[^"\']+\.mp3[^"\']*)["\']', html)
            for dl_url in links[:2]:
                if await self._download_stream(session, dl_url, "https://muzofond.fm/", file_path):
                    logger.info(f"Muzofond hit for query: '{query}'")
                    return True
        except Exception as e:
            logger.warning(f"Muzofond search error: {e}")
        return False

    def _download_yt_tv(self, query: str, file_path: str) -> bool:
        """Скачивание через YouTube TV клиент (не банится Render'ом)"""
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": file_path.replace(".mp3", ".%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "default_search": "ytsearch1:",
            "extractor_args": {
                "youtube": {
                    "player_client": ["tv_embedded", "tv"],
                }
            },
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([query])

            if os.path.exists(file_path) and os.path.getsize(file_path) > 400 * 1024:
                logger.info(f"YouTube TV downloaded full track for '{query}'")
                return True
        except Exception as e:
            logger.warning(f"YouTube TV error: {e}")
        return False

    async def download_track(self, query: str) -> Optional[Dict[str, str]]:
        queries_to_try = self._get_search_queries(query)
        file_path = os.path.join(DOWNLOAD_DIR, f"{abs(hash(query))}.mp3")

        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(headers=self.headers, timeout=timeout) as session:
            # 1. Ищем в Hitmo (по полному имени, потом по названию песни)
            for q in queries_to_try:
                if await self._try_hitmo(session, q, file_path):
                    return {"file_path": file_path, "title": query, "artist": "Music", "duration": 0}

            # 2. Ищем в Muzofond
            for q in queries_to_try:
                if await self._try_muzofond(session, q, file_path):
                    return {"file_path": file_path, "title": query, "artist": "Music", "duration": 0}

        # 3. Железный резерв: YouTube TV
        loop = asyncio.get_running_loop()
        ok = await loop.run_in_executor(None, self._download_yt_tv, queries_to_try[0], file_path)
        if ok and os.path.exists(file_path):
            return {"file_path": file_path, "title": query, "artist": "Music", "duration": 0}

        return None


yt_service = UltimateMusicDownloader()
