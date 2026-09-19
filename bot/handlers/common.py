import html

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message

from bot.config import config
from bot.services.delivery import deliver_track

router = Router(name="common")


@router.message(CommandStart(deep_link=True, magic=F.args.regexp(r"^t_\d+$")))
async def cmd_start_download(message: Message, command: CommandObject, bot: Bot) -> None:
    """Deep link из inline-режима: /start t_<id> — сразу скачиваем трек."""
    if message.from_user is None:
        return
    track_id = command.args[2:]
    await deliver_track(bot, message.chat.id, message.from_user.id, track_id)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    name = html.escape(message.from_user.first_name) if message.from_user else "друг"
    username = html.escape(config.BOT_USERNAME)
    await message.answer(
        f"👋 Привет, <b>{name}</b>!\n\n"
        "Я музыкальный поисковый бот <b>music_kasper</b> 🎵\n\n"
        "🔎 <b>Как мной пользоваться:</b>\n"
        "1. <b>В личке:</b> просто напиши название трека или <code>найди Blinding Lights</code>\n"
        f"2. <b>В группах:</b> напиши <code>@{username} трек</code>, <code>найди трек</code> "
        "или ответь на моё сообщение\n"
        f"3. <b>В любом чате (inline):</b> набери <code>@{username} название</code>\n\n"
        "Попробуй прямо сейчас: отправь мне название трека!"
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    username = html.escape(config.BOT_USERNAME)
    await message.answer(
        "💡 <b>Справка</b>\n\n"
        "• Отправь название песни или исполнителя\n"
        "• <code>найди песня</code> — то же самое\n"
        f"• В группах: <code>@{username} запрос</code> или <code>найди запрос</code>\n"
        f"• В любом чате: <code>@{username} запрос</code> (inline-режим)"
    )
