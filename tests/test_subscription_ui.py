import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.bot.handlers import _get_plans_text, show_plans_handler, add_account_start
from telegram import Update, Message, CallbackQuery, User

@pytest.mark.asyncio
async def test_get_plans_text():
    # Mock DBManager
    with patch("src.bot.handlers.DBManager") as MockDB:
        db_instance = MockDB.return_value
        db_instance.get_plans = AsyncMock(return_value=[{"name": "Free", "price": 0, "max_accounts": 1, "description": "Free plan", "max_text_recharges": 10, "max_image_recharges": 5}])
        db_instance.get_user_subscription = AsyncMock(return_value={"name": "Free", "max_accounts": 1, "text_recharges_count": 0, "max_text_recharges": 10, "image_recharges_count": 0, "max_image_recharges": 5})
        db_instance.get_setting = AsyncMock(return_value="Support: @Dev")

        text = await _get_plans_text(123)

        assert "💎 **الخطط المتاحة**" in text
        assert "خطة اشتراكك الحالية: **Free**" in text
        assert "Support: @Dev" in text
        assert "📝 شحن نصي: `10`" in text

@pytest.mark.asyncio
async def test_add_account_start_limit_reached():
    update = MagicMock(spec=Update)
    update.effective_user.id = 123
    update.callback_query = MagicMock(spec=CallbackQuery)
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    context = MagicMock()

    with patch("src.bot.handlers.DBManager") as MockDB, \
         patch("src.bot.handlers._get_plans_text", new_callable=AsyncMock) as mock_get_plans:

        db_instance = MockDB.return_value
        # Mock limit reached
        db_instance.get_user_subscription = AsyncMock(return_value={"max_accounts": 1})
        db_instance.get_user_accounts = AsyncMock(return_value=[{"phone": "0770"}]) # 1 account exists
        mock_get_plans.return_value = "PLANS_LIST"

        from src.bot.handlers import add_account_start, ConversationHandler
        res = await add_account_start(update, context)

        assert res == ConversationHandler.END
        # Should have edited message with plans instead of alert
        args, kwargs = update.callback_query.edit_message_text.call_args
        assert "❌ لقد تجاوزت الحد الأقصى للحسابات المسموح به في خطتك." in args[0]
        assert "PLANS_LIST" in args[0]
