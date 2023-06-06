"""Main loop."""

import asyncio
import logging

from aiogram import Bot, Dispatcher

from ti4_tg_bot.bot.logic import router


async def async_main() -> None:
    """Async main runner."""
    with open("secret/tg_token") as f:
        TOKEN = f.read()
    # Dispatcher is a root router
    dp = Dispatcher()
    # ... and all other routers should be attached to Dispatcher
    dp.include_router(router)

    # Initialize Bot instance with a default parse mode which will be passed to all API
    bot = Bot(TOKEN, parse_mode="HTML")
    # And the run events dispatching
    await dp.start_polling(bot)


def main():
    logging.basicConfig(level=logging.INFO)
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
