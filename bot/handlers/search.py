import html
import os
from typing import Dict

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile

from bot.services.deezer_service import DeezerMusicService
from bot.services.authorized_audio_service import audio_service
from bot.database.db import db
from bot.keyboards.pagination import get_search_results_keyboard, get_track_action_keyboard
from bot.utils.formatters import sanitize_query, format_duration
from bot.config import config

router = Router()
music_service = DeezerMusicService()
user_last_search: Dict[int, dict] = {}


@router.message(F.text)
async def handle_search_message(message: Message):
    text = message.text.strip()
    is_group = message.chat.type in ["group", "supergroup"]

    if is_group:
        mentioned = bool(config.BOT_USERNAME and f"@{config.BOT_USERNAME.lower()}" in text.lower())
        if not mentioned and not text.lower().startswith("найди"):
            return

    query = sanitize_query(text, config.BOT_USERNAME)
    if not query:
        await message.reply(
            "⚠️ Укажите название трека или исполнителя.\n"
            "Пример: <code>найди The Weeknd</code>", parse_mode="HTML"
        )
        return

    wait_msg = await message.reply("🔎 Ищу музыку...")
    try:
        tracks = await db.get_cached_search(query)
        if not tracks:
            tracks = await music_service.search(query, limit=20)
            if tracks:
                await db.save_search_cache(query, tracks)

        if not tracks:
            await wait_msg.edit_text("😔 Ничего не найдено.")
            return

        user_last_search[message.from_user.id] = {"query": query, "tracks": tracks}
        keyboard = get_search_results_keyboard(tracks, query, page=1)
        await wait_msg.edit_text(
            f"🎵 <b>Результаты поиска:</b> «{html.escape(query)}»\n"
            f"Найдено: {len(tracks)}\n\nВыберите трек:",
            reply_markup=keyboard, parse_mode="HTML"
        )
    except Exception:
        await wait_msg.edit_text("❌ Ошибка поиска. Попробуйте ещё раз.")


@router.callback_query(F.data.startswith("page:"))
async def handle_page_change(callback: CallbackQuery):
    page = int(callback.data.split(":")[1])
    data = user_last_search.get(callback.from_user.id)
    if not data:
        await callback.answer("⚠️ Сессия поиска устарела.", show_alert=True)
        return
    await callback.message.edit_reply_markup(
        reply_markup=get_search_results_keyboard(data["tracks"], data["query"], page)
    )
    await callback.answer()


@router.callback_query(F.data == "noop")
async def handle_noop(callback: CallbackQuery):
    await callback.answer()


@router.callback_query(F.data.startswith("sel:"))
async def handle_track_select(callback: CallbackQuery):
    track_id = callback.data.split(":", 1)[1]
    track = await db.get_track(track_id)
    if not track:
        track = await music_service.get_track(track_id)
        if track:
            await db.save_track(track)
    if not track:
        await callback.answer("⚠️ Трек не найден.", show_alert=True)
        return

    await callback.answer("⏳ Готовлю полный трек...")
    status = await callback.message.answer(
        f"⏳ Загружаю полный трек <b>{html.escape(track.artist)} — {html.escape(track.title)}</b>...",
        parse_mode="HTML"
    )

    if not audio_service.configured():
        await status.edit_text(
            "⚠️ Источник полных треков не настроен.\n\n"
            "Добавьте AUDIO_SOURCE_URL_TEMPLATE в Render Environment.\n"
            "Превью Deezer специально не отправляется, чтобы бот не выдавал 30 секунд вместо полной версии."
        )
        return

    source = await audio_service.download_track(track)
    if not source:
        await status.edit_text("❌ Не удалось получить полный аудиофайл. Попробуйте ещё раз позже.")
        return

    mp3 = await audio_service.convert_to_mp3(source, track)
    if not mp3:
        source.unlink(missing_ok=True)
        await status.edit_text("❌ Не удалось обработать аудиофайл.")
        return

    caption = (
        f"🎧 <b>{html.escape(track.artist)} — {html.escape(track.title)}</b>\n"
        f"⏱ Длительность: {format_duration(track.duration)}"
    )

    try:
        await callback.message.answer_audio(
            audio=FSInputFile(mp3, filename=f"{track.artist} - {track.title}.mp3"),
            caption=caption,
            title=track.title,
            performer=track.artist,
            duration=track.duration or None,
            thumbnail=None,
            reply_markup=get_track_action_keyboard(track),
            parse_mode="HTML",
        )
        await status.delete()
    except Exception:
        await status.edit_text("❌ Telegram не смог принять аудиофайл. Проверьте размер файла и повторите попытку.")
    finally:
        mp3.unlink(missing_ok=True)
