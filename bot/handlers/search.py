import html
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

from bot.config import config
from bot.database.db import db
from bot.filters.search_request import SearchRequest
from bot.keyboards.pagination import search_results_keyboard
from bot.middlewares.throttling import ThrottlingMiddleware
from bot.services.base import ProviderError
from bot.services.catalog import search_tracks
from bot.services.delivery import deliver_track

logger = logging.getLogger(__name__)

router = Router(name="search")
router.message.middleware(ThrottlingMiddleware(config.RATE_LIMIT))
router.callback_query.middleware(ThrottlingMiddleware(config.RATE_LIMIT))


@router.message(SearchRequest())
async def handle_search_message(message: Message, query: str) -> None:
    if not query:
        await message.reply(
            "⚠️ Укажите название трека или исполнителя.\n"
            "Пример: <code>найди The Weeknd</code>"
        )
        return

    wait_msg = await message.reply("🔎 Ищу музыку…")

    try:
        tracks = await search_tracks(query)
    except ProviderError as exc:
        logger.warning("Search provider error: %s", exc)
        await wait_msg.edit_text("❌ Музыкальный сервис сейчас недоступен. Попробуйте чуть позже.")
        return
    except Exception:
        logger.exception("Search failed for query %r", query)
        await wait_msg.edit_text("❌ Произошла ошибка при поиске. Попробуйте позже.")
        return

    if not tracks:
        await wait_msg.edit_text("😔 Ничего не найдено. Проверьте правильность написания.")
        return

    session_id = await db.create_session(query, tracks)
    await wait_msg.edit_text(
        f"🎵 <b>Результаты поиска:</b> «{html.escape(query)}»\n"
        f"Найдено треков: {len(tracks)}\n\n"
        "Выберите трек для скачивания:",
        reply_markup=search_results_keyboard(session_id, tracks, page=1),
    )


@router.callback_query(F.data.startswith("page:"))
async def handle_page_change(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        await callback.answer("Некорректная страница.", show_alert=True)
        return

    session = await db.get_session(parts[1])
    if session is None:
        await callback.answer("⚠️ Результаты поиска устарели. Введите запрос заново.", show_alert=True)
        return

    if not isinstance(callback.message, Message):
        await callback.answer("⚠️ Сообщение слишком старое, повторите поиск.", show_alert=True)
        return

    _, tracks = session
    try:
        await callback.message.edit_reply_markup(
            reply_markup=search_results_keyboard(parts[1], tracks, page=int(parts[2]))
        )
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            logger.warning("Cannot switch page: %s", exc)
    await callback.answer()


@router.callback_query(F.data == "noop")
async def handle_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data.startswith("sel:"))
async def handle_track_select(callback: CallbackQuery, bot: Bot) -> None:
    track_id = callback.data.split(":", 1)[1]
    if not track_id.isdigit():
        await callback.answer("⚠️ Некорректный трек.", show_alert=True)
        return

    chat_id = callback.message.chat.id if callback.message else callback.from_user.id
    await callback.answer("⏳ Скачиваю полный трек…")
    await deliver_track(bot, chat_id, callback.from_user.id, track_id)
