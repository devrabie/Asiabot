import asyncio
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, PicklePersistence
from src.config import settings
from src.bot.handlers import get_conversation_handler, start
from src.services.scheduler import SchedulerService
from src.database.db_manager import DBManager
from telegram.ext import CommandHandler
from loguru import logger

# Set up logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

async def post_init(application):
    logger.info("Running post_init...")

    # Initialize DB
    db_manager = DBManager()
    await db_manager.init_db()

    # Start Scheduler
    scheduler_service = SchedulerService(application)
    scheduler_service.start()
    logger.info("Scheduler started via post_init.")

def main():
    logger.info("Starting Asiabot...")

    # Check for BOT_TOKEN
    if not settings.BOT_TOKEN:
        logger.error("BOT_TOKEN not found in environment variables.")
        return

    application = ApplicationBuilder().token(settings.BOT_TOKEN).post_init(post_init).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(get_conversation_handler())

    logger.info("Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    main()
