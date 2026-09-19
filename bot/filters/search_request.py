import re
from typing import Any, Dict, Union

from aiogram import Bot
from aiogram.enums import ChatType
from aiogram.filters import Filter
from aiogram.types import Message

from bot.config import config
from bot.utils.formatters import mention_pattern, sanitize_query

_FIND_RE = re.compile(r"^\s*найди(?=\s|$)", re.IGNORECASE)


class SearchRequest(Filter):
    """
    Пропускает только сообщения, адресованные боту:
    - в личке — любой текст, кроме команд;
    - в группе — упоминание бота, «найди …» или ответ на сообщение бота.
    Остальные сообщения группы бот не трогает (и троттлинг на них не срабатывает).
    Передаёт в хендлер готовый `query`.
    """

    async def __call__(self, message: Message, bot: Bot) -> Union[bool, Dict[str, Any]]:
        text = message.text
        if not text or text.startswith("/") or message.via_bot is not None:
            return False

        if message.chat.type != ChatType.PRIVATE:
            username = config.BOT_USERNAME
            reply = message.reply_to_message
            addressed = (
                (bool(username) and mention_pattern(username).search(text) is not None)
                or _FIND_RE.match(text) is not None
                or (reply is not None and reply.from_user is not None and reply.from_user.id == bot.id)
            )
            if not addressed:
                return False

        return {"query": sanitize_query(text, config.BOT_USERNAME, config.MAX_QUERY_LENGTH)}
