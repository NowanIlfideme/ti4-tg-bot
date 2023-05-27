"""Telegram bot code."""

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

with open("secret/tg_token") as f:
    app = ApplicationBuilder().token(f.read()).build()


async def hello(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(f"Hello {update.effective_user.first_name}")


app.add_handler(CommandHandler("hello", hello))

app.run_polling()
