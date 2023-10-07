# ti4-tg-bot

Telegram bot for TI4.

## Getting Started

### Telegram Token

You need to create a new bot for yourself.

Get a Telegram bot token from [BotFather](https://t.me/BotFather)
and save it as a plain-text file to `secret/tg_token`.

### Docker

You will need `docker` installed to run the dockerized version.

Just run `docker compose up --build -d` to build and let it run.
It should work on Linux x86 and ARM environments.

### Native

For running outside of docker, install `mamba` or `conda` (I recommend `mamba-forge`).

Run `mamba env create` / `conda env create` to create the environment.

You can run the bot with `ti4tg` or `python -m ti4_tg_bot.main`
