from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, User
from cachetools import TTLCache


class ThrottlingMiddleware(BaseMiddleware):
    """
    Не чаще одного запроса за `rate` секунд от пользователя.
    Регистрируется как inner-middleware, поэтому срабатывает только после фильтров,
    то есть на сообщения, которые действительно адресованы боту.
    Предупреждение отправляется один раз за окно, чтобы бот сам не спамил.
    """

    def __init__(self, rate: float) -> None:
        self.rate = rate
        self._recent: TTLCache = TTLCache(maxsize=10_000, ttl=rate if rate > 0 else 1)
        self._warned: TTLCache = TTLCache(maxsize=10_000, ttl=rate if rate > 0 else 1)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        if self.rate <= 0 or user is None:
            return await handler(event, data)

        if user.id in self._recent:
            if isinstance(event, CallbackQuery):
                # На callback нужно ответить в любом случае, иначе у кнопки будут «часики».
                await event.answer("⏳ Подождите секунду…")
            elif isinstance(event, Message) and user.id not in self._warned:
                self._warned[user.id] = True
                await event.reply("⏳ Не спешите, вы отправляете запросы слишком часто!")
            return None

        self._recent[user.id] = True
        return await handler(event, data)
