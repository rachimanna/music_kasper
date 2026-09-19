import asyncio
import os
import logging
from typing import Optional, Dict
import yt_dlp

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = "/tmp/music_cache"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


class YouTubeDownloader:
    @staticmethod
    def _download_sync(query: str) -> Optional[Dict[str, str]]:
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": f"{DOWNLOAD_DIR}/%(id)s.%(ext)s",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "default_search": "ytsearch1:",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(query, download=True)
                if "entries" in info:
                    info = info["entries"][0]

                track_id = info.get("id")
                file_path = f"{DOWNLOAD_DIR}/{track_id}.mp3"

                return {
                    "file_path": file_path,
                    "title": info.get("title", "Unknown"),
                    "artist": info.get("uploader", "Unknown"),
                    "duration": int(info.get("duration", 0)),
                }
        except Exception as e:
            logger.error(f"yt-dlp download error for query '{query}': {e}")
            return None

    async def download_track(self, query: str) -> Optional[Dict[str, str]]:
        """Скачивает аудио в фоновом потоке, чтобы не вешать бота"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._download_sync, query)


yt_service = YouTubeDownloader()
