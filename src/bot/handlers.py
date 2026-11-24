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
from src.services.ocr_service import download_telegram_photo_bytes, extract_card_from_image_bytes
from src.utils.card_parser import extract_card_number
from src.bot.admin_handlers import admin_dashboard, get_admin_handlers
from src.bot.ui_helpers import (
    BTN_ICON_ABOUT,
    BTN_ICON_ACCOUNTS,
    BTN_ICON_ADD,
    BTN_ICON_BACK,
    BTN_ICON_CANCEL,
    BTN_ICON_CHECK,
    BTN_ICON_HOME,
    BTN_ICON_PHONE,
    BTN_ICON_PLANS,
    BTN_ICON_RECHARGE,
    BTN_ICON_REFRESH,
    BTN_ICON_TRASH,
    E_BOLT,
    E_CARD,
    E_CROWN,
    E_DIAMOND,
    E_ERROR,
    E_GROWTH,
    E_INFO,
    E_PENDING,
    E_ROCKET,
    E_STAR,
    E_STATS,
    E_SUCCESS,
    E_USER,
    E_WARN,
    btn,
    build_card,
    esc,
)
import aiohttp

# States for Conversations
PHONE, OTP = range(2)
RECHARGE_INPUT = 2

# --- Handlers ---

async def _safe_answer(query, text=None, show_alert=False):
    """Safely answer a callback query, ignoring timeout errors."""
    try:
        await query.answer(text=text, show_alert=show_alert)
    except Exception:
        pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends the main menu with a live status card and styled action buttons."""
    user = update.effective_user
    db = DBManager()
    await db.create_user_if_not_exists(user.id)
    await db.update_user_profile(user.id, user.username, user.first_name)

    sub = await db.get_user_subscription(user.id)
    accounts = await db.get_user_accounts(user.id)
    primary = next((a["phone_number"] for a in accounts if a.get("is_primary_receiver")), None)

    text_rem = max(0, (sub.get("max_text_recharges", 0) or 0) - (sub.get("text_recharges_count", 0) or 0))
    img_rem = max(0, (sub.get("max_image_recharges", 0) or 0) - (sub.get("image_recharges_count", 0) or 0))

    lines = [
        f"{E_USER} <b>مرحباً بك</b> {esc(user.first_name or 'عزيزي')}!",
        f"{E_DIAMOND} <b>الخطة:</b> <code>{esc(sub.get('name', 'Free'))}</code>",
        f"{E_CARD} <b>الحسابات المسجلة:</b> <code>{len(accounts)}/{sub.get('max_accounts', 0)}</code>",
        f"{E_BOLT} <b>الرصيد المتبقي للعمليات:</b> نصي <code>{text_rem}</code> • صوري <code>{img_rem}</code>",
    ]
    if primary:
        lines.append(f"{E_SUCCESS} <b>المستلم الرئيسي:</b> <code>{esc(primary)}</code>")

    card_text = build_card(
        f"{E_CROWN} لوحة تحكم بوت آسياسيل",
        lines,
        footer="تلميح: يمكنك إرسال صورة الكرت مباشرة في أي وقت للشحن التلقائي",
    )

    keyboard = [
        [btn("شحن رصيد", "start_recharge", BTN_ICON_RECHARGE, "success")],
        [
            btn("حساباتي", "my_accounts", BTN_ICON_ACCOUNTS, "primary"),
            btn("إضافة حساب", "add_account_start", BTN_ICON_ADD, "success"),
        ],
        [
            btn("الخطط", "show_plans", BTN_ICON_PLANS, "primary"),
            btn("حول البوت", "about", BTN_ICON_ABOUT, "primary"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await _safe_answer(update.callback_query)
        await update.callback_query.edit_message_text(
            card_text, parse_mode="HTML", reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            card_text, parse_mode="HTML", reply_markup=reply_markup
        )

async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback wrapper for returning to main menu."""
    await start(update, context)

def _escape_markdown(text: str) -> str:
    """Escapes underscores and asterisks for Markdown (Legacy)."""
    if not text: return ""
    return str(text).replace("_", "\\_").replace("*", "\\*")

async def _get_user_status_text(user_id: int) -> str:
    """Helper to generate the current subscription status card in HTML."""
    db = DBManager()
    user_sub = await db.get_user_subscription(user_id)
    user_data = await db.get_user_by_id(user_id)

    lines = [
        f"{E_DIAMOND} <b>الخطة:</b> <code>{esc(user_sub['name'])}</code>",
        f"{E_CARD} <b>حد الحسابات:</b> <code>{user_sub['max_accounts']}</code>",
        f"{E_BOLT} <b>شحن نصي:</b> <code>{user_sub.get('text_recharges_count', 0)}/{user_sub.get('max_text_recharges', 0)}</code>",
        f"{E_STAR} <b>شحن صوري:</b> <code>{user_sub.get('image_recharges_count', 0)}/{user_sub.get('max_image_recharges', 0)}</code>",
    ]
    if user_data and user_data.get('plan_expiry'):
        lines.append(f"{E_INFO} <b>تاريخ الانتهاء:</b> <code>{esc(user_data['plan_expiry'])}</code>")

    return build_card(f"{E_STATS} حالة اشتراكك الحالية", lines)

async def _get_available_plans_text() -> str:
    """Helper to generate the list of available plans in HTML."""
    db = DBManager()
    plans = await db.get_plans()

    lines = []
    for plan in plans:
        lines.append(f"{E_CROWN} <b>{esc(plan['name'])}</b> — <code>{plan['price']} IQD</code>")
        lines.append(
            f"   {E_CARD} حسابات: <code>{plan['max_accounts']}</code> | "
            f"نصي: <code>{plan.get('max_text_recharges')}</code> | "
            f"صوري: <code>{plan.get('max_image_recharges')}</code>"
        )
        if plan['description']:
            lines.append(f"   <i>{esc(plan['description'])}</i>")
        lines.append("")

    subscribe_message = await db.get_setting("subscribe_message", "للاشتراك يرجى التواصل مع الدعم.")
    return build_card(
        f"{E_DIAMOND} الخطط المتاحة",
        lines,
        footer=esc(subscribe_message),
        expandable_footer=False,
    )

async def about_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows about info."""
    query = update.callback_query
    await _safe_answer(query)

    db = DBManager()
    raw_text = await db.get_setting(
        "about_text",
        "بوت احترافي لإدارة حسابات آسياسيل، مراقبة الرصيد، وتعبئة الكروت نصياً وبالصور تلقائياً.",
    )
    card_text = build_card(
        f"{E_INFO} حول البوت",
        [esc(raw_text)],
        footer="جاهز لخدمتك على مدار الساعة",
    )

    keyboard = [[btn("رجوع", "main_menu", BTN_ICON_BACK, "primary")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(text=card_text, parse_mode="HTML", reply_markup=reply_markup)

async def my_accounts_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lists user accounts."""
    query = update.callback_query
    await _safe_answer(query)
    user_id = query.from_user.id

    db = DBManager()
    accounts = await db.get_user_accounts(user_id)

    keyboard = []
    lines = []
    if accounts:
        lines.append(f"{E_USER} لديك <code>{len(accounts)}</code> حسابات مسجلة. اختر حساباً للإدارة:")
        for acc in accounts:
            phone = acc["phone_number"]
            is_primary = acc.get("is_primary_receiver", 0)
            label = f"{phone} (رئيسي)" if is_primary else phone
            icon = BTN_ICON_CHECK if is_primary else BTN_ICON_PHONE
            style = "success" if is_primary else "primary"
            keyboard.append([btn(label, f"acc_{phone}", icon, style)])
    else:
        lines.append(f"{E_WARN} لا توجد حسابات مسجلة حالياً.")
        keyboard.append([btn("إضافة حساب جديد", "add_account_start", BTN_ICON_ADD, "success")])

    keyboard.append([btn("رجوع", "main_menu", BTN_ICON_BACK, "primary")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    card_text = build_card(f"{E_CARD} حساباتي", lines)
    await query.edit_message_text(card_text, parse_mode="HTML", reply_markup=reply_markup)

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

    account = await db.get_account(phone, user_id)
    current_balance = account.get("current_balance", 0.0)

    lines = [
        f"{E_CARD} <b>الرقم:</b> <code>{esc(phone)}</code>",
        f"{E_GROWTH} <b>الرصيد الحالي:</b> <code>{current_balance:,.2f} IQD</code>",
    ]
    if 'name' in account_info:
        lines.append(f"{E_USER} <b>الاسم:</b> {esc(account_info['name'])}")
    if 'expiry' in account_info:
        lines.append(f"{E_INFO} <b>صالح لغاية:</b> <code>{esc(account_info['expiry'])}</code>")

    is_primary = account.get("is_primary_receiver", 0)
    if is_primary:
        lines.append(f"{E_SUCCESS} <b>الحالة:</b> المستقبل الرئيسي للرصيد")

    card_text = build_card(f"{E_STATS} تفاصيل حساب آسياسيل", lines)

    keyboard = [
        [btn("تحديث البيانات", f"refresh_{phone}", BTN_ICON_REFRESH, "primary")],
    ]
    if not is_primary:
        keyboard.append([btn("تعيين كمستقبل رئيسي", f"setprimary_{phone}", BTN_ICON_CHECK, "success")])

    keyboard.append([
        btn("حذف الحساب", f"delconf_{phone}", BTN_ICON_TRASH, "danger"),
        btn("رجوع", "my_accounts", BTN_ICON_BACK, "primary"),
    ])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text=card_text, parse_mode="HTML", reply_markup=reply_markup)

async def refresh_balance_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Refreshes balance for an account by reusing detailed view logic."""
    # Since account_details_handler now does a fresh fetch, we just redirect to it.
    await account_details_handler(update, context)

async def delete_confirm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Asks for deletion confirmation."""
    query = update.callback_query
    await _safe_answer(query)
    phone = query.data.split("_")[1]

    text = build_card(
        f"{E_WARN} تأكيد حذف الحساب",
        [f"هل أنت متأكد من حذف الحساب <code>{esc(phone)}</code>؟"],
        footer="لا يمكن التراجع عن هذه العملية بعد التأكيد",
    )
    keyboard = [
        [
            btn("نعم، احذف", f"delaction_{phone}", BTN_ICON_TRASH, "danger"),
            btn("تراجع", f"acc_{phone}", BTN_ICON_BACK, "primary"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=reply_markup)

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
    phone = query.data.split("_")[1]
    user_id = query.from_user.id

    db = DBManager()
    await db.set_primary_receiver(user_id, phone)

    await _safe_answer(query, f"✅ تم تعيين {phone} كمستقبل رئيسي", show_alert=False)
    await account_details_handler(update, context)

# --- Recharge Conversation Handlers ---

async def start_recharge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Starts the recharge conversation."""
    user_id = update.effective_user.id
    db = DBManager()
    accounts = await db.get_user_accounts(user_id)

    if not accounts:
        text = build_card(
            f"{E_WARN} لا توجد حسابات مضافة",
            ["الرجاء إضافة رقم آسياسيل أولاً قبل البدء بالشحن."],
        )
        keyboard = [
            [btn("إضافة حساب جديد", "add_account_start", BTN_ICON_ADD, "success")],
            [btn("رجوع", "main_menu", BTN_ICON_BACK, "primary")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if update.callback_query:
            await _safe_answer(update.callback_query)
            await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=reply_markup)
        else:
            await update.message.reply_text(text, parse_mode="HTML", reply_markup=reply_markup)
        return ConversationHandler.END

    text = build_card(
        f"{E_BOLT} شحن رصيد",
        [
            f"{E_CARD} قم بإرسال رقم الكرت (14 أو 15 رقم) كتابةً.",
            f"{E_ROCKET} أو أرسل <b>صورة الكرت</b> وسأستخرج الرقم وأشحنه تلقائياً.",
        ],
        footer="يمكنك الإلغاء في أي وقت من الزر أدناه",
    )

    keyboard = [[btn("إلغاء", "cancel_conv", BTN_ICON_CANCEL, "danger")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await _safe_answer(update.callback_query)
        await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=reply_markup)
    return RECHARGE_INPUT

async def recharge_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the card number input."""
    user_id = update.effective_user.id
    db = DBManager()
    sub = await db.get_user_subscription(user_id)

    text = ""
    feature_type = "text"
    code = None
    status_msg = None

    if update.message.text:
        if sub['text_recharges_count'] >= sub['max_text_recharges']:
             text = f"{E_ERROR} <b>لقد وصلت للحد الأقصى المسموح به لشحن الكروت عبر النص في خطتك.</b>\n\n"
             text += await _get_user_status_text(user_id)
             keyboard = [[btn("رجوع", "main_menu", BTN_ICON_BACK, "primary")]]
             await update.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
             return ConversationHandler.END
        text = update.message.text
    elif update.message.photo:
        if sub['image_recharges_count'] >= sub['max_image_recharges']:
             text = f"{E_ERROR} <b>لقد وصلت للحد الأقصى المسموح به لشحن الكروت عبر الصور في خطتك.</b>\n\n"
             text += await _get_user_status_text(user_id)
             keyboard = [[btn("رجوع", "main_menu", BTN_ICON_BACK, "primary")]]
             await update.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
             return ConversationHandler.END
        feature_type = "image"
        status_msg = await update.message.reply_text(
            f"{E_PENDING} <b>جاري تحليل الصورة واستخراج رقم الكرت...</b>",
            parse_mode="HTML",
        )
        try:
            largest_photo = update.message.photo[-1]
            image_bytes = await download_telegram_photo_bytes(context.bot, largest_photo.file_id)
            code, text = await extract_card_from_image_bytes(image_bytes)
        except Exception as e:
            logger.error(f"Failed to process photo: {e}")
            await status_msg.edit_text(f"{E_ERROR} <b>حدث خطأ أثناء معالجة الصورة.</b>", parse_mode="HTML")
            return RECHARGE_INPUT

    # Fallback to caption if available and OCR didn't find anything (or it wasn't a photo)
    if not text and update.message.caption:
        text = update.message.caption

    # Extract code using robust logic
    if not code:
        code = extract_card_number(text)

    # Secondary fallback to caption if OCR returned text but no valid card code was extracted
    if not code and update.message.caption:
        code = extract_card_number(update.message.caption)

    if not code:
        err_text = f"{E_ERROR} <b>لم يتم العثور على كود صالح.</b> يرجى إرسال كود يتكون من 14 أو 15 رقم."
        if status_msg:
            await status_msg.edit_text(err_text, parse_mode="HTML")
        else:
            await update.message.reply_text(err_text, parse_mode="HTML")
        return RECHARGE_INPUT

    processing_text = f"{E_PENDING} <b>جاري شحن الكود:</b> <code>{esc(code)}</code> ..."
    if status_msg:
        msg = await status_msg.edit_text(processing_text, parse_mode="HTML")
    else:
        msg = await update.message.reply_text(processing_text, parse_mode="HTML")

    post_keyboard = InlineKeyboardMarkup([
        [
            btn("شحن كرت آخر", "start_recharge", BTN_ICON_RECHARGE, "success"),
            btn("القائمة الرئيسية", "main_menu", BTN_ICON_HOME, "primary"),
        ]
    ])

    try:
        recharge_manager = RechargeManager()
        result_message = await recharge_manager.process_smart_recharge(user_id, code)
        await db.increment_usage(user_id, feature_type)

        await msg.edit_text(result_message, parse_mode="HTML", reply_markup=post_keyboard)
    except Exception as e:
        logger.exception(f"Recharge failed: {e}")
        await msg.edit_text(f"{E_ERROR} <b>حدث خطأ غير متوقع:</b> {esc(e)}", parse_mode="HTML", reply_markup=post_keyboard)

    return ConversationHandler.END

async def show_plans_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows available subscription plans and user status."""
    query = update.callback_query
    await _safe_answer(query)
    user_id = query.from_user.id

    status_text = await _get_user_status_text(user_id)
    plans_text = await _get_available_plans_text()

    full_text = f"{status_text}\n\n{plans_text}"
    keyboard = [[btn("رجوع", "main_menu", BTN_ICON_BACK, "primary")]]
    await query.edit_message_text(text=full_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

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
        text += await _get_user_status_text(user_id)
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
        CommandHandler("admin", admin_dashboard),
    ] + admin_handlers + callback_handlers + [
        MessageHandler(filters.PHOTO, recharge_input_handler),
    ]
