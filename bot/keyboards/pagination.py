from math import ceil
from typing import List
from urllib.parse import quote_plus

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import config
from bot.services.base import Track
from bot.utils.formatters import format_duration, truncate


def total_pages(tracks: List[Track]) -> int:
    return max(1, ceil(len(tracks) / config.PAGE_SIZE))


def search_results_keyboard(session_id: str, tracks: List[Track], page: int = 1) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    pages = total_pages(tracks)
    page = max(1, min(page, pages))

    start = (page - 1) * config.PAGE_SIZE
    for number, track in enumerate(tracks[start:start + config.PAGE_SIZE], start=start + 1):
        text = f"{number}. {track.artist} — {track.title} ({format_duration(track.duration)})"
        builder.row(InlineKeyboardButton(text=truncate(text, 60), callback_data=f"sel:{track.id}"))

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"page:{session_id}:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"📄 {page}/{pages}", callback_data="noop"))
    if page < pages:
        nav.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"page:{session_id}:{page + 1}"))
    builder.row(*nav)
    return builder.as_markup()


def youtube_search_url(track: Track) -> str:
    return "https://www.youtube.com/results?search_query=" + quote_plus(f"{track.artist} {track.title}")


def track_links_keyboard(track: Track, with_download: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if with_download and config.BOT_USERNAME:
        # Deep link: открывает личку с ботом и сразу запускает скачивание полной версии.
        builder.row(
            InlineKeyboardButton(
                text="⬇️ Скачать полную версию",
                url=f"https://t.me/{config.BOT_USERNAME}?start=t_{track.id}",
            )
        )
    builder.row(
        InlineKeyboardButton(text="🎧 Открыть в Deezer", url=track.external_url),
        InlineKeyboardButton(text="🔎 YouTube", url=youtube_search_url(track)),
    )
    return builder.as_markup()
