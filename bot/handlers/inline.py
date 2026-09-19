import html
import logging

from aiogram import Router
from aiogram.enums import ParseMode
from aiogram.types import InlineQuery, InlineQueryResultArticle, InputTextMessageContent

from bot.config import config
from bot.keyboards.pagination import track_links_keyboard
from bot.services.base import ProviderError
from bot.services.catalog import search_tracks
from bot.utils.formatters import format_duration

logger = logging.getLogger(__name__)

router = Router(name="inline")


def _hint(result_id: str, title: str, description: str) -> InlineQueryResultArticle:
    return InlineQueryResultArticle(
        id=result_id,
        title=title,
        description=description,
        input_message_content=InputTextMessageContent(message_text=f"{title}\n{description}", parse_mode=None),
    )


@router.inline_query()
async def inline_search(inline_query: InlineQuery) -> None:
    query = " ".join(inline_query.query.split())[: config.MAX_QUERY_LENGTH]

    if not query:
        await inline_query.answer(
            [_hint("empty", "Начните вводить название песни или артиста", "Например: Michael Jackson")],
            cache_time=300,
        )
        return

    try:
        tracks = await search_tracks(query)
    except ProviderError as exc:
        logger.warning("Inline provider error: %s", exc)
        await inline_query.answer(
            [_hint("unavailable", "Сервис временно недоступен", "Попробуйте через минуту")],
            cache_time=5,
        )
        return
    except Exception:
        logger.exception("Inline search failed for %r", query)
        await inline_query.answer([], cache_time=5)
        return

    if not tracks:
        await inline_query.answer(
            [_hint("not_found", "Ничего не найдено", f"По запросу «{query}» треков нет")],
            cache_time=30,
        )
        return

    # Отправляем карточку трека с кнопкой «Скачать полную версию» (deep link в личку бота),
    # а не 30-секундное превью Deezer — его ссылки к тому же со временем истекают.
    results = []
    for track in tracks[: config.INLINE_LIMIT]:
        duration = format_duration(track.duration)
        results.append(
            InlineQueryResultArticle(
                id=f"t_{track.id}",
                title=track.title,
                description=f"{track.artist} · {duration}",
                thumbnail_url=track.cover_url,
                input_message_content=InputTextMessageContent(
                    message_text=(
                        f"🎧 <b>{html.escape(track.full_name)}</b>\n"
                        f"⏱ {duration}"
                    ),
                    parse_mode=ParseMode.HTML,
                ),
                reply_markup=track_links_keyboard(track, with_download=True),
            )
        )

    await inline_query.answer(results, cache_time=300)
