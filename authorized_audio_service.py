import os
import uuid
import asyncio
from pathlib import Path
from typing import Optional

import aiohttp


DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", "downloads"))
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

MAX_FILE_SIZE = int(os.getenv("MAX_AUDIO_SIZE_MB", "100")) * 1024 * 1024
DOWNLOAD_TIMEOUT = int(os.getenv("AUDIO_DOWNLOAD_TIMEOUT", "180"))

AUDIO_SOURCE_URL_TEMPLATE = os.getenv("AUDIO_SOURCE_URL_TEMPLATE", "").strip()


async def _download_file(url: str, output_path: Path) -> bool:
    """
    Загружает аудиофайл по прямой URL-ссылке.
    Используй только источник, с которого у тебя есть право
    получать полный аудиофайл.
    """

    timeout = aiohttp.ClientTimeout(
        total=DOWNLOAD_TIMEOUT,
        connect=30,
        sock_read=DOWNLOAD_TIMEOUT,
    )

    headers = {
        "User-Agent": "MusicKasPerBot/1.0"
    }

    try:
        async with aiohttp.ClientSession(
            timeout=timeout,
            headers=headers
        ) as session:

            async with session.get(
                url,
                allow_redirects=True
            ) as response:

                if response.status != 200:
                    print(
                        f"[AUDIO] HTTP error: "
                        f"{response.status} {url}"
                    )
                    return False

                content_length = response.headers.get("Content-Length")

                if content_length:
                    try:
                        if int(content_length) > MAX_FILE_SIZE:
                            print("[AUDIO] File is too large")
                            return False
                    except ValueError:
                        pass

                downloaded = 0

                with open(output_path, "wb") as file:
                    async for chunk in response.content.iter_chunked(1024 * 256):
                        if not chunk:
                            continue

                        downloaded += len(chunk)

                        if downloaded > MAX_FILE_SIZE:
                            print("[AUDIO] Download exceeded size limit")
                            return False

                        file.write(chunk)

                if downloaded < 1024:
                    print("[AUDIO] Downloaded file is empty or invalid")
                    return False

                return True

    except asyncio.TimeoutError:
        print("[AUDIO] Download timeout")
        return False

    except aiohttp.ClientError as e:
        print(f"[AUDIO] Network error: {e}")
        return False

    except Exception as e:
        print(f"[AUDIO] Unexpected error: {e}")
        return False


async def download_audio(
    artist: str,
    title: str,
    source_url: Optional[str] = None,
) -> Optional[dict]:
    """
    Получает полный аудиофайл из настроенного разрешённого источника.

    source_url можно передать напрямую.

    Либо используется:
        AUDIO_SOURCE_URL_TEMPLATE

    Например:
        https://your-domain.example/audio/{artist}/{title}.mp3
    """

    url = source_url

    if not url:
        if not AUDIO_SOURCE_URL_TEMPLATE:
            print(
                "[AUDIO] AUDIO_SOURCE_URL_TEMPLATE "
                "is not configured"
            )
            return None

        url = AUDIO_SOURCE_URL_TEMPLATE.format(
            artist=artist,
            title=title,
        )

    if not url.startswith(("http://", "https://")):
        print("[AUDIO] Invalid audio URL")
        return None

    unique_id = uuid.uuid4().hex

    raw_file = DOWNLOAD_DIR / f"{unique_id}.source"
    mp3_file = DOWNLOAD_DIR / f"{unique_id}.mp3"

    try:
        print(f"[AUDIO] Downloading: {artist} - {title}")

        success = await _download_file(
            url,
            raw_file
        )

        if not success:
            return None

        # Конвертация в MP3 через FFmpeg.
        process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-i",
            str(raw_file),
            "-vn",
            "-codec:a",
            "libmp3lame",
            "-b:a",
            "192k",
            str(mp3_file),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            print(
                "[AUDIO] FFmpeg error:\n",
                stderr.decode(errors="ignore")[-2000:]
            )
            return None

        if not mp3_file.exists():
            print("[AUDIO] MP3 was not created")
            return None

        if mp3_file.stat().st_size < 1024:
            print("[AUDIO] MP3 is empty")
            return None

        duration = await get_audio_duration(mp3_file)

        if duration <= 0:
            print("[AUDIO] Could not determine duration")
            return None

        print(
            f"[AUDIO] Ready: "
            f"{artist} - {title} "
            f"({duration:.1f}s)"
        )

        return {
            "file_path": str(mp3_file),
            "title": title,
            "artist": artist,
            "duration": int(duration),
        }

    except Exception as e:
        print(f"[AUDIO] Error: {e}")
        return None

    finally:
        # Исходный скачанный файл больше не нужен.
        try:
            if raw_file.exists():
                raw_file.unlink()
        except Exception:
            pass


async def get_audio_duration(file_path: Path) -> float:
    """
    Получает настоящую длительность готового файла через ffprobe.
    """

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
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, _ = await process.communicate()

        if process.returncode != 0:
            return 0

        value = stdout.decode().strip()

        if not value:
            return 0

        return float(value)

    except Exception as e:
        print(f"[AUDIO] ffprobe error: {e}")
        return 0


async def cleanup_file(file_path: Optional[str]) -> None:
    """
    Безопасно удаляет временный аудиофайл.
    """

    if not file_path:
        return

    try:
        path = Path(file_path)

        if path.exists():
            path.unlink()
            print(f"[AUDIO] Deleted: {path}")

    except Exception as e:
        print(f"[AUDIO] Cleanup error: {e}")
