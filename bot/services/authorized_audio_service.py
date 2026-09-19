import asyncio
import logging
import os
import uuid
from pathlib import Path
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = Path(
    os.getenv("DOWNLOAD_DIR", "/tmp/music_kasper")
)
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

MAX_AUDIO_MB = int(
    os.getenv("MAX_AUDIO_SIZE_MB", "49")
)

MAX_AUDIO_BYTES = MAX_AUDIO_MB * 1024 * 1024

DOWNLOAD_TIMEOUT = int(
    os.getenv("AUDIO_DOWNLOAD_TIMEOUT", "180")
)

AUDIO_SOURCE_URL_TEMPLATE = os.getenv(
    "AUDIO_SOURCE_URL_TEMPLATE",
    ""
).strip()


class AuthorizedAudioService:

    def __init__(self):
        self.timeout = aiohttp.ClientTimeout(
            total=None,
            connect=30,
            sock_connect=30,
            sock_read=DOWNLOAD_TIMEOUT,
        )

        self.headers = {
            "User-Agent": "MusicKasPerBot/1.0",
            "Accept": "*/*",
        }

    def configured(self) -> bool:
        return bool(AUDIO_SOURCE_URL_TEMPLATE)

    def _make_url(
        self,
        artist: str,
        title: str
    ) -> Optional[str]:

        if not self.configured():
            return None

        try:
            return AUDIO_SOURCE_URL_TEMPLATE.format(
                artist=artist,
                title=title,
            )
        except Exception as exc:
            logger.error(
                "Failed to build audio URL: %s",
                exc
            )
            return None

    async def _download(
        self,
        url: str,
        destination: Path
    ) -> bool:

        temporary = destination.with_suffix(
            destination.suffix + ".part"
        )

        try:
            async with aiohttp.ClientSession(
                timeout=self.timeout,
                headers=self.headers
            ) as session:

                async with session.get(
                    url,
                    allow_redirects=True
                ) as response:

                    if response.status != 200:
                        logger.error(
                            "Audio source HTTP %s: %s",
                            response.status,
                            url
                        )
                        return False

                    content_length = response.headers.get(
                        "Content-Length"
                    )

                    if content_length:
                        try:
                            if (
                                int(content_length)
                                > MAX_AUDIO_BYTES
                            ):
                                logger.error(
                                    "Audio file is too large"
                                )
                                return False
                        except ValueError:
                            pass

                    downloaded = 0

                    with open(
                        temporary,
                        "wb"
                    ) as output:

                        async for chunk in response.content.iter_chunked(
                            256 * 1024
                        ):

                            if not chunk:
                                continue

                            downloaded += len(chunk)

                            if downloaded > MAX_AUDIO_BYTES:
                                logger.error(
                                    "Audio exceeded %s MB",
                                    MAX_AUDIO_MB
                                )
                                return False

                            output.write(chunk)

                    if downloaded < 1024:
                        logger.error(
                            "Downloaded file is empty"
                        )
                        return False

            temporary.replace(destination)

            return True

        except asyncio.TimeoutError:
            logger.error(
                "Audio download timeout"
            )
            return False

        except aiohttp.ClientError as exc:
            logger.error(
                "Audio network error: %s",
                exc
            )
            return False

        except Exception as exc:
            logger.exception(
                "Audio download error: %s",
                exc
            )
            return False

        finally:
            try:
                if temporary.exists():
                    temporary.unlink()
            except Exception:
                pass

    async def download_track(
        self,
        artist: str,
        title: str
    ) -> Optional[dict]:

        if not self.configured():
            logger.warning(
                "AUDIO_SOURCE_URL_TEMPLATE is not configured"
            )
            return None

        url = self._make_url(
            artist,
            title
        )

        if not url:
            return None

        file_id = uuid.uuid4().hex

        source_file = (
            DOWNLOAD_DIR /
            f"{file_id}.source"
        )

        mp3_file = (
            DOWNLOAD_DIR /
            f"{file_id}.mp3"
        )

        try:

            logger.info(
                "Downloading full track: %s — %s",
                artist,
                title
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
                    "Could not determine audio duration"
                )
                return None

            return {
                "file_path": str(mp3_file),
                "title": title,
                "artist": artist,
                "duration": duration,
            }

        except Exception as exc:
            logger.exception(
                "Audio service error: %s",
                exc
            )
            return None

        finally:
            try:
                if source_file.exists():
                    source_file.unlink()
            except Exception:
                pass

    async def _convert_to_mp3(
        self,
        source: Path,
        destination: Path
    ) -> bool:

        try:

            process = await asyncio.create_subprocess_exec(
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
                "-codec:a",
                "libmp3lame",
                "-b:a",
                "192k",
                str(destination),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )

            _, stderr = await process.communicate()

            if process.returncode != 0:
                logger.error(
                    "FFmpeg error: %s",
                    stderr.decode(
                        errors="ignore"
                    )[-3000:]
                )
                return False

            if not destination.exists():
                return False

            if destination.stat().st_size < 1024:
                return False

            return True

        except FileNotFoundError:
            logger.error(
                "FFmpeg is not installed"
            )
            return False

        except Exception as exc:
            logger.exception(
                "FFmpeg conversion error: %s",
                exc
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

        except Exception as exc:
            logger.error(
                "ffprobe error: %s",
                exc
            )
            return 0


audio_service = AuthorizedAudioService()
