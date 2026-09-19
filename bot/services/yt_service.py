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

# Проверенные рабочие ключи SoundCloud API
SOUNDCLOUD_CLIENT_IDS = [
    "iZIs9mchVcX5lhVR1EzGCcyupzgQIbtm",
    "2t9loNfh0ekOfbnfq6VBesetl3kKuwnT",
    "a3e059563d7fd3372b49b37f00a00bcf",
]

PIPED_INSTANCES = [
    "https://api.piped.private.coffee",
    "https://pipedapi.leptons.xyz",
    "https://pipedapi.tokhmi.xyz",
]


class IronMusicDownloader:
    def __init__(self):
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
        }

    def _clean(self, text: str) -> str:
        t = text.replace("_", " ").replace("-", " ")
        t = re.sub(r'\(.*?\)|\[.*?\]', '', t)
        t = re.sub(r'\s+', ' ', t).strip()
        return t

    async def _download_file(self, session: aiohttp.ClientSession, url: str, file_path: str) -> bool:
        try:
            timeout = aiohttp.ClientTimeout(total=45)
            async with session.get(url, headers=self.headers, timeout=timeout, allow_redirects=True) as resp:
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
                    logger.info(f"Full track saved: {round(size / 1024 / 1024, 2)} MB")
                    return True
                else:
                    if os.path.exists(file_path):
                        os.remove(file_path)
        except Exception as e:
            logger.warning(f"Download stream error: {e}")
            if os.path.exists(file_path):
                os.remove(file_path)
        return False

    async def _try_soundcloud(self, session: aiohttp.ClientSession, query: str, file_path: str) -> bool:
        """Скачивание полного трека через SoundCloud CDN (без блокировок дата-центров)"""
        for client_id in SOUNDCLOUD_CLIENT_IDS:
            try:
                encoded_q = urllib.parse.quote(query)
                search_url = (
                    f"https://api-v2.soundcloud.com/search/tracks"
                    f"?q={encoded_q}&client_id={client_id}&limit=5"
                )

                async with session.get(search_url, headers=self.headers, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()

                collection = data.get("collection", [])
                if not collection:
                    continue

                for track in collection:
                    media = track.get("media", {})
                    transcodings = media.get("transcodings", [])

                    # 1. Сначала ищем прямой прогрессивный MP3 поток
                    prog_trans = next(
                        (t for t in transcodings if t.get("format", {}).get("protocol") == "progressive"),
                        None
                    )

                    if prog_trans:
                        stream_info_url = f"{prog_trans['url']}?client_id={client_id}"
                        async with session.get(stream_info_url, headers=self.headers, timeout=aiohttp.ClientTimeout(total=8)) as stream_resp:
                            if stream_resp.status == 200:
                                stream_data = await stream_resp.json()
                                direct_url = stream_data.get("url")
                                if direct_url and await self._download_file(session, direct_url, file_path):
                                    logger.info(f"SoundCloud Direct MP3 SUCCESS for: '{query}'")
                                    return True

                    # 2. Если нет прямого MP3, берем HLS поток и склеиваем через FFmpeg
                    hls_trans = next(
                        (t for t in transcodings if t.get("format", {}).get("protocol") == "hls"),
                        None
                    )
                    if hls_trans:
                        stream_info_url = f"{hls_trans['url']}?client_id={client_id}"
                        async with session.get(stream_info_url, headers=self.headers, timeout=aiohttp.ClientTimeout(total=8)) as stream_resp:
                            if stream_resp.status == 200:
                                stream_data = await stream_resp.json()
                                m3u8_url = stream_data.get("url")
                                if m3u8_url:
                                    cmd = [
                                        "ffmpeg", "-y", "-i", m3u8_url,
                                        "-c:a", "libmp3lame", "-b:a", "192k",
                                        "-vn", file_path
                                    ]
                                    proc = await asyncio.create_subprocess_exec(
                                        *cmd,
                                        stdout=asyncio.subprocess.DEVNULL,
                                        stderr=asyncio.subprocess.DEVNULL
                                    )
                                    await proc.communicate()

                                    if os.path.exists(file_path) and os.path.getsize(file_path) > 400 * 1024:
                                        logger.info(f"SoundCloud HLS SUCCESS for: '{query}'")
                                        return True

            except Exception as e:
                logger.warning(f"SoundCloud attempt error with key {client_id}: {e}")
                continue

        return False

    async def _try_piped(self, session: aiohttp.ClientSession, query: str, file_path: str) -> bool:
        """Резерв: Piped API (YouTube звук через выделенные прокси-сервера)"""
        for instance in PIPED_INSTANCES:
            try:
                encoded = urllib.parse.quote(query)
                search_url = f"{instance}/search?q={encoded}&filter=music_songs"

                async with session.get(search_url, headers=self.headers, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()

                items = data.get("items", [])
                if not items:
                    continue

                video_url = items[0].get("url", "")
                if "/watch?v=" not in video_url:
                    continue
                video_id = video_url.split("/watch?v=")[1]

                # Получаем потоки
                stream_api = f"{instance}/streams/{video_id}"
                async with session.get(stream_api, headers=self.headers, timeout=aiohttp.ClientTimeout(total=8)) as stream_resp:
                    if stream_resp.status != 200:
                        continue
                    stream_data = await stream_resp.json()

                audio_streams = stream_data.get("audioStreams", [])
                if not audio_streams:
                    continue

                best_audio = audio_streams[0].get("url")
                if best_audio and await self._download_file(session, best_audio, file_path):
                    logger.info(f"Piped ({instance}) SUCCESS for: '{query}'")
                    return True
            except Exception as e:
                logger.warning(f"Piped {instance} error: {e}")
                continue

        return False

    async def download_track(self, artist: str, title: str) -> Optional[Dict[str, str]]:
        clean_artist = self._clean(artist)
        clean_title = self._clean(title)

        queries = [
            f"{clean_artist} {clean_title}".strip(),
            clean_title.strip()
        ]

        file_path = os.path.join(DOWNLOAD_DIR, f"{abs(hash(artist + title))}.mp3")

        timeout = aiohttp.ClientTimeout(total=50)
        async with aiohttp.ClientSession(headers=self.headers, timeout=timeout) as session:
            for q in queries:
                logger.info(f"Searching SoundCloud for '{q}'...")
                if await self._try_soundcloud(session, q, file_path):
                    return {"file_path": file_path, "title": title, "artist": artist, "duration": 0}

                logger.info(f"Searching Piped for '{q}'...")
                if await self._try_piped(session, q, file_path):
                    return {"file_path": file_path, "title": title, "artist": artist, "duration": 0}

        return None


yt_service = IronMusicDownloader()
