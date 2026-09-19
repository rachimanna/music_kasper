"""
Отправка трека в чат. Порядок источников:
1. Свой сервер (AUDIO_SOURCE_URL_TEMPLATE) — полная версия.
2. Jamendo — полная версия, если исполнитель выложил трек под Creative Commons.
3. Deezer — 30-секундное превью с явной пометкой и ссылкой на полную версию.
"""
import html
import logging
from typing import Optional, Set

from aiogram import Bot
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramAPIError
from aiogram.types import FSInputFile, InputFile, Message, URLInputFile

from bot.config import config
from bot.keyboards.pagination import track_links_keyboard
from bot.services.authorized_audio_service import DownloadedAudio, audio_service
from bot.services.base import Track
from bot.services.catalog import find_track
from bot.services.deezer_service import deezer
from bot.services.jamendo_service import jamendo
from bot.utils.formatters import format_duration, safe_filename

logger = logging.getLogger(__name__)

# Пользователи, для которых сейчас идёт скачивание — чтобы не запускать 10 загрузок подряд.
_active_users: Set[int] = set()


async def _safe_edit(message: Optional[Message], text: str) -> None:
    if message is None:
        return
    try:
        await message.edit_text(text, disable_web_page_preview=True)
    except TelegramAPIError as exc:
        logger.debug("Cannot edit status message: %s", exc)


async def _safe_delete(message: Optional[Message]) -> None:
    if message is None:
        return
    try:
        await message.delete()
    except TelegramAPIError as exc:
        logger.debug("Cannot delete status message: %s", exc)


def _title_line(track: Track) -> str:
    return f"🎧 <b>{html.escape(track.artist)} — {html.escape(track.title)}</b>"


async def _send(bot: Bot, chat_id: int, track: Track, audio: InputFile, caption: str, duration: int) -> None:
    kwargs = dict(
        chat_id=chat_id,
        caption=caption,
        title=track.title,
        performer=track.artist,
        duration=duration,
        reply_markup=track_links_keyboard(track),
        request_timeout=config.UPLOAD_TIMEOUT,
    )
    if track.cover_url:
        try:
            await bot.send_audio(audio=audio, thumbnail=URLInputFile(track.cover_url), **kwargs)
            return
        except Exception as exc:  # обложка недоступна или Telegram её не принял — шлём без неё
            logger.warning("Sending with thumbnail failed (%s), retrying without it", exc)
    await bot.send_audio(audio=audio, **kwargs)


async def _send_full(bot: Bot, chat_id: int, track: Track, audio: DownloadedAudio, license_url: Optional[str] = None) -> None:
    caption = f"{_title_line(track)}\n⏱ {format_duration(audio.duration)}"
    if license_url:
        caption += f'\n📜 Jamendo · <a href="{html.escape(license_url)}">лицензия Creative Commons</a>'
    filename = safe_filename(f"{track.artist} - {track.title}") + ".mp3"
    await _send(bot, chat_id, track, FSInputFile(audio.path, filename=filename), caption, audio.duration)


async def _send_preview(bot: Bot, chat_id: int, track: Track) -> bool:
    # Ссылки превью Deezer подписаны и истекают, поэтому берём свежую.
    fresh = await deezer.get_track(track.id)
    preview_url = (fresh.preview_url if fresh else None) or track.preview_url
    if not preview_url:
        return False

    caption = (
        f"{_title_line(track)}\n"
        "⏯ <b>Превью 30 секунд.</b> Полная версия — по кнопке «Открыть в Deezer»."
    )
    filename = safe_filename(f"{track.artist} - {track.title} (preview)") + ".mp3"
    await _send(bot, chat_id, track, URLInputFile(preview_url, filename=filename), caption, 30)
    return True


async def _try_full(track: Track) -> tuple[Optional[DownloadedAudio], Optional[str]]:
    """(аудио, ссылка на лицензию) из первого сработавшего полного источника."""
    if audio_service.configured():
        audio = await audio_service.download_track(track)
        if audio:
            return audio, None

    match = await jamendo.find_full_track(track)
    if match:
        audio = await audio_service.download_from_url(match.download_url, track)
        if audio:
            return audio, match.license_url

    return None, None


async def deliver_track(bot: Bot, chat_id: int, user_id: int, track_id: str) -> None:
    if user_id in _active_users:
        await bot.send_message(chat_id, "⏳ Я ещё обрабатываю предыдущий трек, подождите немного.")
        return

    track = await find_track(track_id)
    if track is None:
        await bot.send_message(chat_id, "⚠️ Трек не найден.")
        return

    has_full_source = audio_service.configured() or jamendo.configured()
    if not has_full_source and not config.PREVIEW_ENABLED:
        await bot.send_message(chat_id, "⚠️ Источники аудио не настроены.")
        return

    _active_users.add(user_id)
    status: Optional[Message] = None
    audio: Optional[DownloadedAudio] = None
    try:
        status = await bot.send_message(chat_id, f"⏳ Ищу <b>{html.escape(track.full_name)}</b>…")
        await bot.send_chat_action(chat_id, ChatAction.UPLOAD_DOCUMENT)

        if has_full_source:
            audio, license_url = await _try_full(track)
            if audio:
                await bot.send_chat_action(chat_id, ChatAction.UPLOAD_DOCUMENT)
                await _send_full(bot, chat_id, track, audio, license_url)
                await _safe_delete(status)
                return

        if config.PREVIEW_ENABLED and await _send_preview(bot, chat_id, track):
            await _safe_delete(status)
            return

        await _safe_edit(
            status,
            "😔 Для этого трека нет ни полной версии, ни превью.\n"
            f'Послушать можно в <a href="{html.escape(track.external_url)}">Deezer</a>.',
        )

    except Exception:
        logger.exception("Failed to deliver track %s", track_id)
        await _safe_edit(status, "❌ Не удалось отправить трек. Попробуйте ещё раз позже.")

    finally:
        _active_users.discard(user_id)
        if audio is not None:
            try:
                audio.path.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("File cleanup error: %s", exc)
