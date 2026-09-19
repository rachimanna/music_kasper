from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message):
    welcome_text = (
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        "Я музыкальный поисковый бот **music_kasper** 🎵\n\n"
        "🔎 **Как мной пользоваться:**\n"
        "1. **В личке:** просто напиши название песни или `найди Blinding Lights`\n"
        "2. **В группах:** добавь меня в группу и напиши `@имя_бота песня` или `найди трек`\n"
        "3. **В любом чате (Inline):** напиши прямо в поле ввода `@имя_бота название`\n\n"
        "Попробуй прямо сейчас: отправь мне любое название!"
    )
    await message.answer(welcome_text, parse_mode="Markdown")


@router.message(Command("help"))
async def cmd_help(message: Message):
    help_text = (
        "💡 **Справка по командам:**\n\n"
        "• Просто отправь название трека или артиста\n"
        "• `найди <песня>` — быстрый поиск\n"
        "• В группах: упомяни бота перед запросом\n"
        "• В диалогах: используй inline-режим через `@music_kasper_bot трек`"
    )
    await message.answer(help_text, parse_mode="Markdown")
