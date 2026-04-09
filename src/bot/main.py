import asyncio
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, PicklePersistence, ContextTypes
from src.config import settings
from src.bot.handlers import get_handlers
from src.services.scheduler import SchedulerService
from src.database.db_manager import DBManager
from telegram.ext import CommandHandler
from loguru import logger

# Set up logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# Reduce noise from libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and handle specific telegram errors."""
    logger.error(f"Exception while handling an update: {context.error}")

    # Specific handling for callback query timeout
    if "Query is too old" in str(context.error):
        return

    # Log full traceback for other errors
    import traceback
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)
    logger.error(f"Traceback:\n{tb_string}")

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

    builder = ApplicationBuilder().token(settings.BOT_TOKEN).post_init(post_init)

    if settings.TELEGRAM_API_URL:
        logger.info(f"Using custom Telegram API URL: {settings.TELEGRAM_API_URL}")
        builder.base_url(settings.TELEGRAM_API_URL)
        # If it's a local server, we might want to enable local_mode as well
        if "localhost" in settings.TELEGRAM_API_URL or "127.0.0.1" in settings.TELEGRAM_API_URL:
            builder.local_mode(True)

    application = builder.build()

    # Add error handler
    application.add_error_handler(error_handler)

    # Register all handlers
    for handler in get_handlers():
        application.add_handler(handler)

    logger.info("Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    main()
