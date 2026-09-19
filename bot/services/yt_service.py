import asyncio
import os
import re
import urllib.parse
import logging
from typing import Optional, Dict, List
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
            "Accept": "*/*",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        }

    def _generate_queries(self, artist: str, title: str) -> List[str]:
        """Генерирует умные варианты запросов"""
        clean_artist = re.sub(r'[_\-\(\)\[\]]', ' ', artist).strip()
        clean_title = re.sub(r'[_\-\(\)\[\]]', ' ', title).strip()
        
        queries = [
            f"{clean_artist} {clean_title}".strip(),
            clean_title.strip()  # Искать чисто по названию, если автор на латинице (например Zaret_khan)
        ]
        
        # Удаляем дубли и пустые строки
        result = []
        for q in queries:
            q = re.sub(r'\s+', ' ', q).strip()
            if q and q not in result:
                result.append(q)
        return result

    async def _download_file(self, session: aiohttp.ClientSession, url: str, referer: str, file_path: str) -> bool:
        headers = self.headers.copy()
        headers["Referer"] = referer

        try:
            timeout = aiohttp.ClientTimeout(total=25)
            async with session.get(url, headers=headers, timeout=timeout, allow_redirects=True) as resp:
                if resp.status != 200:
                    return False

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

                # Если файл больше 500 КБ — это 100% полная песня
                if size > 500 * 1024:
                    logger.info(f"Successfully downloaded full MP3 ({round(size / 1024 / 1024, 2)} MB)")
                    return True
                else:
                    if os.path.exists(file_path):
                        os.remove(file_path)
        except Exception as e:
            logger.warning(f"Download stream error: {e}")
            if os.path.exists(file_path):
                os.remove(file_path)
        return False

    async def _try_hitmo(self, session: aiohttp.ClientSession, query: str, file_path: str) -> bool:
        try:
            encoded = urllib.parse.quote(query)
            url = f"https://rus.hitmotop.com/search?q={encoded}"
            headers = self.headers.copy()
            headers["Referer"] = "https://rus.hitmotop.com/"

            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    return False
                html = await resp.text()

            # Ищем любые кнопки скачивания или прямые mp3
            links = []
            for tag in re.findall(r'<a\s+[^>]*class=["\'][^"\']*track__download-btn[^"\']*["\'][^>]*>', html):
                href_match = re.search(r'href=["\']([^"\']+)["\']', tag)
                if href_match:
                    links.append(href_match.group(1))

            if not links:
                links = re.findall(r'href=["\']([^"\']+/get/track/[^"\']+)["\']', html)

            for link in links[:3]:
                dl_url = link if link.startswith("http") else f"https://rus.hitmotop.com{link}"
                if await self._download_file(session, dl_url, "https://rus.hitmotop.com/", file_path):
                    logger.info(f"Hitmo found track for query: '{query}'")
                    return True
        except Exception as e:
            logger.warning(f"Hitmo error: {e}")
        return False

    async def _try_mp3party(self, session: aiohttp.ClientSession, query: str, file_path: str) -> bool:
        try:
            encoded = urllib.parse.quote(query)
            url = f"https://mp3party.net/search?q={encoded}"
            headers = self.headers.copy()
            headers["Referer"] = "https://mp3party.net/"

            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    return False
                html = await resp.text()

            links = re.findall(r'href=["\'](/download/\d+)["\']', html)
            for link in links[:3]:
                dl_url = f"https://mp3party.net{link}"
                if await self._download_file(session, dl_url, "https://mp3party.net/", file_path):
                    logger.info(f"Mp3Party found track for query: '{query}'")
                    return True
        except Exception as e:
            logger.warning(f"Mp3Party error: {e}")
        return False

    async def _try_drivemusic(self, session: aiohttp.ClientSession, query: str, file_path: str) -> bool:
        try:
            encoded = urllib.parse.quote(query)
            url = f"https://drivemusic.me/?do=search&subaction=search&story={encoded}"
            headers = self.headers.copy()
            headers["Referer"] = "https://drivemusic.me/"

            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    return False
                html = await resp.text()

            links = re.findall(r'href=["\']((?:https://drivemusic\.me)?/dl/[^"\']+)["\']', html)
            for link in links[:3]:
                dl_url = link if link.startswith("http") else f"https://drivemusic.me{link}"
                if await self._download_file(session, dl_url, "https://drivemusic.me/", file_path):
                    logger.info(f"DriveMusic found track for query: '{query}'")
                    return True
        except Exception as e:
            logger.warning(f"DriveMusic error: {e}")
        return False

    async def download_track(self, artist: str, title: str) -> Optional[Dict[str, str]]:
        queries = self._generate_queries(artist, title)
        file_path = os.path.join(DOWNLOAD_DIR, f"{abs(hash(artist + title))}.mp3")

        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(headers=self.headers, timeout=timeout) as session:
            for q in queries:
                logger.info(f"Searching full MP3 for: '{q}'")
                
                # 1. Hitmo
                if await self._try_hitmo(session, q, file_path):
                    return {"file_path": file_path, "title": title, "artist": artist, "duration": 0}

                # 2. Mp3Party
                if await self._try_mp3party(session, q, file_path):
                    return {"file_path": file_path, "title": title, "artist": artist, "duration": 0}

                # 3. DriveMusic
                if await self._try_drivemusic(session, q, file_path):
                    return {"file_path": file_path, "title": title, "artist": artist, "duration": 0}

        return None


yt_service = DirectMusicDownloader()
