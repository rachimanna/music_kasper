import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.config import config
from bot.database.db import db
from bot.middlewares.throttling import ThrottlingMiddleware
from bot.handlers import common, search, inline


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

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot stopped.")
