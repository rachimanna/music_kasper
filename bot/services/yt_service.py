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


class MusicDownloader:
    def __init__(self):
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        }

    async def _download_from_hitmo(self, query: str) -> Optional[Dict[str, str]]:
        """Скачивает полный трек напрямую из MP3 базы без блокировок дата-центров"""
        encoded_query = urllib.parse.quote(query)
        search_url = f"https://rus.hitmotop.com/search?q={encoded_query}"

        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(headers=self.headers, timeout=timeout) as session:
                async with session.get(search_url) as resp:
                    if resp.status != 200:
                        return None
                    html_text = await resp.text()

                # Находим прямую ссылку на скачивание MP3
                matches = re.findall(r'href="([^"]+)"\s+class="track__download-btn"', html_text)
                if not matches:
                    matches = re.findall(r'class="track__download-btn"\s+href="([^"]+)"', html_text)

                if not matches:
                    return None

                download_url = matches[0]
                if not download_url.startswith("http"):
                    download_url = f"https://rus.hitmotop.com{download_url}"

                file_path = os.path.join(DOWNLOAD_DIR, f"{abs(hash(query))}.mp3")

                # Скачиваем полный MP3 файл
                async with session.get(download_url) as dl_resp:
                    if dl_resp.status != 200:
                        return None
                    with open(file_path, "wb") as f:
                        while True:
                            chunk = await dl_resp.content.read(1024 * 64)
                            if not chunk:
                                break
                            f.write(chunk)

                # Проверяем, что файл скачался и он больше 500 КБ (полный трек)
                if os.path.exists(file_path) and os.path.getsize(file_path) > 500 * 1024:
                    logger.info(f"Downloaded full MP3 directly for '{query}'")
                    return {
                        "file_path": file_path,
                        "title": query,
                        "artist": "Music",
                        "duration": 0,
                    }
        except Exception as e:
            logger.warning(f"Direct MP3 search error for '{query}': {e}")
        return None

    def _download_soundcloud_sync(self, query: str) -> Optional[Dict[str, str]]:
        """Резервный источник: SoundCloud (SoundCloud не банит дата-центры)"""
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": f"{DOWNLOAD_DIR}/sc_%(id)s.%(ext)s",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "default_search": "scsearch1:",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(query, download=True)
                if not info:
                    return None
                if "entries" in info and info["entries"]:
                    info = info["entries"][0]

                track_id = info.get("id")
                file_path = f"{DOWNLOAD_DIR}/sc_{track_id}.mp3"

                if os.path.exists(file_path) and os.path.getsize(file_path) > 200 * 1024:
                    logger.info(f"Downloaded from SoundCloud: '{query}'")
                    return {
                        "file_path": file_path,
                        "title": info.get("title", query),
                        "artist": info.get("uploader", "Music"),
                        "duration": int(info.get("duration", 0)),
                    }
        except Exception as e:
            logger.warning(f"SoundCloud error for '{query}': {e}")
        return None

    async def download_track(self, query: str) -> Optional[Dict[str, str]]:
        # 1. Сначала пробуем моментальную прямую базу MP3
        result = await self._download_from_hitmo(query)
        if result:
            return result

        # 2. Если там нет — ищем в SoundCloud
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._download_soundcloud_sync, query)


yt_service = MusicDownloader()
