import html
import os
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile, URLInputFile
from bot.services.deezer_service import DeezerMusicService
from bot.services.yt_service import yt_service
from bot.database.db import db
from bot.keyboards.pagination import get_search_results_keyboard, get_track_action_keyboard
from bot.utils.formatters import sanitize_query, format_duration
from bot.config import config

router = Router()
music_service = DeezerMusicService()

user_last_search = {}


@router.message(F.text)
async def handle_search_message(message: Message):
    text = message.text.strip()
    is_group = message.chat.type in ["group", "supergroup"]

    if is_group:
        is_mentioned = False
        if config.BOT_USERNAME and f"@{config.BOT_USERNAME.lower()}" in text.lower():
            is_mentioned = True
        elif text.lower().startswith("найди"):
            is_mentioned = True

        if not is_mentioned:
            return

    query = sanitize_query(text, config.BOT_USERNAME)

    if not query:
        await message.reply(
            "⚠️ Пожалуйста, укажите название трека или исполнителя.\nПример: <code>найди The Weeknd</code>",
            parse_mode="HTML"
        )
        return

    wait_msg = await message.reply("🔎 Ищу музыку...")

    try:
        cached_tracks = await db.get_cached_search(query)
        if cached_tracks:
            tracks = cached_tracks
        else:
            tracks = await music_service.search(query, limit=20)
            if tracks:
                await db.save_search_cache(query, tracks)

        if not tracks:
            await wait_msg.edit_text("😔 Ничего не найдено. Проверьте правильность написания.")
            return

        user_last_search[message.from_user.id] = {
            "query": query,
            "tracks": tracks
        }

        safe_query = html.escape(query)
        keyboard = get_search_results_keyboard(tracks, query, page=1)
        await wait_msg.edit_text(
            f"🎵 <b>Результаты поиска по запросу:</b> «{safe_query}»\n"
            f"Найдено треков: {len(tracks)}\n\n"
            "Выберите трек для скачивания:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except Exception:
        await wait_msg.edit_text("❌ Произошла ошибка сервиса при поиске. Попробуйте позже.")


@router.callback_query(F.data.startswith("page:"))
async def handle_page_change(callback: CallbackQuery):
    page = int(callback.data.split(":")[1])
    user_id = callback.from_user.id

    data = user_last_search.get(user_id)
    if not data:
        await callback.answer("⚠️ Сессия поиска устарела. Введите запрос заново.", show_alert=True)
        return

    tracks = data["tracks"]
    query = data["query"]
    keyboard = get_search_results_keyboard(tracks, query, page=page)

    try:
        await callback.message.edit_reply_markup(reply_markup=keyboard)
        await callback.answer()
    except Exception:
        await callback.answer()


@router.callback_query(F.data == "noop")
async def handle_noop(callback: CallbackQuery):
    await callback.answer()


@router.callback_query(F.data.startswith("sel:"))
async def handle_track_select(callback: CallbackQuery):
    track_id = callback.data.split(":")[1]

    track = await db.get_track(track_id)
    if not track:
        track = await music_service.get_track(track_id)
        if track:
            await db.save_track(track)

    if not track:
        await callback.answer("⚠️ Трек не найден.", show_alert=True)
        return

    safe_artist = html.escape(track.artist)
    safe_title = html.escape(track.title)

    await callback.answer("⏳ Скачиваю полный трек...")
    status_msg = await callback.message.answer(
        f"⏳ Скачиваю полную версию <b>{safe_artist} — {safe_title}</b>...",
        parse_mode="HTML"
    )

    # Передаем автора и название раздельно для умного поиска
    download_info = await yt_service.download_track(track.artist, track.title)

    caption = (
        f"🎧 <b>{safe_artist} — {safe_title}</b>\n"
        f"⏱ Длительность: {format_duration(track.duration)}"
    )
    keyboard = get_track_action_keyboard(track)

    if download_info and os.path.exists(download_info["file_path"]):
        file_path = download_info["file_path"]
        try:
            audio_file = FSInputFile(file_path, filename=f"{track.artist} - {track.title}.mp3")
            thumb = URLInputFile(track.cover_url) if track.cover_url else None

            await callback.message.answer_audio(
                audio=audio_file,
                caption=caption,
                title=track.title,
                performer=track.artist,
                duration=track.duration or download_info["duration"],
                thumbnail=thumb,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            await status_msg.delete()
        finally:
            if os.path.exists(file_path):
                os.remove(file_path)
    else:
        await status_msg.edit_text(
            "⚠️ Полный трек не найден. Отправляю превью:",
            parse_mode="HTML"
        )
        if track.preview_url:
            await callback.message.answer_audio(
                audio=URLInputFile(track.preview_url),
                caption=caption + " <i>(Превью)</i>",
                title=track.title,
                performer=track.artist,
                duration=30,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
