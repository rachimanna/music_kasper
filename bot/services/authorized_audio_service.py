"""
Скачивание и конвертация полных аудиофайлов из легальных источников:
- свой сервер (шаблон AUDIO_SOURCE_URL_TEMPLATE с полями {id}, {artist}, {title});
- Jamendo (ссылку передаёт delivery через download_from_url).
"""
import asyncio
import logging
import shutil
import string
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import aiohttp

from bot.config import config
from bot.services.base import Track

logger = logging.getLogger(__name__)

ALLOWED_FIELDS = {"id", "artist", "title"}
BITRATE_STEPS = (320, 256, 192, 160, 128, 96, 64)


@dataclass
class DownloadedAudio:
    path: Path
    duration: int
    size: int


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Cannot remove %s: %s", path, exc)


class AuthorizedAudioService:
    def __init__(self) -> None:
        self.template = config.AUDIO_SOURCE_URL_TEMPLATE.strip()
        self.download_dir = config.download_path
        self._session: Optional[aiohttp.ClientSession] = None
        self._semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_DOWNLOADS)

    # ---------- настройка ----------

    def configured(self) -> bool:
        return bool(self.template)

    def validate_template(self) -> Optional[str]:
        """Текст ошибки, если шаблон неправильный, иначе None."""
        if not self.template:
            return "AUDIO_SOURCE_URL_TEMPLATE is empty"
        if not self.template.startswith(("http://", "https://")):
            return "AUDIO_SOURCE_URL_TEMPLATE must start with http:// or https://"
        try:
            fields = {name for _, name, _, _ in string.Formatter().parse(self.template) if name is not None}
        except ValueError as exc:
            return f"AUDIO_SOURCE_URL_TEMPLATE is malformed: {exc}"
        unknown = fields - ALLOWED_FIELDS
        if unknown:
            return f"Unknown fields in AUDIO_SOURCE_URL_TEMPLATE: {', '.join(sorted(unknown))}"
        return None

    def build_url(self, track: Track) -> Optional[str]:
        error = self.validate_template()
        if error:
            logger.error(error)
            return None
        # Кодируем значения, чтобы «AC/DC», «&», «#» и пробелы не ломали ссылку.
        return self.template.format(
            id=quote(str(track.id), safe=""),
            artist=quote(track.artist, safe=""),
            title=quote(track.title, safe=""),
        )

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"User-Agent": "MusicKasperBot/2.0", "Accept": "*/*"},
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # ---------- основной метод ----------

    async def download_track(self, track: Track) -> Optional[DownloadedAudio]:
        """Полный трек из своего источника (AUDIO_SOURCE_URL_TEMPLATE)."""
        if not self.configured():
            return None
        url = self.build_url(track)
        if not url:
            return None
        return await self.download_from_url(url, track)

    async def download_from_url(self, url: str, track: Track) -> Optional[DownloadedAudio]:
        """Скачивает файл по ссылке и конвертирует в mp3. При ошибке возвращает None и убирает за собой файлы."""
        async with self._semaphore:
            self.download_dir.mkdir(parents=True, exist_ok=True)
            file_id = uuid.uuid4().hex
            source = self.download_dir / f"{file_id}.source"
            mp3 = self.download_dir / f"{file_id}.mp3"
            success = False

            try:
                logger.info("Downloading full track %s: %s", track.id, track.full_name)
                if not await self._download(url, source):
                    return None

                duration = await self._probe_duration(source) or track.duration
                if duration <= 0:
                    logger.error("Cannot determine duration of track %s", track.id)
                    return None

                bitrate = self._pick_bitrate(duration)
                if bitrate is None:
                    logger.error("Track %s is too long (%ss) to fit into Telegram limit", track.id, duration)
                    return None

                if not await self._convert_to_mp3(source, mp3, bitrate, track):
                    return None

                size = mp3.stat().st_size
                if size > config.max_upload_bytes:
                    logger.error("MP3 for track %s is %.1f MB — above Telegram limit", track.id, size / 1048576)
                    return None

                success = True
                return DownloadedAudio(path=mp3, duration=int(duration), size=size)

            except Exception:
                logger.exception("Audio service error for track %s", track.id)
                return None

            finally:
                _unlink(source)
                if not success:
                    _unlink(mp3)

    # ---------- шаги ----------

    async def _download(self, url: str, destination: Path) -> bool:
        partial = destination.with_suffix(destination.suffix + ".part")
        timeout = aiohttp.ClientTimeout(
            total=config.AUDIO_DOWNLOAD_TIMEOUT, connect=30, sock_read=60
        )
        limit = config.max_source_bytes

        try:
            session = await self._get_session()
            async with session.get(url, allow_redirects=True, timeout=timeout) as response:
                if response.status != 200:
                    logger.error("Audio source HTTP %s for %s", response.status, url)
                    return False

                if response.content_length and response.content_length > limit:
                    logger.error("Audio source is too large: %s bytes", response.content_length)
                    return False

                downloaded = 0
                with open(partial, "wb") as output:
                    async for chunk in response.content.iter_chunked(256 * 1024):
                        downloaded += len(chunk)
                        if downloaded > limit:
                            logger.error("Audio source exceeded %s MB", config.MAX_SOURCE_SIZE_MB)
                            return False
                        output.write(chunk)

            if downloaded < 1024:
                logger.error("Downloaded audio is empty (%s bytes)", downloaded)
                return False

            partial.replace(destination)
            return True

        except asyncio.TimeoutError:
            logger.error("Audio download timeout: %s", url)
            return False
        except aiohttp.ClientError as exc:
            logger.error("Audio network error: %s", exc)
            return False
        finally:
            _unlink(partial)

    def _pick_bitrate(self, duration: int) -> Optional[int]:
        """Самый высокий битрейт (не выше настроенного), при котором mp3 влезет в лимит Telegram."""
        max_kbps = config.max_upload_bytes * 8 * 0.95 / duration / 1000
        for kbps in BITRATE_STEPS:
            if kbps <= config.AUDIO_BITRATE_KBPS and kbps <= max_kbps:
                return kbps
        return None

    async def _run(self, *args: str, timeout: int) -> Optional[tuple]:
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            logger.error("%s is not installed", args[0])
            return None

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            logger.error("%s timed out after %ss", args[0], timeout)
            return None
        return process.returncode, stdout, stderr

    async def _probe_duration(self, path: Path) -> int:
        result = await self._run(
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
            timeout=60,
        )
        if not result or result[0] != 0:
            return 0
        try:
            return int(float(result[1].decode().strip()))
        except ValueError:
            return 0

    async def _convert_to_mp3(self, source: Path, destination: Path, kbps: int, track: Track) -> bool:
        result = await self._run(
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(source),
            "-map", "0:a:0", "-vn",
            "-codec:a", "libmp3lame", "-b:a", f"{kbps}k",
            "-map_metadata", "-1",
            "-metadata", f"title={track.title}",
            "-metadata", f"artist={track.artist}",
            "-f", "mp3",
            str(destination),
            timeout=config.FFMPEG_TIMEOUT,
        )
        if not result:
            return False
        returncode, _, stderr = result
        if returncode != 0:
            logger.error("FFmpeg error: %s", stderr.decode(errors="ignore")[-2000:])
            return False
        return destination.exists() and destination.stat().st_size >= 1024


audio_service = AuthorizedAudioService()
