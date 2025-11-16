import asyncio
import logging
from aiogram import Bot, Dispatcher

from teletube.config import BOT_TOKEN, LOG_LEVEL_STR, BOT_NAME
from teletube.handlers import (
    cmd_start, cmd_help, cmd_addvideo, cmd_leaderboard, cmd_leaderboardpic,
    cmd_myprofile, cmd_achievements, cmd_daily, cmd_shop, cb_shop_buy,
    admin_add_currency, admin_add_subs, admin_delete_db, admin_stats
)

def _setup_logging():
    logging.basicConfig(level=getattr(logging, LOG_LEVEL_STR, logging.INFO), format="%(asctime)s | %(levelname)s | %(message)s")
    logger = logging.getLogger(__name__)
    return logger


async def main():
    logger = _setup_logging()
    if not BOT_TOKEN:
        logger.critical("BOT_TOKEN is missing. Set it in .env")
        return

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    dp.message.register(cmd_start, commands=["start"])
    dp.message.register(cmd_help, commands=["help", "info"])
    dp.message.register(cmd_addvideo, commands=["addvideo", "add", "video", "newvideo", "publishvideo", "publish"])
    dp.message.register(cmd_leaderboard, commands=["leaderboard", "lp"])
    dp.message.register(cmd_leaderboardpic, commands=["leaderboardpic", "lppic"])
    dp.message.register(cmd_myprofile, commands=["myprofile"])
    dp.message.register(cmd_achievements, commands=["achievements"])
    dp.message.register(cmd_daily, commands=["daily"])
    dp.message.register(cmd_shop, commands=["shop"])

    dp.message.register(admin_add_currency, commands=["CHEATaddcoins"])
    dp.message.register(admin_add_subs, commands=["CHEATaddsub"])
    dp.message.register(admin_delete_db, commands=["CHEATDeleteDatabase"])
    dp.message.register(admin_stats, commands=["botstats"])

    dp.callback_query.register(cb_shop_buy, lambda c: c.data and c.data.startswith("shop_buy:"))

    logger.info("%s is starting...", BOT_NAME)
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    logger = _setup_logging()
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Stopped by user")


