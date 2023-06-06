"""Main loop."""

import logging

from aiogram import Bot, Dispatcher, executor
from aiogram.types import Message

logger = logging.getLogger(__name__)

with open("secret/tg_token") as f:
    bot = Bot(f.read(), parse_mode="HTML")
dp = Dispatcher(bot=bot)


@dp.message_handler()
async def echo(message: Message):
    """Echo bot."""
    await message.answer(message.text)


def main():
    executor.start_polling(dp, skip_updates=True)


if __name__ == "__main__":
    main()
