"""Скачивание полного трека и отправка его в чат. Используется кнопками поиска и deep link."""
import html
import logging
from typing import Optional, Set

from aiogram import Bot
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramAPIError
from aiogram.types import FSInputFile, Message, URLInputFile

from bot.config import config
from bot.keyboards.pagination import track_links_keyboard
from bot.services.authorized_audio_service import DownloadedAudio, audio_service
from bot.services.base import Track
from bot.services.catalog import find_track
from bot.utils.formatters import format_duration, safe_filename

logger = logging.getLogger(__name__)

# Пользователи, для которых сейчас идёт скачивание — чтобы не запускать 10 загрузок подряд.
_active_users: Set[int] = set()


async def _safe_edit(message: Optional[Message], text: str) -> None:
    if message is None:
        return
    try:
        await message.edit_text(text)
    except TelegramAPIError as exc:
        logger.debug("Cannot edit status message: %s", exc)


async def _safe_delete(message: Optional[Message]) -> None:
    if message is None:
        return
    try:
        await message.delete()
    except TelegramAPIError as exc:
        logger.debug("Cannot delete status message: %s", exc)


async def _send_audio(bot: Bot, chat_id: int, track: Track, audio: DownloadedAudio) -> None:
    caption = (
        f"🎧 <b>{html.escape(track.artist)} — {html.escape(track.title)}</b>\n"
        f"⏱ Длительность: {format_duration(audio.duration)}"
    )
    kwargs = dict(
        chat_id=chat_id,
        caption=caption,
        title=track.title,
        performer=track.artist,
        duration=audio.duration,
        reply_markup=track_links_keyboard(track),
        request_timeout=config.UPLOAD_TIMEOUT,
    )
    filename = safe_filename(f"{track.artist} - {track.title}") + ".mp3"

    if track.cover_url:
        try:
            await bot.send_audio(
                audio=FSInputFile(audio.path, filename=filename),
                thumbnail=URLInputFile(track.cover_url),
                **kwargs,
            )
            return
        except Exception as exc:  # обложка недоступна или Telegram её не принял — шлём без неё
            logger.warning("Sending with thumbnail failed (%s), retrying without it", exc)

    await bot.send_audio(audio=FSInputFile(audio.path, filename=filename), **kwargs)


async def deliver_track(bot: Bot, chat_id: int, user_id: int, track_id: str) -> None:
    if user_id in _active_users:
        await bot.send_message(chat_id, "⏳ Я ещё скачиваю предыдущий трек, подождите немного.")
        return

    track = await find_track(track_id)
    if track is None:
        await bot.send_message(chat_id, "⚠️ Трек не найден.")
        return

    if not audio_service.configured():
        await bot.send_message(
            chat_id,
            "⚠️ Источник полных треков не настроен.\n\n"
            "Deezer отдаёт только 30-секундное превью, поэтому я не отправляю его вместо полной версии.",
        )
        return

    _active_users.add(user_id)
    status: Optional[Message] = None
    audio: Optional[DownloadedAudio] = None
    try:
        status = await bot.send_message(
            chat_id,
            f"⏳ Скачиваю полную версию <b>{html.escape(track.full_name)}</b>…",
        )
        await bot.send_chat_action(chat_id, ChatAction.UPLOAD_DOCUMENT)

        audio = await audio_service.download_track(track)
        if audio is None:
            await _safe_edit(status, "❌ Не удалось получить полный аудиофайл.\n\nПопробуйте ещё раз позже.")
            return

        await bot.send_chat_action(chat_id, ChatAction.UPLOAD_DOCUMENT)
        await _send_audio(bot, chat_id, track, audio)
        await _safe_delete(status)

    except Exception:
        logger.exception("Failed to deliver track %s", track_id)
        await _safe_edit(status, "❌ Не удалось отправить аудиофайл в Telegram.")

    finally:
        _active_users.discard(user_id)
        if audio is not None:
            try:
                audio.path.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("File cleanup error: %s", exc)
