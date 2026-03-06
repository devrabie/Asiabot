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
from src.services.recharge_manager import RechargeManager
from src.utils.card_parser import extract_card_number
from src.bot.admin_handlers import admin_dashboard, get_admin_handlers
import aiohttp

# States for Conversations
PHONE, OTP = range(2)
RECHARGE_INPUT = 2

# --- Handlers ---

async def _safe_answer(query):
    """Safely answer a callback query, ignoring timeout errors."""
    try:
        await query.answer()
    except Exception:
        pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends the main menu."""
    user = update.effective_user
    db = DBManager()
    await db.create_user_if_not_exists(user.id)
    await db.update_user_profile(user.id, user.username, user.first_name)

    keyboard = [
        [InlineKeyboardButton("📱 حساباتي", callback_data="my_accounts")],
        [InlineKeyboardButton("➕ إضافة حساب جديد", callback_data="add_account_start")],
        [InlineKeyboardButton("💳 شحن رصيد", callback_data="start_recharge")],
        [InlineKeyboardButton("💎 الخطط", callback_data="show_plans")],
        [InlineKeyboardButton("ℹ️ حول البوت", callback_data="about")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Check if this is a callback or a new message
    if update.callback_query:
        await _safe_answer(update.callback_query)
        await update.callback_query.edit_message_text("مرحباً بك في بوت آسياسيل! اختر من القائمة:", reply_markup=reply_markup)
    else:
        await update.message.reply_text("مرحباً بك في بوت آسياسيل! اختر من القائمة:", reply_markup=reply_markup)

async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback wrapper for returning to main menu."""
    await start(update, context)

async def _get_plans_text(user_id: int) -> str:
    """Helper to generate the plans and subscription status text."""
    db = DBManager()
    plans = await db.get_plans()
    user_sub = await db.get_user_subscription(user_id)

    text = "💎 **الخطط المتاحة**\n\n"
    text += f"خطة اشتراكك الحالية: **{user_sub['name']}**\n"
    text += f"الحد الأقصى للحسابات: `{user_sub['max_accounts']}`\n"
    text += f"شحن كروت (نص): `{user_sub.get('text_recharges_count', 0)}/{user_sub.get('max_text_recharges', 0)}`\n"
    text += f"شحن كروت (صور): `{user_sub.get('image_recharges_count', 0)}/{user_sub.get('max_image_recharges', 0)}`\n\n"

    for plan in plans:
        text += f"🔹 **{plan['name']}**\n"
        text += f"   💰 السعر: `{plan['price']} IQD`\n"
        text += f"   🔢 عدد الحسابات: `{plan['max_accounts']}`\n"
        text += f"   📝 شحن نصي: `{plan.get('max_text_recharges')}`\n"
        text += f"   📸 شحن صوري: `{plan.get('max_image_recharges')}`\n"
        if plan['description']:
            text += f"   ℹ️ {plan['description']}\n"
        text += "\n"

    subscribe_message = await db.get_setting("subscribe_message", "للاشتراك يرجى التواصل مع الدعم.")
    text += f"\n{subscribe_message}"
    return text

async def about_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows about info."""
    query = update.callback_query
    await _safe_answer(query)

    db = DBManager()
    text = await db.get_setting("about_text", "🤖 **Asiabot**\nبوت لإدارة حسابات آسياسيل.\nيمكنك مراقبة الرصيد وتجديد الرموز تلقائياً.\n\nDev: @YourUsername")

    keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(text=text, parse_mode="Markdown", reply_markup=reply_markup)

async def my_accounts_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lists user accounts."""
    query = update.callback_query
    await _safe_answer(query)
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
    """Shows details for a specific account, verifying and refreshing data live."""
    query = update.callback_query
    # We delay answering or show loading because we will do a network request
    try:
        await query.answer("جاري جلب تفاصيل الحساب...")
    except:
        pass
    await query.edit_message_text("⏳ جاري الاتصال بخوادم آسياسيل لجلب أحدث البيانات...")

    phone = query.data.split("_")[1]
    user_id = query.from_user.id

    db = DBManager()
    account = await db.get_account(phone, user_id)

    if not account:
        await query.edit_message_text("❌ هذا الحساب غير موجود أو لا تملك صلاحية الوصول إليه.")
        return

    # Attempt to fetch fresh data
    details_text = f"📱 **تفاصيل حساب آسياسيل:** `{phone}`\n"
    fresh_balance = None
    account_info = {}

    try:
        async with AsiacellClient() as client:
            # We try to get balance. If token expired, we might get 403/401
            balance_data = await client.get_balance(
                account["access_token"],
                account["device_id"],
                account["cookie"]
            )

            # Parse response
            if isinstance(balance_data, dict):
                 # Based on PHP: $balanceData['watch']['information']['mainBalance']
                 # My client returns response.get("data") which is likely the root of json response?
                 # Or inside 'watch'? PHP code: $response->getBody() then json_decode.
                 # Python client: return response.get("data")
                 # If Python client returns the full JSON body as 'data', then we access it.
                 # Let's assume the structure matches PHP expectations.

                 # Note: Python client might need adjustment if get_balance doesn't return full structure.
                 # client.get_balance returns response.get("data").
                 # If API returns { "watch": { ... } }, then balance_data has "watch".

                 info = balance_data.get("watch", {}).get("information", {})
                 raw_balance = info.get("mainBalance")

                 if raw_balance:
                     fresh_balance = float(str(raw_balance).replace(" IQD", "").replace(",", ""))
                     account_info['name'] = info.get("fullname", "N/A")
                     account_info['expiry'] = info.get("expiryDate", "N/A")

                     # Update DB
                     await db.update_balance(phone, fresh_balance)
                 else:
                     logger.warning(f"Unexpected balance structure: {balance_data}")

    except Exception as e:
        logger.warning(f"Failed to fetch balance for {phone}: {e}")
        # Try to handle token refresh if it's a 403/401 error
        # aiohttp exceptions usually have 'status' attribute
        if hasattr(e, 'status') and e.status in [401, 403]:
             details_text += "⚠️ انتهت صلاحية الجلسة. جاري محاولة التجديد...\n"
             try:
                 async with AsiacellClient() as client:
                     token_resp = await client.refresh_token(account["refresh_token"], account["device_id"])
                     if token_resp.access_token:
                         # Update DB
                         new_refresh = token_resp.refresh_token or account["refresh_token"]
                         await db.update_tokens(phone, token_resp.access_token, new_refresh)
                         details_text += "✅ تم تجديد الجلسة بنجاح.\n"

                         # Retry fetching balance immediately
                         try:
                             balance_data = await client.get_balance(
                                 token_resp.access_token,
                                 account["device_id"],
                                 account["cookie"]
                             )
                             info = balance_data.get("watch", {}).get("information", {})
                             raw_balance = info.get("mainBalance")

                             if raw_balance:
                                 fresh_balance = float(str(raw_balance).replace(" IQD", "").replace(",", ""))
                                 account_info['name'] = info.get("fullname", "N/A")
                                 account_info['expiry'] = info.get("expiryDate", "N/A")

                                 await db.update_balance(phone, fresh_balance)
                                 # Clear the warning message since we succeeded
                                 details_text = f"📱 **تفاصيل حساب آسياسيل:** `{phone}`\n"
                             else:
                                 details_text += "⚠️ تم التجديد ولكن فشل جلب الرصيد (بيانات غير متوقعة).\n"
                         except Exception as retry_err:
                             logger.warning(f"Retry balance fetch failed: {retry_err}")
                             details_text += "⚠️ تم التجديد ولكن فشل جلب الرصيد في المحاولة الثانية.\n"

                     else:
                         details_text += "❌ فشل تجديد التوكن. يرجى إعادة تسجيل الدخول.\n"
             except Exception as refresh_err:
                 details_text += f"❌ خطأ أثناء التجديد: {refresh_err}\n"
        else:
             details_text += f"❌ خطأ في الاتصال: {str(e)}\n"

    # Reload account from DB to get latest stored values (if updated)
    account = await db.get_account(phone, user_id)
    current_balance = account.get("current_balance", 0.0)

    details_text += f"💰 **الرصيد:** `{current_balance:,.2f} IQD`\n"
    if 'name' in account_info:
        details_text += f"👤 **الاسم:** {account_info['name']}\n"
    if 'expiry' in account_info:
        details_text += f"📅 **صالح لغاية:** {account_info['expiry']}\n"

    # Balance comparison logic (PHP: notify if changed)
    # Since we updated DB above, current_balance is the latest.
    # The previous balance logic is handled implicitly by update_balance overwriting it,
    # but to show "change" we would need to know the *previous* state before update.
    # For now, just showing current is sufficient as per basic requirement.

    # Buttons
    keyboard = []
    keyboard.append([InlineKeyboardButton("🔄 تحديث معلومات الحساب", callback_data=f"refresh_{phone}")])

    # Primary Receiver Toggle
    is_primary = account.get("is_primary_receiver", 0)
    if is_primary:
        keyboard.append([InlineKeyboardButton("✅ هذا هو الحساب الرئيسي للاستقبال", callback_data="noop")])
    else:
        keyboard.append([InlineKeyboardButton("📥 تعيين كـ مستقبل رئيسي", callback_data=f"setprimary_{phone}")])

    keyboard.append([InlineKeyboardButton("🗑️ حذف الحساب", callback_data=f"delconf_{phone}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="my_accounts")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(text=details_text, parse_mode="Markdown", reply_markup=reply_markup)

async def refresh_balance_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Refreshes balance for an account by reusing detailed view logic."""
    # Since account_details_handler now does a fresh fetch, we just redirect to it.
    await account_details_handler(update, context)

async def delete_confirm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Asks for deletion confirmation."""
    query = update.callback_query
    await _safe_answer(query)
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
    await _safe_answer(query)
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

async def set_primary_receiver_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sets the account as primary receiver."""
    query = update.callback_query
    await _safe_answer(query)

    phone = query.data.split("_")[1]
    user_id = query.from_user.id

    db = DBManager()
    await db.set_primary_receiver(user_id, phone)

    await query.message.reply_text(f"✅ تم تعيين الحساب {phone} كمستقبل رئيسي للرصيد.")
    # Refresh view
    await account_details_handler(update, context)

# --- Recharge Conversation Handlers ---

async def start_recharge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Starts the recharge conversation."""
    user_id = update.effective_user.id
    db = DBManager()
    accounts = await db.get_user_accounts(user_id)

    if not accounts:
        text = "❌ لا توجد حسابات مضافة. الرجاء إضافة رقم آسياسيل أولاً."
        keyboard = [[InlineKeyboardButton("➕ إضافة حساب جديد", callback_data="add_account_start")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.message.reply_text(text, reply_markup=reply_markup)
        else:
            await update.message.reply_text(text, reply_markup=reply_markup)
        return ConversationHandler.END

    text = (
        "💳 **شحن رصيد**\n\n"
        "قم بإرسال رقم الكارت (14 أو 15 رقم).\n"
        "يمكنك إرسال رقم الكارت كتابةً أو صورة الكارت."
    )

    keyboard = [[InlineKeyboardButton("🔙 إلغاء", callback_data="cancel_conv")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await _safe_answer(update.callback_query)
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)
    return RECHARGE_INPUT

async def recharge_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the card number input."""
    user_id = update.effective_user.id
    db = DBManager()
    sub = await db.get_user_subscription(user_id)

    text = ""
    feature_type = "text"

    if update.message.text:
        if sub['text_recharges_count'] >= sub['max_text_recharges']:
             text = "❌ لقد وصلت للحد الأقصى المسموح به لشحن الكروت عبر النص في خطتك.\n\n"
             text += await _get_plans_text(user_id)
             keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")]]
             await update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
             return ConversationHandler.END
        text = update.message.text
    elif update.message.photo:
        if sub['image_recharges_count'] >= sub['max_image_recharges']:
             text = "❌ لقد وصلت للحد الأقصى المسموح به لشحن الكروت عبر الصور في خطتك.\n\n"
             text += await _get_plans_text(user_id)
             keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")]]
             await update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
             return ConversationHandler.END
        feature_type = "image"
        await update.message.reply_text("⏳ جاري تحليل الصورة واستخراج الكود...")
        try:
            photo = update.message.photo[-1]
            file = await context.bot.get_file(photo.file_id)
            async with AsiacellClient() as client:
                text = await client.extract_text_from_image_url(file.file_path)
        except Exception as e:
            logger.error(f"Failed to process photo: {e}")
            await update.message.reply_text("❌ حدث خطأ أثناء معالجة الصورة.")
            return RECHARGE_INPUT

    # Fallback to caption if available and OCR didn't find anything (or it wasn't a photo)
    if not text and update.message.caption:
        text = update.message.caption

    # Extract code using robust logic
    code = extract_card_number(text)

    if not code:
        await update.message.reply_text("❌ لم يتم العثور على كود صالح. يرجى إرسال كود يتكون من 14 أو 15 رقم.")
        return RECHARGE_INPUT

    msg = await update.message.reply_text(f"🔄 جاري معالجة الكود: `{code}` ...", parse_mode="Markdown")

    try:
        recharge_manager = RechargeManager()
        result_message = await recharge_manager.process_smart_recharge(user_id, code)

        # Only increment if it looks like a valid attempt (even if unconfirmed by balance)
        # If it was an explicit failure like "invalid card", we still count it as a "use" of the feature?
        # User request says "number of times using features", so yes.
        await db.increment_usage(user_id, feature_type)

        await msg.edit_text(result_message, parse_mode="Markdown")
    except Exception as e:
        logger.exception(f"Recharge failed: {e}")
        await msg.edit_text(f"❌ حدث خطأ غير متوقع: {e}")

    return ConversationHandler.END

async def show_plans_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows available subscription plans."""
    query = update.callback_query
    await _safe_answer(query)

    text = await _get_plans_text(query.from_user.id)
    keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")]]
    await query.edit_message_text(text=text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

# --- Add Account Conversation ---

async def add_account_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Starts the add account flow from callback."""
    query = update.callback_query
    user_id = update.effective_user.id

    db = DBManager()

    # Check limit
    sub = await db.get_user_subscription(user_id)
    accounts = await db.get_user_accounts(user_id)
    if len(accounts) >= sub['max_accounts']:
        text = "❌ لقد تجاوزت الحد الأقصى للحسابات المسموح به في خطتك.\n\n"
        text += await _get_plans_text(user_id)
        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")]]

        if query:
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return ConversationHandler.END

    text = "الرجاء إرسال رقم آسياسيل الخاص بك (077xxxxxxxx):"
    keyboard = [[InlineKeyboardButton("🔙 إلغاء", callback_data="cancel_conv")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        await _safe_answer(query)
        await query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)
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

            if not pid and parsed_url.fragment:
                # Handle fragment-based URLs (e.g., #/path?PID=...)
                fragment_parts = parsed_url.fragment.split("?", 1)
                if len(fragment_parts) > 1:
                    fragment_query = urllib.parse.parse_qs(fragment_parts[1])
                    pid = fragment_query.get("PID", [None])[0]

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

async def cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancels the conversation via callback button."""
    query = update.callback_query
    if query:
        await _safe_answer(query)
        # Return to main menu instead of just saying cancelled
        await start(update, context)
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
        CallbackQueryHandler(set_primary_receiver_handler, pattern="^setprimary_"),
    ]

    # Add Account Conversation
    add_account_conv = ConversationHandler(
        entry_points=[
            CommandHandler("add_account", add_account_start),
            CallbackQueryHandler(add_account_start, pattern="^add_account_start$")
        ],
        states={
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, phone_handler)],
            OTP: [MessageHandler(filters.TEXT & ~filters.COMMAND, otp_handler)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(cancel_callback, pattern="^cancel_conv$"),
            CommandHandler("start", start), # Reset if user sends /start
        ],
        allow_reentry=True,
    )

    # Recharge Conversation
    recharge_conv = ConversationHandler(
        entry_points=[
            CommandHandler("recharge", start_recharge),
            CallbackQueryHandler(start_recharge, pattern="^start_recharge$")
        ],
        states={
            RECHARGE_INPUT: [MessageHandler((filters.TEXT & ~filters.COMMAND) | filters.PHOTO, recharge_input_handler)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(cancel_callback, pattern="^cancel_conv$"),
            CommandHandler("start", start), # Reset if user sends /start
        ],
        allow_reentry=True,
    )

    # Add show_plans callback
    callback_handlers.append(CallbackQueryHandler(show_plans_handler, pattern="^show_plans$"))

    # Get Admin Conversation Handlers & Callbacks
    admin_handlers = get_admin_handlers()

    return [
        add_account_conv,
        recharge_conv,
        CommandHandler("start", start),
        CommandHandler("admin", admin_dashboard)
    ] + admin_handlers + callback_handlers
