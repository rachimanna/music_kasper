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

INVIDIOUS_INSTANCES = [
    "https://inv.nadeko.net",
    "https://yewtu.be",
    "https://invidious.nerdvpn.de",
    "https://inv.tux.pizza",
]

PIPED_INSTANCES = [
    "https://pipedapi.kavin.rocks",
    "https://api.piped.private.coffee",
    "https://pipedapi.leptons.xyz",
]

COBALT_INSTANCES = [
    "https://cobaltapi.canine.tools",
    "https://api.cobalt.tools",
]


class GlobalMusicDownloader:
    def __init__(self):
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
        }

    def _clean_query(self, text: str) -> str:
        t = text.replace("_", " ").replace("-", " ")
        t = re.sub(r'\(.*?\)|\[.*?\]', '', t)
        t = re.sub(r'\s+', ' ', t).strip()
        return t

    async def _stream_to_file(self, session: aiohttp.ClientSession, url: str, out_file: str) -> bool:
        try:
            timeout = aiohttp.ClientTimeout(total=50)
            async with session.get(url, headers=self.headers, timeout=timeout, allow_redirects=True) as resp:
                if resp.status != 200:
                    return False

                with open(out_file, "wb") as f:
                    size = 0
                    while True:
                        chunk = await resp.content.read(1024 * 64)
                        if not chunk:
                            break
                        f.write(chunk)
                        size += len(chunk)

                if size > 300 * 1024:
                    logger.info(f"Stream saved ({round(size / 1024 / 1024, 2)} MB)")
                    return True
                else:
                    if os.path.exists(out_file):
                        os.remove(out_file)
        except Exception as e:
            logger.warning(f"Stream error from {url}: {e}")
            if os.path.exists(out_file):
                os.remove(out_file)
        return False

    async def _convert_to_mp3(self, input_file: str, output_mp3: str) -> bool:
        try:
            cmd = [
                "ffmpeg", "-y", "-i", input_file,
                "-vn", "-c:a", "libmp3lame", "-b:a", "192k",
                output_mp3
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            await proc.communicate()
            return os.path.exists(output_mp3) and os.path.getsize(output_mp3) > 300 * 1024
        except Exception as e:
            logger.error(f"FFmpeg error: {e}")
            return False

    async def _get_video_id(self, session: aiohttp.ClientSession, query: str) -> Optional[str]:
        encoded = urllib.parse.quote(query)

        # 1. Поиск напрямую через открытый интерфейс YouTube
        try:
            yt_url = f"https://www.youtube.com/results?search_query={encoded}"
            async with session.get(yt_url, headers=self.headers, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    ids = re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', text)
                    if ids:
                        logger.info(f"Found YouTube ID '{ids[0]}' for query '{query}'")
                        return ids[0]
        except Exception as e:
            logger.warning(f"YouTube search scrape error: {e}")

        # 2. Поиск через Invidious API
        for inst in INVIDIOUS_INSTANCES:
            try:
                api_url = f"{inst}/api/v1/search?q={encoded}&type=video"
                async with session.get(api_url, headers=self.headers, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data and isinstance(data, list) and len(data) > 0:
                            v_id = data[0].get("videoId")
                            if v_id:
                                logger.info(f"Found Video ID '{v_id}' via {inst}")
                                return v_id
            except Exception:
                continue

        return None

    async def _try_cobalt(self, session: aiohttp.ClientSession, video_id: str, out_file: str) -> bool:
        for c_inst in COBALT_INSTANCES:
            try:
                payload = {
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                    "downloadMode": "audio",
                    "audioFormat": "mp3",
                }
                headers = {"Accept": "application/json", "Content-Type": "application/json"}
                async with session.post(f"{c_inst}/", json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=12)) as resp:
                    if resp.status == 200:
                        res = await resp.json()
                        stream_url = res.get("url")
                        if stream_url and await self._stream_to_file(session, stream_url, out_file):
                            logger.info(f"Cobalt SUCCESS ({c_inst})")
                            return True
            except Exception as e:
                logger.warning(f"Cobalt error ({c_inst}): {e}")
                continue
        return False

    async def _try_invidious(self, session: aiohttp.ClientSession, video_id: str, out_file: str) -> bool:
        temp_file = f"{out_file}.tmp"
        for inst in INVIDIOUS_INSTANCES:
            try:
                # itag 140 = m4a (AAC), itag 251 = webm (Opus)
                for itag in ["140", "251"]:
                    stream_url = f"{inst}/latest_version?id={video_id}&itag={itag}&local=true"
                    if await self._stream_to_file(session, stream_url, temp_file):
                        if await self._convert_to_mp3(temp_file, out_file):
                            logger.info(f"Invidious SUCCESS ({inst})")
                            if os.path.exists(temp_file):
                                os.remove(temp_file)
                            return True
            except Exception as e:
                logger.warning(f"Invidious error ({inst}): {e}")
                continue
            finally:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
        return False

    async def _try_piped(self, session: aiohttp.ClientSession, video_id: str, out_file: str) -> bool:
        temp_file = f"{out_file}.tmp"
        for inst in PIPED_INSTANCES:
            try:
                stream_api = f"{inst}/streams/{video_id}"
                async with session.get(stream_api, headers=self.headers, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()

                audio_streams = data.get("audioStreams", [])
                if not audio_streams:
                    continue

                best_url = audio_streams[0].get("url")
                if best_url and await self._stream_to_file(session, best_url, temp_file):
                    if await self._convert_to_mp3(temp_file, out_file):
                        logger.info(f"Piped SUCCESS ({inst})")
                        if os.path.exists(temp_file):
                            os.remove(temp_file)
                        return True
            except Exception as e:
                logger.warning(f"Piped error ({inst}): {e}")
                continue
            finally:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
        return False

    async def download_track(self, artist: str, title: str) -> Optional[Dict[str, str]]:
        clean_artist = self._clean_query(artist)
        clean_title = self._clean_query(title)

        queries = [
            f"{clean_artist} {clean_title}".strip(),
            clean_title.strip()
        ]

        final_mp3 = os.path.join(DOWNLOAD_DIR, f"{abs(hash(artist + title))}.mp3")

        # КЛЮЧЕВОЙ МОМЕНТ: ssl=False отключает ошибку сертификатов на Render!
        connector = aiohttp.TCPConnector(ssl=False)
        timeout = aiohttp.ClientTimeout(total=60)

        async with aiohttp.ClientSession(connector=connector, headers=self.headers, timeout=timeout) as session:
            for q in queries:
                logger.info(f"Looking for YouTube ID for: '{q}'")
                video_id = await self._get_video_id(session, q)
                if not video_id:
                    continue

                # 1. Пробуем скоростной Cobalt
                if await self._try_cobalt(session, video_id, final_mp3):
                    return {"file_path": final_mp3, "title": title, "artist": artist, "duration": 0}

                # 2. Пробуем Invidious прокси
                if await self._try_invidious(session, video_id, final_mp3):
                    return {"file_path": final_mp3, "title": title, "artist": artist, "duration": 0}

                # 3. Пробуем Piped прокси
                if await self._try_piped(session, video_id, final_mp3):
                    return {"file_path": final_mp3, "title": title, "artist": artist, "duration": 0}

        return None


yt_service = GlobalMusicDownloader()
