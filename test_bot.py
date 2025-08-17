#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тестовый скрипт для TeleTube бота
Запускает бота с отключенной проверкой подписки для тестирования
"""

import asyncio
import logging
import os
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
load_dotenv()
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)
BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
@dp.message(Command("test"))
async def cmd_test(message: types.Message):
    await message.answer(f"✅ \n ID: {message.from_user.id}")
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(f"/test для проверки.")
async def main():
    try:
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        logger.info("Бот вскрылся")
    finally:
        await bot.session.close()
if __name__ == "__main__":
    asyncio.run(main())
