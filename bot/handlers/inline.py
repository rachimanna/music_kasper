from aiogram import Router
from aiogram.types import (
    InlineQuery,
    InlineQueryResultAudio,
    InlineQueryResultArticle,
    InputTextMessageContent
)
from bot.services.deezer_service import DeezerMusicService
from bot.database.db import db
from bot.keyboards.pagination import get_track_action_keyboard

router = Router()
music_service = DeezerMusicService()


@router.inline_query()
async def inline_search(inline_query: InlineQuery):
    query = inline_query.query.strip()

    if not query:
        placeholder = [
            InlineQueryResultArticle(
                id="empty_query",
                title="Начните вводить название песни или артиста",
                description="Например: Michael Jackson",
                input_message_content=InputTextMessageContent(
                    message_text="Чтобы найти трек, напишите название после юзернейма бота.",
                    parse_mode="Markdown"
                )
            )
        ]
        await inline_query.answer(placeholder, cache_time=5, is_personal=True)
        return

    try:
        cached_tracks = await db.get_cached_search(query)
        if cached_tracks:
            tracks = cached_tracks
        else:
            tracks = await music_service.search(query, limit=15)
            if tracks:
                await db.save_search_cache(query, tracks)

        if not tracks:
            not_found = [
                InlineQueryResultArticle(
                    id="not_found",
                    title="Ничего не найдено",
                    description=f"По запросу «{query}» нет треков.",
                    input_message_content=InputTextMessageContent(
                        message_text=f"Песня «{query}» не найдена.",
                    )
                )
            ]
            await inline_query.answer(not_found, cache_time=10, is_personal=True)
            return

        results = []
        for track in tracks:
            if track.preview_url:
                results.append(
                    InlineQueryResultAudio(
                        id=f"inline_{track.id}",
                        audio_url=track.preview_url,
                        title=track.title,
                        performer=track.artist,
                        audio_duration=30,
                        reply_markup=get_track_action_keyboard(track)
                    )
                )
            else:
                results.append(
                    InlineQueryResultArticle(
                        id=f"inline_art_{track.id}",
                        title=f"{track.artist} - {track.title}",
                        description=f"Длительность: {track.duration // 60}:{track.duration % 60:02d}",
                        thumbnail_url=track.cover_url,
                        input_message_content=InputTextMessageContent(
                            message_text=(
                                f"🎧 **{track.artist} — {track.title}**\n"
                                f"Слушать: {track.external_url}"
                            ),
                            parse_mode="Markdown"
                        ),
                        reply_markup=get_track_action_keyboard(track)
                    )
                )

        await inline_query.answer(results, cache_time=300, is_personal=True)
    except Exception:
        await inline_query.answer([], cache_time=5, is_personal=True)
