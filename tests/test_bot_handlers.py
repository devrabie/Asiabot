import asyncio
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from telegram import Update, Message, Chat, User
from telegram.ext import ContextTypes
from src.bot.handlers import phone_handler, otp_handler, PHONE, OTP, ConversationHandler
from src.api.models import LoginResponse, TokenResponse

@pytest.mark.asyncio
async def test_phone_handler_valid():
    # Mock Update and Context
    update = MagicMock(spec=Update)
    update.message = MagicMock(spec=Message)
    update.message.text = "07712345678"
    update.message.reply_text = AsyncMock()

    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.user_data = {}

    # Mock AsiacellClient
    with patch("src.bot.handlers.AsiacellClient") as MockClient:
        instance = MockClient.return_value
        # Mock __aenter__ to return the instance itself
        instance.__aenter__.return_value = instance
        instance.__aexit__.return_value = None

        instance.get_login_cookie = AsyncMock(return_value="session_cookie")
        instance.generate_device_id.return_value = "device-id-123"
        instance.send_login_code = AsyncMock(return_value=LoginResponse(nextUrl="https://api.com?PID=test-pid"))

        state = await phone_handler(update, context)

        assert state == OTP
        assert context.user_data["phone_number"] == "07712345678"
        assert context.user_data["cookie"] == "session_cookie"
        assert context.user_data["device_id"] == "device-id-123"
        assert context.user_data["pid"] == "test-pid"
        instance.send_login_code.assert_called_once()

@pytest.mark.asyncio
async def test_phone_handler_invalid_number():
    update = MagicMock(spec=Update)
    update.message = MagicMock(spec=Message)
    update.message.text = "07812345678" # Wrong prefix
    update.message.reply_text = AsyncMock()

    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)

    state = await phone_handler(update, context)

    assert state == PHONE
    update.message.reply_text.assert_called_with("Invalid format. Please send a valid number starting with 077.")

@pytest.mark.asyncio
async def test_otp_handler_success():
    update = MagicMock(spec=Update)
    update.message = MagicMock(spec=Message)
    update.message.text = "123456"
    update.message.reply_text = AsyncMock()

    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.user_data = {
        "phone_number": "07712345678",
        "pid": "test-pid",
        "device_id": "device-id-123",
        "cookie": "session_cookie"
    }

    # Mock Client and Repository
    with patch("src.bot.handlers.AsiacellClient") as MockClient, \
         patch("src.bot.handlers.AccountRepository") as MockRepo:

        client_instance = MockClient.return_value
        client_instance.__aenter__.return_value = client_instance
        client_instance.__aexit__.return_value = None

        client_instance.validate_sms_code = AsyncMock(return_value=TokenResponse(
            access_token="acc_tok",
            refresh_token="ref_tok"
        ))

        repo_instance = MockRepo.return_value
        repo_instance.init_db = AsyncMock()
        repo_instance.save_account = AsyncMock()

        state = await otp_handler(update, context)

        assert state == ConversationHandler.END
        client_instance.validate_sms_code.assert_called_with("session_cookie", "device-id-123", "test-pid", "123456")
        repo_instance.save_account.assert_called_with("07712345678", "acc_tok", "ref_tok", "device-id-123", "session_cookie")
        update.message.reply_text.assert_called_with("Login Successful! Account Saved.")
