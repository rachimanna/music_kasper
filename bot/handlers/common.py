from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message):
    welcome_text = (
        f"👋 Привет, <b>{message.from_user.first_name}</b>!\n\n"
        "Я музыкальный поисковый бот <b>music_kasper</b> 🎵\n\n"
        "🔎 <b>Как мной пользоваться:</b>\n"
        "1. <b>В личке:</b> просто напиши название трека или <code>найди Blinding Lights</code>\n"
        "2. <b>В группах:</b> добавь меня в группу и напиши <code>@music_kasper_bot трек</code> или <code>найди трек</code>\n"
        "3. <b>В любом чате (Inline-режим):</b> набери в строке ввода <code>@music_kasper_bot название</code>\n\n"
        "Попробуй прямо сейчас: отправь мне название трека!"
    )
    await message.answer(welcome_text, parse_mode="HTML")


@router.message(Command("help"))
async def cmd_help(message: Message):
    help_text = (
        "💡 <b>Справка по командам:</b>\n\n"
        "• Отправь название песни или артиста\n"
        "• <code>найди песня</code> — текстовый запрос\n"
        "• В группах: упомяни бота перед запросом\n"
        "• В диалогах: используй inline-поиск"
    )
    await message.answer(help_text, parse_mode="HTML")
