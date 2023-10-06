"""Main loop."""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from ti4_tg_bot.bot.lobby_logic import cmds, r_lobby


async def async_main() -> None:
    """Async main runner."""
    # Set up token
    try:
        with open("/run/secrets/tg_token") as f:
            TOKEN = f.read()
    except Exception:
        with open("secret/tg_token") as f:
            TOKEN = f.read()

    # Set up storage
    if True:
        storage = MemoryStorage()
    # TODO: Add redis storage as option

    # Dispatcher is a root router
    dp = Dispatcher(storage=storage)
    # ... and all other routers should be attached to Dispatcher
    # dp.include_router(new_router)
    dp.include_router(r_lobby)

    # Initialize Bot instance with a default parse mode which will be passed to all API
    bot = Bot(TOKEN, parse_mode="HTML")

    # Set commands
    await bot.set_my_commands([v for k, v in cmds.items()])

    # And the run events dispatching
    await dp.start_polling(bot)


def main():
    logging.basicConfig(level=logging.INFO)
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
