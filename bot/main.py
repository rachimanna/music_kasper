import asyncio
import logging
import sys
from typing import Optional

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiohttp import web

from bot.config import config
from bot.database.db import db
from bot.handlers import common, inline, search
from bot.services.authorized_audio_service import audio_service, ffmpeg_available
from bot.services.deezer_service import deezer

logger = logging.getLogger("bot")


async def handle_ping(request: web.Request) -> web.Response:
    return web.Response(text="music_kasper bot is running")


async def start_web_server() -> web.AppRunner:
    """Маленький HTTP-сервер: Render требует, чтобы веб-сервис слушал порт."""
    app = web.Application()
    app.router.add_get("/", handle_ping)
    app.router.add_get("/health", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", config.PORT).start()
    logger.info("Health server started on port %s", config.PORT)
    return runner


def check_environment() -> None:
    if not audio_service.configured():
        logger.warning("AUDIO_SOURCE_URL_TEMPLATE is not set — full tracks will not be available")
    else:
        error = audio_service.validate_template()
        if error:
            logger.error(error)
    if not ffmpeg_available():
        logger.warning("ffmpeg/ffprobe not found — audio conversion will fail")


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    logger.info("Starting music_kasper bot…")

    runner: Optional[web.AppRunner] = None
    bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    try:
        # Веб-сервер поднимаем первым, чтобы Render сразу увидел открытый порт.
        if config.WEB_SERVER_ENABLED:
            runner = await start_web_server()

        await db.init()
        check_environment()

        me = await bot.get_me()
        config.BOT_USERNAME = me.username or ""
        logger.info("Authorized as @%s", config.BOT_USERNAME)

        dp = Dispatcher()
        dp.include_routers(common.router, inline.router, search.router)

        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Bot is ready")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

    finally:
        await deezer.close()
        await audio_service.close()
        await db.close()
        if runner is not None:
            await runner.cleanup()
        await bot.session.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
