from typing import Optional, List
from loguru import logger
from src.database.db_manager import DBManager
from src.api.client import AsiacellClient

class RechargeManager:
    def __init__(self):
        self.db = DBManager()

    async def process_smart_recharge(self, user_id: int, voucher_code: str) -> str:
        """
        Process smart recharge by rotating through sender accounts to recharge the primary receiver.
        """
        accounts = await self.db.get_user_accounts(user_id)

        # Identify roles
        target_account = None
        sender_accounts = []

        for acc in accounts:
            if acc.get("is_primary_receiver"):
                target_account = acc
            else:
                sender_accounts.append(acc)

        if not target_account:
            return "❌ Error: No primary receiver account set. Please set a primary receiver first."

        if not sender_accounts:
            return "❌ Error: No sender accounts available to perform the recharge."

        target_number = target_account["phone_number"]
        logger.info(f"Starting smart recharge for {target_number} using {len(sender_accounts)} senders.")

        tried_senders = []

        for sender in sender_accounts:
            sender_number = sender["phone_number"]
            tried_senders.append(sender_number)

            logger.info(f"Trying to recharge using sender: {sender_number}")

            try:
                async with AsiacellClient() as client:
                    # Refresh token if needed? For now assuming token is valid or scheduler handles it.
                    # But safely we could try/except around it.

                    # Note: submit_recharge_other requires access_token.
                    response = await client.submit_recharge_other(
                        voucher_code,
                        target_number,
                        sender["access_token"]
                    )

                    # Analyze response
                    # We need to know the structure of success vs error response.
                    # Assuming success has some specific field or just doesn't raise exception.
                    # But typically ODP API returns a structure.
                    # If 'data' is returned, we check it.

                    # Based on typical API behavior:
                    # Success might look like {"status": "success", ...} or similar.
                    # Errors usually raise exception in client._request if status code != 200.
                    # However, business logic errors (like invalid voucher) might return 200 with error message.

                    # Let's assume response contains a success indicator or we rely on exception for failure.
                    # If we got here, HTTP status was 200.

                    # If the response contains an error message inside 200 OK:
                    # We need to parse it. Since we don't have the exact response structure,
                    # I'll check for common error keywords if it's a dict.

                    if isinstance(response, dict):
                        # Check for success
                        # ODP responses often have no standardized "success" field, sometimes it's implied by absence of error.
                        # Or maybe "message" field.

                        message = str(response).lower()

                        # Check for specific failure cases (Blocking/Limits)
                        if "block" in message or "limit" in message or "exceed" in message:
                            logger.warning(f"Account {sender_number} blocked/limited: {message}")
                            continue # Try next sender

                        # Check for Invalid Voucher
                        if "voucher" in message and ("invalid" in message or "used" in message or "not found" in message):
                            return f"❌ Error: Voucher invalid or already used ({message})."

                        # Assume success if no obvious error?
                        # Or better, let's assume if it returns data, it worked, unless we find error.
                        # A safer bet: if we reached here, it's likely a success or a non-critical error.
                        # If it was a critical error like 400/401/500, _request would raise exception.

                        return f"✅ Success! Recharged {target_number} using {sender_number}."

            except Exception as e:
                # Handle HTTP errors or network errors
                err_msg = str(e).lower()

                # Check for blocking/limiting errors in exception
                if "block" in err_msg or "limit" in err_msg or "too many" in err_msg or "429" in err_msg:
                     logger.warning(f"Account {sender_number} failed (Blocked/Limited): {e}")
                     continue

                # Check for voucher errors
                if "voucher" in err_msg and ("invalid" in err_msg or "used" in err_msg):
                     return f"❌ Error: Voucher invalid or used."

                # Other errors - log and continue to next sender?
                logger.error(f"Account {sender_number} failed with error: {e}")
                continue

        return f"❌ Failed to recharge using all available senders: {', '.join(tried_senders)}"
