import re
import urllib.parse
from telegram import Update, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from loguru import logger
from src.api.client import AsiacellClient
from src.database.db_manager import DBManager

# States for Add Account Conversation
PHONE, OTP = range(2)

# --- Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends the main menu."""
    keyboard = [
        [InlineKeyboardButton("📱 حساباتي", callback_data="my_accounts")],
        [InlineKeyboardButton("➕ إضافة حساب جديد", callback_data="add_account_start")],
        [InlineKeyboardButton("ℹ️ حول البوت", callback_data="about")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Check if this is a callback or a new message
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("مرحباً بك في بوت آسياسيل! اختر من القائمة:", reply_markup=reply_markup)
    else:
        await update.message.reply_text("مرحباً بك في بوت آسياسيل! اختر من القائمة:", reply_markup=reply_markup)

async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback wrapper for returning to main menu."""
    await start(update, context)

async def about_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows about info."""
    query = update.callback_query
    await query.answer()

    text = (
        "🤖 **Asiabot**\n"
        "بوت لإدارة حسابات آسياسيل.\n"
        "يمكنك مراقبة الرصيد وتجديد الرموز تلقائياً.\n\n"
        "Dev: @YourUsername"
    )
    keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(text=text, parse_mode="Markdown", reply_markup=reply_markup)

async def my_accounts_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lists user accounts."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    db = DBManager()
    accounts = await db.get_user_accounts(user_id)

    keyboard = []
    if accounts:
        for acc in accounts:
            phone = acc["phone_number"]
            keyboard.append([InlineKeyboardButton(f"📱 {phone}", callback_data=f"acc_{phone}")])
    else:
        keyboard.append([InlineKeyboardButton("لا توجد حسابات مسجلة", callback_data="noop")])

    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text("اختر حساباً لإدارته:", reply_markup=reply_markup)

async def account_details_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows details for a specific account."""
    query = update.callback_query
    await query.answer()

    # Extract phone from callback_data "acc_077xxxxxxxx"
    phone = query.data.split("_")[1]
    user_id = query.from_user.id

    db = DBManager()
    account = await db.get_account(phone, user_id)

    if not account:
        await query.edit_message_text("هذا الحساب غير موجود أو لا تملك صلاحية الوصول إليه.")
        return

    # Prepare info text
    balance = account.get("current_balance", 0.0)
    # Expiry date is not in DB currently (based on schema), skipping or mocking
    text = (
        f"📱 **رقم الهاتف:** `{phone}`\n"
        f"💰 **الرصيد الحالي:** `{balance}`\n"
    )

    keyboard = [
        [InlineKeyboardButton("🔄 تحديث الرصيد", callback_data=f"refresh_{phone}")],
        [InlineKeyboardButton("💳 شحن رصيد", callback_data=f"topup_{phone}")],
        [InlineKeyboardButton("🗑️ حذف الحساب", callback_data=f"delconf_{phone}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="my_accounts")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(text=text, parse_mode="Markdown", reply_markup=reply_markup)

async def refresh_balance_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Refreshes balance for an account."""
    query = update.callback_query
    # Show loading status
    await query.answer("جاري التحديث...", show_alert=False)

    phone = query.data.split("_")[1]
    user_id = query.from_user.id

    db = DBManager()
    account = await db.get_account(phone, user_id)

    if not account:
        await query.edit_message_text("خطأ: الحساب غير موجود.")
        return

    try:
        async with AsiacellClient() as client:
            balance_data = await client.get_balance(
                account["access_token"],
                account["device_id"],
                account["cookie"]
            )

            # Similar safe extraction logic as scheduler
            if isinstance(balance_data, dict):
                raw_balance = balance_data.get("mainBalance", balance_data.get("balance"))
                if raw_balance is not None:
                    new_balance = float(raw_balance)
                    await db.update_balance(phone, new_balance)

                    # Refresh the view
                    await account_details_handler(update, context)
                    return

        await query.answer("فشل تحديث الرصيد. حاول لاحقاً.", show_alert=True)

    except Exception as e:
        logger.error(f"Manual refresh failed for {phone}: {e}")
        await query.answer("حدث خطأ أثناء الاتصال.", show_alert=True)

async def delete_confirm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Asks for deletion confirmation."""
    query = update.callback_query
    await query.answer()
    phone = query.data.split("_")[1]

    text = f"هل أنت متأكد من حذف الحساب `{phone}`؟"
    keyboard = [
        [
            InlineKeyboardButton("نعم، احذف", callback_data=f"delaction_{phone}"),
            InlineKeyboardButton("لا، إلغاء", callback_data=f"acc_{phone}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text=text, parse_mode="Markdown", reply_markup=reply_markup)

async def delete_action_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Deletes the account."""
    query = update.callback_query
    await query.answer()
    phone = query.data.split("_")[1]
    user_id = query.from_user.id

    db = DBManager()
    success = await db.delete_account(phone, user_id)

    if success:
        await query.answer("تم حذف الحساب بنجاح.", show_alert=True)
        await my_accounts_handler(update, context)
    else:
        await query.answer("فشل حذف الحساب.", show_alert=True)
        await account_details_handler(update, context)

async def top_up_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Placeholder for Top Up."""
    query = update.callback_query
    await query.answer()

    # In a full implementation, this would start a conversation asking for the code.
    # For now, we just inform the user.
    await query.message.reply_text("ميزة شحن الرصيد ستتوفر قريباً! (أرسل الكود هنا يدوياً إذا كنت المطور)")

# --- Add Account Conversation ---

async def add_account_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Starts the add account flow from callback."""
    query = update.callback_query
    if query:
        await query.answer()
        await query.message.reply_text("الرجاء إرسال رقم آسياسيل الخاص بك (077xxxxxxxx):")
    else:
        await update.message.reply_text("الرجاء إرسال رقم آسياسيل الخاص بك (077xxxxxxxx):")
    return PHONE

async def phone_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone_number = update.message.text.strip()

    if not re.match(r"^077\d{8}$", phone_number):
        await update.message.reply_text("تنسيق خاطئ. الرجاء إرسال رقم صحيح يبدأ بـ 077.")
        return PHONE

    context.user_data["phone_number"] = phone_number
    msg = await update.message.reply_text("جاري الاتصال...")

    try:
        async with AsiacellClient() as client:
            cookie = await client.get_login_cookie()
            if not cookie:
                 await msg.edit_text("فشل في الحصول على ملف تعريف الارتباط. حاول مرة أخرى.")
                 return ConversationHandler.END

            context.user_data["cookie"] = cookie
            device_id = client.generate_device_id()
            context.user_data["device_id"] = device_id

            login_response = await client.send_login_code(device_id, cookie, phone_number)
            next_url = login_response.nextUrl

            if not next_url:
                 await msg.edit_text("فشل إرسال الرمز. استجابة غير متوقعة.")
                 return ConversationHandler.END

            parsed_url = urllib.parse.urlparse(next_url)
            query_params = urllib.parse.parse_qs(parsed_url.query)
            pid = query_params.get("PID", [None])[0]

            if not pid:
                 debug_info = f"NextUrl: {next_url}\nResponse: {login_response}"
                 logger.error(f"Failed to extract PID. {debug_info}")
                 await msg.edit_text(f"فشل استخراج PID.\n\nDebug Info:\n{debug_info}")
                 return ConversationHandler.END

            context.user_data["pid"] = pid
            await msg.edit_text("تم إرسال الرمز. الرجاء إرسال رمز التحقق (OTP).")
            return OTP

    except Exception as e:
        logger.exception(f"Error in phone_handler: {e}")
        await msg.edit_text("حدث خطأ ما. حاول مرة أخرى.")
        return ConversationHandler.END

async def otp_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    otp_code = update.message.text.strip()
    data = context.user_data

    msg = await update.message.reply_text("جاري التحقق...")

    try:
        async with AsiacellClient() as client:
            token_response = await client.validate_sms_code(
                data["cookie"], data["device_id"], data["pid"], otp_code
            )

            if not token_response.access_token:
                error_msg = token_response.message or "رمز خاطئ."
                await msg.edit_text(f"فشل تسجيل الدخول: {error_msg}")
                return ConversationHandler.END

            db_manager = DBManager()
            # db_manager.init_db() is called in main.py

            user_id = update.message.from_user.id
            await db_manager.add_account(
                user_id=user_id,
                phone_number=data["phone_number"],
                device_id=data["device_id"],
                cookie=data["cookie"],
                access_token=token_response.access_token,
                refresh_token=token_response.refresh_token
            )

            await msg.edit_text("✅ تم تسجيل الدخول وحفظ الحساب بنجاح!")
            # Show menu again
            await start(update, context)

    except Exception as e:
        logger.exception(f"Error in otp_handler: {e}")
        await msg.edit_text("حدث خطأ أثناء التحقق.")

    finally:
        context.user_data.clear()

    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("تم الإلغاء.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# --- Export Handlers ---

def get_handlers():
    """Returns a list of handlers to register in main.py"""

    # Callback Handlers
    callback_handlers = [
        CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"),
        CallbackQueryHandler(about_handler, pattern="^about$"),
        CallbackQueryHandler(my_accounts_handler, pattern="^my_accounts$"),
        CallbackQueryHandler(account_details_handler, pattern="^acc_"),
        CallbackQueryHandler(refresh_balance_handler, pattern="^refresh_"),
        CallbackQueryHandler(delete_confirm_handler, pattern="^delconf_"),
        CallbackQueryHandler(delete_action_handler, pattern="^delaction_"),
        CallbackQueryHandler(top_up_handler, pattern="^topup_"),
        # 'add_account_start' is handled by ConversationHandler entry point
    ]

    # Conversation Handler
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("add_account", add_account_start),
            CallbackQueryHandler(add_account_start, pattern="^add_account_start$")
        ],
        states={
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, phone_handler)],
            OTP: [MessageHandler(filters.TEXT & ~filters.COMMAND, otp_handler)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    return [conv_handler, CommandHandler("start", start)] + callback_handlers
