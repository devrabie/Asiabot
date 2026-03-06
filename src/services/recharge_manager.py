import asyncio
from typing import Optional, List
from loguru import logger
from src.database.db_manager import DBManager
from src.api.client import AsiacellClient

class RechargeManager:
    def __init__(self):
        self.db = DBManager()

    async def _get_balance_safe(self, client: AsiacellClient, account: dict) -> Optional[float]:
        try:
            # Try to fetch balance
            balance_data = await client.get_balance(
                account["access_token"],
                account["device_id"],
                account["cookie"]
            )
            # Parse balance from balance_data structure
            # Assuming structure matches: { "watch": { "information": { "mainBalance": "1,234 IQD" } } }
            # Or whatever the API returns. Using the logic from handlers.py:
            if isinstance(balance_data, dict):
                info = balance_data.get("watch", {}).get("information", {})
                raw = info.get("mainBalance")
                if raw:
                    return float(str(raw).replace(" IQD", "").replace(",", ""))
        except Exception as e:
            # Suppress errors, return None so caller can handle
            pass
        return None

    async def _refresh_and_update(self, client: AsiacellClient, account: dict) -> Optional[str]:
        """Refreshes token and updates DB. Returns new access_token or None."""
        try:
            token_resp = await client.refresh_token(account["refresh_token"], account["device_id"])
            if token_resp.access_token:
                await self.db.update_tokens(
                    account["phone_number"],
                    token_resp.access_token,
                    token_resp.refresh_token or account["refresh_token"]
                )
                return token_resp.access_token
        except Exception as e:
            logger.error(f"Failed to refresh token for {account['phone_number']}: {e}")
        return None

    async def process_smart_recharge(self, user_id: int, voucher_code: str) -> str:
        """
        Process smart recharge by rotating through sender accounts to recharge the primary receiver.
        Includes token refresh logic and balance verification.
        """
        accounts = await self.db.get_user_accounts(user_id)

        target_account = next((acc for acc in accounts if acc.get("is_primary_receiver")), None)
        sender_accounts = [acc for acc in accounts if not acc.get("is_primary_receiver")]

        # Fallback: if no sender accounts but target exists, assume self-recharge
        if not sender_accounts and target_account:
            sender_accounts = [target_account]

        if not target_account:
            return "❌ خطأ: لم يتم تحديد حساب مستقبل رئيسي (Primary Receiver)."

        if not sender_accounts:
            return "❌ خطأ: لا توجد حسابات متاحة لإجراء الشحن."

        target_number = target_account["phone_number"]
        logger.info(f"Starting smart recharge for {target_number} using {len(sender_accounts)} senders.")

        # 1. Get Initial Balance of Target
        initial_balance = 0.0
        async with AsiacellClient() as client:
            # Check/Refresh target token first to ensure we can read balance
            bal = await self._get_balance_safe(client, target_account)
            if bal is None:
                logger.info(f"Initial balance fetch failed for {target_number}, trying refresh...")
                new_token = await self._refresh_and_update(client, target_account)
                if new_token:
                    target_account["access_token"] = new_token
                    bal = await self._get_balance_safe(client, target_account)

            if bal is not None:
                initial_balance = bal
                logger.info(f"Initial balance for {target_number}: {initial_balance}")
            else:
                return f"❌ فشل جلب رصيد الحساب المستلم {target_number}. يرجى التحقق من صلاحية الحساب."

        tried_senders = []

        for sender in sender_accounts:
            sender_number = sender["phone_number"]
            tried_senders.append(sender_number)

            async with AsiacellClient() as client:
                try:
                    logger.info(f"Attempting recharge via sender: {sender_number}")

                    # Check/Refresh sender token if needed (proactive or reactive? reactive via 403 handling below)

                    if sender_number == target_number:
                        response = await client.recharge(
                            voucher_code, sender["access_token"], sender["device_id"]
                        )
                    else:
                        response = await client.submit_recharge_other(
                            voucher_code, target_number, sender["access_token"], sender["device_id"]
                        )

                    # Inspect response
                    # Try to capture API message
                    api_message = ""
                    if isinstance(response, dict):
                        api_message = response.get("message", "")

                    msg_str = str(response).lower()

                    # Check for specific business errors first, even if status is 200
                    error_keywords = ["invalid", "used", "not found", "غير صحيح", "مستخدم", "عذراً"]
                    if any(k in msg_str for k in error_keywords):
                        error_text = api_message or "الكرت غير صالح أو مستخدم مسبقاً."
                        return f"❌ خطأ: {error_text}"

                    # Check for success
                    # If success is True or message indicates success
                    if isinstance(response, dict) and (response.get("success") is True or "success" in msg_str):
                        pass # Proceed to check balance
                    else:
                        if "block" in msg_str or "limit" in msg_str:
                            logger.warning(f"Sender {sender_number} blocked/limited: {msg_str}")
                            continue

                        # Fallback for other errors (even with 200 OK)
                        error_text = api_message or "فشل غير معروف."
                        logger.warning(f"Recharge response indicated failure: {response}")
                        continue

                    # Wait for balance update
                    logger.info("Recharge request sent. Waiting for balance update...")
                    await asyncio.sleep(3)

                    # Check new balance using TARGET account token
                    new_balance = await self._get_balance_safe(client, target_account)

                    diff = 0.0
                    if new_balance is not None:
                        diff = (new_balance or 0.0) - initial_balance

                    if diff > 0:
                        return (
                            f"✅ *تم شحن الرصيد بنجاح!*\n\n"
                            f"💰 المبلغ المضاف: `{diff:,.0f} IQD`\n"
                            f"📉 الرصيد السابق: `{initial_balance:,.0f} IQD`\n"
                            f"📈 الرصيد الحالي: `{new_balance:,.0f} IQD`\n\n"
                            f"📱 المستلم: `{target_number}`\n"
                            f"💳 المرسل: `{sender_number}`\n"
                            f"🔢 الكرت: `{voucher_code}`"
                        )
                    else:
                        # Success response but balance didn't change
                        # Include API message if available to explain why
                        msg_part = f"\n*رسالة الشركة:* {api_message}" if api_message else ""
                        return (
                            f"⚠️ *تنبيه: لم يتم رصد زيادة في الرصيد*\n\n"
                            f"تم إرسال طلب الشحن، ولكن الرصيد لم يتغير.\n"
                            f"الرصيد الحالي: `{initial_balance:,.0f} IQD`"
                            f"{msg_part}\n\n"
                            f"يرجى التحقق من صحة الكرت أو المحاولة لاحقاً."
                        )

                except Exception as e:
                    # Check for 403 Forbidden (Token Expired)
                    is_auth_error = False
                    if hasattr(e, 'status') and e.status in [401, 403]:
                        is_auth_error = True

                    if is_auth_error:
                        logger.warning(f"Sender {sender_number} token expired (403). Refreshing...")
                        new_token = await self._refresh_and_update(client, sender)
                        if new_token:
                            sender["access_token"] = new_token
                            # Retry ONCE
                            try:
                                logger.info(f"Retrying recharge with new token for {sender_number}")
                                if sender_number == target_number:
                                    await client.recharge(
                                        voucher_code, new_token, sender["device_id"]
                                    )
                                else:
                                    await client.submit_recharge_other(
                                        voucher_code, target_number, new_token, sender["device_id"]
                                    )
                                await asyncio.sleep(3)
                                new_balance = await self._get_balance_safe(client, target_account)
                                diff = (new_balance or 0) - initial_balance
                                if diff > 0:
                                     return (
                                        f"✅ *تم شحن الرصيد بنجاح!* (بعد تحديث التوكن)\n\n"
                                        f"💰 المبلغ المضاف: `{diff:,.0f} IQD`\n"
                                        f"📈 الرصيد الحالي: `{new_balance:,.0f} IQD`"
                                    )
                            except Exception as retry_e:
                                logger.error(f"Retry failed for {sender_number}: {retry_e}")
                                # Continue to next sender if retry fails
                        else:
                            logger.error(f"Failed to refresh token for {sender_number}")

                    # Handle other errors
                    err_msg = str(e).lower()
                    if "block" in err_msg or "limit" in err_msg or "too many" in err_msg:
                        logger.warning(f"Sender {sender_number} limited. Moving to next.")
                        continue

                    # If specific voucher error, abort
                    if "voucher" in err_msg and ("invalid" in err_msg or "used" in err_msg):
                        return f"❌ خطأ: الكرت غير صالح أو مستخدم."

                    logger.error(f"Recharge failed with {sender_number}: {e}")
                    continue

        return f"❌ فشلت عملية الشحن. تم تجربة {len(tried_senders)} حسابات."
