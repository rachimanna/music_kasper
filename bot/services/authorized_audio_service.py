import asyncio
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Optional

import aiohttp

from bot.services.base import Track

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = Path(
    os.getenv("DOWNLOAD_DIR", "/tmp/music_cache")
)
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


class AuthorizedAudioService:
    """
    Сервис получения полного аудиофайла из настроенного
    разрешённого источника.

    В Render нужно будет указать:

    AUDIO_SOURCE_URL_TEMPLATE

    Пример формата:
    https://example.com/audio/{id}.m4a

    Поддерживаются:
    {id}
    {artist}
    {title}
    """

    def __init__(self):
        self.template = os.getenv(
            "AUDIO_SOURCE_URL_TEMPLATE",
            ""
        ).strip()

        # Telegram Bot API имеет ограничения на размер
        # загружаемых файлов. Оставляем запас.
        self.max_bytes = int(
            os.getenv(
                "MAX_AUDIO_BYTES",
                str(49 * 1024 * 1024)
            )
        )

        self.timeout = aiohttp.ClientTimeout(
            total=None,
            connect=30,
            sock_connect=30,
            sock_read=180,
        )

        self.headers = {
            "User-Agent": "MusicKasPerBot/2.0",
            "Accept": "*/*",
        }

    def configured(self) -> bool:
        """
        Проверяет, настроен ли источник полного аудио.
        """

        return bool(self.template)

    @staticmethod
    def _safe_name(value: str) -> str:
        """
        Делает безопасное имя файла.
        """

        value = re.sub(
            r"[^\w\- .()]+",
            "_",
            value,
            flags=re.UNICODE
        )

        value = value.strip(" .")

        return value[:100] or "track"

    def _build_url(self, track: Track) -> Optional[str]:
        """
        Формирует URL полного аудио.
        """

        if not self.configured():
            return None

        try:
            return self.template.format(
                id=track.id,
                artist=track.artist,
                title=track.title,
            )

        except Exception as e:
            logger.error(
                "Failed to build audio URL: %s",
                e
            )
            return None

    async def _download(
        self,
        url: str,
        output: Path
    ) -> bool:
        """
        Скачивает файл потоково, не загружая его
        целиком в RAM.
        """

        temp = output.with_suffix(
            output.suffix + ".part"
        )

        try:

            connector = aiohttp.TCPConnector(
                limit=10,
                ttl_dns_cache=300
            )

            async with aiohttp.ClientSession(
                connector=connector,
                timeout=self.timeout,
                headers=self.headers,
            ) as session:

                async with session.get(
                    url,
                    allow_redirects=True
                ) as response:

                    if response.status != 200:
                        logger.error(
                            "Audio server returned HTTP %s",
                            response.status
                        )
                        return False

                    content_length = response.headers.get(
                        "Content-Length"
                    )

                    if content_length:

                        try:
                            content_length = int(
                                content_length
                            )

                            if content_length > self.max_bytes:
                                logger.error(
                                    "Audio file is too large: %s bytes",
                                    content_length
                                )
                                return False

                        except ValueError:
                            pass

                    size = 0

                    with temp.open("wb") as file:

                        async for chunk in response.content.iter_chunked(
                            256 * 1024
                        ):

                            if not chunk:
                                continue

                            size += len(chunk)

                            if size > self.max_bytes:
                                logger.error(
                                    "Audio exceeded maximum size"
                                )
                                return False

                            file.write(chunk)

                    if size < 64 * 1024:
                        logger.error(
                            "Downloaded audio is too small: %s bytes",
                            size
                        )
                        return False

            temp.replace(output)

            logger.info(
                "Audio downloaded successfully: %.2f MB",
                output.stat().st_size / 1024 / 1024
            )

            return True

        except asyncio.TimeoutError:

            logger.error(
                "Audio download timed out"
            )

            return False

        except aiohttp.ClientError as e:

            logger.error(
                "Audio network error: %s",
                e
            )

            return False

        except Exception as e:

            logger.exception(
                "Audio download failed: %s",
                e
            )

            return False

        finally:

            try:
                if temp.exists():
                    temp.unlink()
            except Exception:
                pass

            if not output.exists():
                try:
                    output.unlink()
                except Exception:
                    pass

    async def download_track(
        self,
        track: Track
    ) -> Optional[Path]:
        """
        Скачивает исходный полный аудиофайл.
        """

        if not self.configured():

            logger.warning(
                "AUDIO_SOURCE_URL_TEMPLATE is not configured"
            )

            return None

        url = self._build_url(track)

        if not url:
            return None

        unique_id = uuid.uuid4().hex

        filename = (
            f"{unique_id}_"
            f"{self._safe_name(track.artist)} - "
            f"{self._safe_name(track.title)}.audio"
        )

        output = DOWNLOAD_DIR / filename

        logger.info(
            "Downloading full track: %s — %s",
            track.artist,
            track.title
        )

        success = await self._download(
            url,
            output
        )

        if not success:
            output.unlink(missing_ok=True)
            return None

        return output

    async def convert_to_mp3(
        self,
        source: Path,
        track: Track
    ) -> Optional[Path]:
        """
        Конвертирует полученный файл в MP3 через FFmpeg.
        """

        if not source.exists():
            logger.error(
                "Source file does not exist: %s",
                source
            )
            return None

        output = source.with_suffix(".mp3")

        command = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",

            "-i",
            str(source),

            "-vn",
            "-map",
            "0:a:0",

            "-c:a",
            "libmp3lame",

            "-b:a",
            "192k",

            str(output),
        ]

        try:

            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            _, stderr = await process.communicate()

            if process.returncode != 0:

                logger.error(
                    "FFmpeg error:\n%s",
                    stderr.decode(
                        errors="ignore"
                    )[-3000:]
                )

                output.unlink(
                    missing_ok=True
                )

                return None

            if not output.exists():

                logger.error(
                    "FFmpeg did not create MP3"
                )

                return None

            if output.stat().st_size < 64 * 1024:

                logger.error(
                    "Generated MP3 is too small"
                )

                output.unlink(
                    missing_ok=True
                )

                return None

            # Исходник больше не нужен.
            source.unlink(
                missing_ok=True
            )

            logger.info(
                "MP3 created: %.2f MB",
                output.stat().st_size / 1024 / 1024
            )

            return output

        except FileNotFoundError:

            logger.error(
                "FFmpeg is not installed"
            )

            return None

        except Exception as e:

            logger.exception(
                "FFmpeg conversion failed: %s",
                e
            )

            output.unlink(
                missing_ok=True
            )

            return None


audio_service = AuthorizedAudioService()
