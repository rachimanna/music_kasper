import asyncio
import logging
import os
import uuid
from pathlib import Path
from typing import Optional, Dict

import aiohttp

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = Path("/tmp/music_cache")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

MAX_FILE_SIZE = int(
    os.getenv("MAX_AUDIO_SIZE_MB", "100")
) * 1024 * 1024

DOWNLOAD_TIMEOUT = int(
    os.getenv("AUDIO_DOWNLOAD_TIMEOUT", "180")
)

# URL-шаблон источника полного аудио.
#
# Пример:
# https://example.com/audio/{artist}/{title}.mp3
#
# Источник должен быть таким, откуда у тебя есть право
# получать полный аудиофайл.
AUDIO_SOURCE_URL_TEMPLATE = os.getenv(
    "AUDIO_SOURCE_URL_TEMPLATE",
    ""
).strip()


class AuthorizedAudioService:

    def __init__(self):
        self.headers = {
            "User-Agent": "MusicKasPerBot/1.0",
            "Accept": "*/*",
        }

    def _build_url(
        self,
        artist: str,
        title: str
    ) -> Optional[str]:

        if not AUDIO_SOURCE_URL_TEMPLATE:
            logger.error(
                "AUDIO_SOURCE_URL_TEMPLATE is not configured"
            )
            return None

        try:
            return AUDIO_SOURCE_URL_TEMPLATE.format(
                artist=artist,
                title=title,
            )
        except Exception as e:
            logger.error(
                f"Failed to build audio URL: {e}"
            )
            return None

    async def _download(
        self,
        url: str,
        output_file: Path
    ) -> bool:

        timeout = aiohttp.ClientTimeout(
            total=DOWNLOAD_TIMEOUT,
            connect=30,
            sock_read=DOWNLOAD_TIMEOUT,
        )

        try:
            async with aiohttp.ClientSession(
                timeout=timeout,
                headers=self.headers
            ) as session:

                async with session.get(
                    url,
                    allow_redirects=True
                ) as response:

                    if response.status != 200:
                        logger.error(
                            f"Audio source returned HTTP "
                            f"{response.status}"
                        )
                        return False

                    content_length = response.headers.get(
                        "Content-Length"
                    )

                    if content_length:
                        try:
                            if int(content_length) > MAX_FILE_SIZE:
                                logger.error(
                                    "Audio file is too large"
                                )
                                return False
                        except ValueError:
                            pass

                    downloaded = 0

                    with open(
                        output_file,
                        "wb"
                    ) as file:

                        async for chunk in response.content.iter_chunked(
                            256 * 1024
                        ):

                            if not chunk:
                                continue

                            downloaded += len(chunk)

                            if downloaded > MAX_FILE_SIZE:
                                logger.error(
                                    "Audio exceeded maximum size"
                                )
                                return False

                            file.write(chunk)

                    if downloaded < 1024:
                        logger.error(
                            "Downloaded audio is empty"
                        )
                        return False

                    logger.info(
                        f"Downloaded "
                        f"{downloaded / 1024 / 1024:.2f} MB"
                    )

                    return True

        except asyncio.TimeoutError:
            logger.error(
                "Audio download timeout"
            )
            return False

        except aiohttp.ClientError as e:
            logger.error(
                f"Audio network error: {e}"
            )
            return False

        except Exception as e:
            logger.exception(
                f"Audio download error: {e}"
            )
            return False

    async def _convert_to_mp3(
        self,
        input_file: Path,
        output_file: Path
    ) -> bool:

        try:

            process = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-y",
                "-i",
                str(input_file),
                "-vn",
                "-codec:a",
                "libmp3lame",
                "-b:a",
                "192k",
                str(output_file),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )

            _, stderr = await process.communicate()

            if process.returncode != 0:

                logger.error(
                    "FFmpeg failed:\n%s",
                    stderr.decode(
                        errors="ignore"
                    )[-3000:]
                )

                return False

            if not output_file.exists():
                return False

            if output_file.stat().st_size < 1024:
                return False

            return True

        except FileNotFoundError:
            logger.error(
                "FFmpeg is not installed"
            )
            return False

        except Exception as e:
            logger.exception(
                f"FFmpeg error: {e}"
            )
            return False

    async def _get_duration(
        self,
        file_path: Path
    ) -> int:

        try:

            process = await asyncio.create_subprocess_exec(
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(file_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )

            stdout, _ = await process.communicate()

            if process.returncode != 0:
                return 0

            value = stdout.decode().strip()

            if not value:
                return 0

            return int(float(value))

        except Exception as e:
            logger.error(
                f"Failed to read duration: {e}"
            )
            return 0

    async def download_track(
        self,
        artist: str,
        title: str
    ) -> Optional[Dict]:

        url = self._build_url(
            artist,
            title
        )

        if not url:
            logger.error(
                "No authorized audio source configured"
            )
            return None

        unique_id = uuid.uuid4().hex

        source_file = (
            DOWNLOAD_DIR /
            f"{unique_id}.source"
        )

        mp3_file = (
            DOWNLOAD_DIR /
            f"{unique_id}.mp3"
        )

        try:

            logger.info(
                f"Downloading: "
                f"{artist} - {title}"
            )

            success = await self._download(
                url,
                source_file
            )

            if not success:
                return None

            success = await self._convert_to_mp3(
                source_file,
                mp3_file
            )

            if not success:
                return None

            duration = await self._get_duration(
                mp3_file
            )

            if duration <= 0:
                logger.error(
                    "Invalid audio duration"
                )
                return None

            logger.info(
                f"Audio ready: "
                f"{artist} - {title} "
                f"({duration}s)"
            )

            return {
                "file_path": str(mp3_file),
                "title": title,
                "artist": artist,
                "duration": duration,
            }

        except Exception as e:

            logger.exception(
                f"Audio service error: {e}"
            )

            return None

        finally:

            try:
                if source_file.exists():
                    source_file.unlink()
            except Exception:
                pass

    async def cleanup(
        self,
        file_path: Optional[str]
    ):

        if not file_path:
            return

        try:

            path = Path(file_path)

            if path.exists():
                path.unlink()

                logger.info(
                    f"Deleted temporary file: {path}"
                )

        except Exception as e:

            logger.warning(
                f"Cleanup error: {e}"
            )


audio_service = AuthorizedAudioService()
