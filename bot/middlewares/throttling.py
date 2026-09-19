from typing import Any, Awaitable, Callable, Dict
import time
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject
from cachetools import TTLCache
from bot.config import config


class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, limit: float = config.RATE_LIMIT):
        self.cache = TTLCache(maxsize=10000, ttl=limit)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        user_id = None
        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            user_id = event.from_user.id

        if user_id:
            if user_id in self.cache:
                if isinstance(event, Message):
                    await event.answer("⏳ Не спешите, вы отправляете запросы слишком часто!")
                elif isinstance(event, CallbackQuery):
                    await event.answer("⏳ Подождите секунду...", show_alert=False)
                return None
            self.cache[user_id] = time.time()

        return await handler(event, data)
