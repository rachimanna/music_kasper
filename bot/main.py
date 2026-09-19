import asyncio
import logging
import os
import sys
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.config import config
from bot.database.db import db
from bot.middlewares.throttling import ThrottlingMiddleware
from bot.handlers import common, search, inline

# Простой веб-ответ для Render, чтобы сервис не падал
async def handle_ping(request):
    return web.Response(text="music_kasper bot is running 24/7!")


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    app.router.add_get("/health", handle_ping)
    
    port = int(os.getenv("PORT", 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"Ping server started on port {port}")


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    logger = logging.getLogger(__name__)
    logger.info("Starting music_kasper bot...")

    await db.init()

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    if not config.BOT_USERNAME:
        bot_info = await bot.get_me()
        config.BOT_USERNAME = bot_info.username
        logger.info(f"Bot authorized as @{config.BOT_USERNAME}")

    dp = Dispatcher()

    dp.message.middleware(ThrottlingMiddleware())
    dp.callback_query.middleware(ThrottlingMiddleware())

    dp.include_router(common.router)
    dp.include_router(inline.router)
    dp.include_router(search.router)

    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Bot started and ready to receive updates!")

    # Запускаем фоновый веб-сервер для Render
    await start_web_server()

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot stopped.")
