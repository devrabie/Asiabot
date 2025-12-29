import asyncio
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, PicklePersistence
from src.config import settings
from src.bot.handlers import get_conversation_handler, start
from telegram.ext import CommandHandler
from loguru import logger

# Set up logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

def main():
    logger.info("Starting Asiabot...")

    # Check for BOT_TOKEN
    if not settings.BOT_TOKEN:
        logger.error("BOT_TOKEN not found in environment variables.")
        return

    application = ApplicationBuilder().token(settings.BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(get_conversation_handler())

    logger.info("Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    main()
