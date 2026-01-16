from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from src.config import settings
from src.database.db_manager import DBManager

# States for Add Plan Conversation
PLAN_NAME, PLAN_PRICE, PLAN_ACCOUNTS, PLAN_DESC, PLAN_DURATION = range(5)
# States for Grant Plan Conversation
GRANT_USER_ID, GRANT_PLAN_SELECT, GRANT_DURATION = range(3)

async def check_admin(update: Update) -> bool:
    user_id = update.effective_user.id
    if user_id != settings.ADMIN_ID:
        if update.callback_query:
            await update.callback_query.answer("⛔ Unauthorized.", show_alert=True)
        else:
            await update.message.reply_text("⛔ Unauthorized access.")
        return False
    return True

async def admin_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main Admin Menu."""
    if not await check_admin(update): return

    keyboard = [
        [InlineKeyboardButton("👥 Users", callback_data="admin_users")],
        [InlineKeyboardButton("💎 Plans", callback_data="admin_plans")],
        [InlineKeyboardButton("🎁 Grant Subscription", callback_data="admin_grant_start")],
        [InlineKeyboardButton("🔙 Close", callback_data="admin_close")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "🔐 **Admin Dashboard**\nSelect an option:"

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)

async def admin_users_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all users."""
    if not await check_admin(update): return
    query = update.callback_query
    await query.answer("Fetching users...")

    db = DBManager()
    users = await db.get_all_users_with_accounts()

    if not users:
        await query.edit_message_text("No users found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_menu")]]))
        return

    # Basic pagination logic could be added here, for now list as buttons
    keyboard = []
    for user in users:
        label = f"{user.get('first_name', 'NoName')} (@{user.get('username', 'None')})"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"admin_user_{user['telegram_id']}")])

    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="admin_menu")])

    await query.edit_message_text("👥 **Users List**\nClick for details:", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_user_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user details."""
    if not await check_admin(update): return
    query = update.callback_query
    user_id = int(query.data.split("_")[2])

    db = DBManager()
    # Re-fetch specific user data properly would be better, but we can iterate for now
    # Or implement get_user_with_accounts in DB. For now, filter list.
    users = await db.get_all_users_with_accounts()
    user_data = next((u for u in users if u['telegram_id'] == user_id), None)

    if not user_data:
        await query.answer("User not found.")
        return

    text = f"👤 **User Details**\n"
    text += f"ID: `{user_data['telegram_id']}`\n"
    text += f"Name: {user_data.get('first_name')}\n"
    text += f"Username: @{user_data.get('username')}\n"

    sub = await db.get_user_subscription(user_id)
    text += f"Plan: {sub.get('name', 'Free')} (Max: {sub.get('max_accounts')})\n"
    if user_data.get('plan_expiry'):
        text += f"Expiry: {user_data['plan_expiry']}\n"

    text += "\n📱 **Accounts:**\n"
    accounts = user_data.get('accounts', [])
    if accounts:
        for acc in accounts:
            text += f"- `{acc['phone_number']}` | 💰 {acc['current_balance']} IQD\n"
    else:
        text += "No accounts linked."

    keyboard = [[InlineKeyboardButton("🔙 Back to Users", callback_data="admin_users")]]
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_plans_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List plans."""
    if not await check_admin(update): return
    query = update.callback_query
    await query.answer()

    db = DBManager()
    plans = await db.get_plans()

    text = "💎 **Plans Management**\n\n"
    keyboard = []

    for plan in plans:
        text += f"🔹 **{plan['name']}** (ID: {plan['id']})\n"
        text += f"   Price: {plan['price']}, Max Accs: {plan['max_accounts']}\n"
        # Delete button
        keyboard.append([InlineKeyboardButton(f"❌ Delete {plan['name']}", callback_data=f"admin_delplan_{plan['id']}")])

    keyboard.append([InlineKeyboardButton("➕ Add New Plan", callback_data="admin_addplan_start")])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="admin_menu")])

    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_delete_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update): return
    query = update.callback_query
    plan_id = int(query.data.split("_")[2])
    db = DBManager()
    await db.delete_plan(plan_id)
    await query.answer("Plan deleted.")
    await admin_plans_list(update, context)

async def admin_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.message.delete()

# --- Add Plan Conversation ---
async def add_plan_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("Enter Plan Name:")
    return PLAN_NAME

async def add_plan_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['p_name'] = update.message.text
    await update.message.reply_text("Enter Plan Price (IQD):")
    return PLAN_PRICE

async def add_plan_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data['p_price'] = float(update.message.text)
    except ValueError:
        await update.message.reply_text("Invalid number. Enter price again:")
        return PLAN_PRICE
    await update.message.reply_text("Enter Max Accounts allowed:")
    return PLAN_ACCOUNTS

async def add_plan_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data['p_accs'] = int(update.message.text)
    except ValueError:
        await update.message.reply_text("Invalid number. Enter max accounts:")
        return PLAN_ACCOUNTS
    await update.message.reply_text("Enter Plan Description:")
    return PLAN_DESC

async def add_plan_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['p_desc'] = update.message.text
    await update.message.reply_text("Enter Duration (days):")
    return PLAN_DURATION

async def add_plan_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        duration = int(update.message.text)
        db = DBManager()
        await db.add_plan(
            context.user_data['p_name'],
            context.user_data['p_price'],
            context.user_data['p_accs'],
            context.user_data['p_desc'],
            duration
        )
        await update.message.reply_text("✅ Plan added successfully!")
    except ValueError:
        await update.message.reply_text("Invalid number.")

    return ConversationHandler.END

async def cancel_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END

# --- Grant Plan Conversation ---
async def grant_plan_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("Enter User Telegram ID:")
    return GRANT_USER_ID

async def grant_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        uid = int(update.message.text)
        context.user_data['g_uid'] = uid

        db = DBManager()
        plans = await db.get_plans()
        if not plans:
            await update.message.reply_text("No plans available. Add a plan first.")
            return ConversationHandler.END

        keyboard = []
        for p in plans:
            keyboard.append([InlineKeyboardButton(f"{p['name']} ({p['duration_days']} days)", callback_data=str(p['id']))])

        await update.message.reply_text("Select a Plan:", reply_markup=InlineKeyboardMarkup(keyboard))
        return GRANT_PLAN_SELECT
    except ValueError:
        await update.message.reply_text("Invalid ID.")
        return ConversationHandler.END

async def grant_plan_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pid = int(query.data)
    context.user_data['g_pid'] = pid

    await query.edit_message_text("Enter custom duration in days (or 0 to use plan default):")
    return GRANT_DURATION

async def grant_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        days = int(update.message.text)
        db = DBManager()

        # Get default if 0
        if days == 0:
            plans = await db.get_plans()
            plan = next((p for p in plans if p['id'] == context.user_data['g_pid']), None)
            days = plan['duration_days'] if plan else 30

        await db.grant_subscription(context.user_data['g_uid'], context.user_data['g_pid'], days)
        await update.message.reply_text(f"✅ Plan granted to user {context.user_data['g_uid']} for {days} days.")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

    return ConversationHandler.END

# Export Handlers
def get_admin_handlers():
    add_plan_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_plan_start, pattern="^admin_addplan_start$")],
        states={
            PLAN_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_plan_name)],
            PLAN_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_plan_price)],
            PLAN_ACCOUNTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_plan_accounts)],
            PLAN_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_plan_desc)],
            PLAN_DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_plan_duration)],
        },
        fallbacks=[CommandHandler("cancel", cancel_admin)]
    )

    grant_plan_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(grant_plan_start, pattern="^admin_grant_start$")],
        states={
            GRANT_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, grant_user_id)],
            GRANT_PLAN_SELECT: [CallbackQueryHandler(grant_plan_select)],
            GRANT_DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, grant_duration)],
        },
        fallbacks=[CommandHandler("cancel", cancel_admin)]
    )

    return [
        add_plan_conv,
        grant_plan_conv,
        CallbackQueryHandler(admin_dashboard, pattern="^admin_menu$"),
        CallbackQueryHandler(admin_users_list, pattern="^admin_users$"),
        CallbackQueryHandler(admin_user_details, pattern="^admin_user_"),
        CallbackQueryHandler(admin_plans_list, pattern="^admin_plans$"),
        CallbackQueryHandler(admin_delete_plan, pattern="^admin_delplan_"),
        CallbackQueryHandler(admin_close, pattern="^admin_close$"),
    ]
