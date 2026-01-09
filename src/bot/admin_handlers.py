from telegram import Update
from telegram.ext import ContextTypes
from src.config import settings
from src.database.db_manager import DBManager

async def admin_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin dashboard to list users and accounts."""
    user_id = update.effective_user.id

    if user_id != settings.ADMIN_ID:
        # Silently ignore or say unauth? Usually better to ignore or say "Unknown command"
        # But for clarity to the user, we might not reply at all if it's meant to be hidden.
        # However, if they typed /admin, they expect something.
        # Let's just ignore to hide existence, or reply "Unauthorized".
        # Given the request is specific, let's reply.
        await update.message.reply_text("⛔ Unauthorized access.")
        return

    db = DBManager()
    users_data = await db.get_all_users_with_accounts()

    if not users_data:
        await update.message.reply_text("📂 No users found in the database.")
        return

    message = "🔐 **Admin Dashboard - Users & Accounts**\n\n"

    for user in users_data:
        t_id = user.get('telegram_id', 'Unknown')
        accounts = user.get('accounts', [])

        message += f"👤 **User ID:** `{t_id}`\n"

        if accounts:
            for acc in accounts:
                phone = acc.get('phone_number', 'N/A')
                balance = acc.get('current_balance', 0)
                is_primary = "⭐" if acc.get('is_primary_receiver') else ""
                message += f"   - 📱 `{phone}` | 💰 {balance} IQD {is_primary}\n"
        else:
            message += "   - No accounts linked.\n"

        message += "\n" + ("-" * 20) + "\n"

    # Split message if it's too long (Telegram limit is 4096 chars)
    if len(message) > 4000:
        # Simple split, could be more robust
        parts = [message[i:i+4000] for i in range(0, len(message), 4000)]
        for part in parts:
            await update.message.reply_text(part, parse_mode="Markdown")
    else:
        await update.message.reply_text(message, parse_mode="Markdown")
