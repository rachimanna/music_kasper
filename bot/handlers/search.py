from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, URLInputFile
from bot.services.deezer_service import DeezerMusicService
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
            "⚠️ Пожалуйста, укажите название трека или исполнителя.\nПример: `найди The Weeknd`",
            parse_mode="Markdown"
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

        keyboard = get_search_results_keyboard(tracks, query, page=1)
        await wait_msg.edit_text(
            f"🎵 **Результаты поиска по запросу:** «{query}»\n"
            f"Найдено треков: {len(tracks)}\n\n"
            "Выберите трек для прослушивания:",
            reply_markup=keyboard,
            parse_mode="Markdown"
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
        await callback.answer("⚠️ Трек не найден или удалён из источника.", show_alert=True)
        return

    await callback.answer("Загружаю трек...")

    caption = (
        f"🎧 **{track.artist} — {track.title}**\n"
        f"⏱ Длительность: {format_duration(track.duration)}"
    )
    keyboard = get_track_action_keyboard(track)

    if track.preview_url:
        audio = URLInputFile(track.preview_url, filename=f"{track.artist} - {track.title}.mp3")
        thumb = URLInputFile(track.cover_url) if track.cover_url else None

        await callback.message.answer_audio(
            audio=audio,
            caption=caption,
            title=track.title,
            performer=track.artist,
            duration=30,
            thumbnail=thumb,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    else:
        if track.cover_url:
            await callback.message.answer_photo(
                photo=track.cover_url,
                caption=caption + "\n\n*(Превью аудио недоступно для этого трека)*",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        else:
            await callback.message.answer(
                caption,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
