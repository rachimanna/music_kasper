from math import ceil
from typing import List
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot.services.base import Track
from bot.utils.formatters import format_duration
from bot.config import config


def get_search_results_keyboard(tracks: List[Track], query: str, page: int = 1) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    total_pages = max(1, ceil(len(tracks) / config.PAGE_SIZE))
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * config.PAGE_SIZE
    page_tracks = tracks[start_idx:start_idx + config.PAGE_SIZE]

    for idx, track in enumerate(page_tracks, start=start_idx + 1):
        dur = format_duration(track.duration)
        title = f"{idx}. {track.artist} - {track.title} ({dur})"
        if len(title) > 60:
            title = title[:57] + "..."
        builder.row(
            InlineKeyboardButton(text=title, callback_data=f"sel:{track.id}")
        )

    nav_buttons = []
    if page > 1:
        nav_buttons.append(
            InlineKeyboardButton(text="⬅️ Назад", callback_data=f"page:{page - 1}")
        )

    nav_buttons.append(
        InlineKeyboardButton(text=f"📄 {page}/{total_pages}", callback_data="noop")
    )

    if page < total_pages:
        nav_buttons.append(
            InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"page:{page + 1}")
        )

    builder.row(*nav_buttons)
    return builder.as_markup()


def get_track_action_keyboard(track: Track) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🎧 Слушать трек", url=track.external_url)
    )
    builder.row(
        InlineKeyboardButton(
            text="🔎 Искать в YouTube",
            url=f"https://www.youtube.com/results?search_query={track.artist}+{track.title}"
        )
    )
    return builder.as_markup()
