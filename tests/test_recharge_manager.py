import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.services.recharge_manager import RechargeManager

@pytest.mark.asyncio
async def test_process_smart_recharge_arabic_error():
    manager = RechargeManager()

    # Mock database
    mock_db = AsyncMock()
    mock_db.get_user_accounts.return_value = [
        {"phone_number": "07700000000", "access_token": "at1", "refresh_token": "rt1", "device_id": "d1", "is_primary_receiver": 1}
    ]
    manager.db = mock_db

    # Mock _get_balance_safe directly to avoid complex client mocking
    manager._get_balance_safe = AsyncMock(return_value=10000.0)

    # Mock AsiacellClient
    with patch("src.services.recharge_manager.AsiacellClient") as MockClient:
        client_instance = MockClient.return_value.__aenter__.return_value

        # Recharge response with Arabic error
        client_instance.recharge.return_value = {
            "success": True, # API might return success: True even with error message
            "message": "عذراً! الرقم الذي أدخلته غير صحيح."
        }

        result = await manager.process_smart_recharge(123, "123456789")

        assert "❌ خطأ" in result
        assert "غير صحيح" in result

@pytest.mark.asyncio
async def test_process_smart_recharge_no_balance_change():
    manager = RechargeManager()

    # Mock database
    mock_db = AsyncMock()
    mock_db.get_user_accounts.return_value = [
        {"phone_number": "07700000000", "access_token": "at1", "refresh_token": "rt1", "device_id": "d1", "is_primary_receiver": 1}
    ]
    manager.db = mock_db

    # Mock _get_balance_safe
    manager._get_balance_safe = AsyncMock(side_effect=[10000.0, 10000.0])

    # Mock AsiacellClient
    with patch("src.services.recharge_manager.AsiacellClient") as MockClient:
        client_instance = MockClient.return_value.__aenter__.return_value

        # Recharge response (success but no balance change)
        client_instance.recharge.return_value = {
            "success": True,
            "message": "تم استلام الطلب"
        }

        with patch("asyncio.sleep", return_value=None):
            result = await manager.process_smart_recharge(123, "123456789")

        assert "⚠️ *تنبيه: لم يتم رصد زيادة في الرصيد*" in result
        assert "10,000 IQD" in result
        assert "تم استلام الطلب" in result
