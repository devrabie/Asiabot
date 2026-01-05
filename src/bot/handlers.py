import re
import urllib.parse
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    filters,
)
from loguru import logger
from src.api.client import AsiacellClient
from src.database.repository import AccountRepository

# States
PHONE, OTP = range(2)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Welcome to Asiabot! Use /add_account to login.")

async def add_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Please send your Asiacell number (077xxxxxxxx).",
        reply_markup=ReplyKeyboardRemove(),
    )
    return PHONE

async def phone_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone_number = update.message.text.strip()

    # Validate phone number
    if not re.match(r"^077\d{8}$", phone_number):
        await update.message.reply_text("Invalid format. Please send a valid number starting with 077.")
        return PHONE

    context.user_data["phone_number"] = phone_number

    await update.message.reply_text("Connecting...")

    try:
        async with AsiacellClient() as client:
            # 1. Get Login Cookie
            cookie = await client.get_login_cookie()
            if not cookie:
                 await update.message.reply_text("Failed to get login cookie. Please try again.")
                 return ConversationHandler.END

            context.user_data["cookie"] = cookie

            # 2. Generate Device ID
            device_id = client.generate_device_id()
            context.user_data["device_id"] = device_id

            # 3. Send Login Code
            login_response = await client.send_login_code(device_id, cookie, phone_number)

            # Extract PID from nextUrl
            next_url = login_response.nextUrl
            if not next_url:
                 logger.error(f"Unexpected response from send_login_code: {login_response}")
                 await update.message.reply_text("Failed to send login code. Unexpected API response.")
                 return ConversationHandler.END

            parsed_url = urllib.parse.urlparse(next_url)
            query_params = urllib.parse.parse_qs(parsed_url.query)
            pid = query_params.get("PID", [None])[0]

            if not pid:
                 await update.message.reply_text("Failed to extract PID.")
                 return ConversationHandler.END

            context.user_data["pid"] = pid

            await update.message.reply_text("Code sent. Send the OTP.")
            return OTP

    except Exception as e:
        logger.exception(f"Error in phone_handler: {e}")
        await update.message.reply_text("An error occurred. Please try again.")
        return ConversationHandler.END

async def otp_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    otp_code = update.message.text.strip()

    data = context.user_data
    phone_number = data.get("phone_number")
    pid = data.get("pid")
    device_id = data.get("device_id")
    cookie = data.get("cookie")

    try:
        await update.message.reply_text("Verifying OTP...")

        async with AsiacellClient() as client:
            token_response = await client.validate_sms_code(cookie, device_id, pid, otp_code)

            access_token = token_response.access_token
            refresh_token = token_response.refresh_token

            if not access_token:
                error_msg = token_response.message or "Invalid OTP or failed to validate."
                await update.message.reply_text(f"Login failed: {error_msg}")
                return ConversationHandler.END

            # Save to DB
            repo = AccountRepository()
            await repo.init_db()
            await repo.save_account(phone_number, access_token, refresh_token, device_id, cookie)

            await update.message.reply_text("Login Successful! Account Saved.")

    except Exception as e:
        logger.exception(f"Error in otp_handler: {e}")
        await update.message.reply_text("An error occurred during verification.")

    finally:
        context.user_data.clear()

    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Operation cancelled.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

def get_conversation_handler():
    return ConversationHandler(
        entry_points=[CommandHandler("add_account", add_account)],
        states={
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, phone_handler)],
            OTP: [MessageHandler(filters.TEXT & ~filters.COMMAND, otp_handler)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
