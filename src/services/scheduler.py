from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.ext import Application
from loguru import logger
from src.database.db_manager import DBManager
from src.api.client import AsiacellClient
from src.api.models import TokenResponse
import asyncio

class SchedulerService:
    def __init__(self, application: Application):
        self.scheduler = AsyncIOScheduler()
        self.application = application
        self.db = DBManager()

    def start(self):
        """Starts the scheduler with defined jobs."""
        self.scheduler.add_job(self.refresh_all_tokens, "interval", hours=12)
        # self.scheduler.add_job(self.check_balances, "interval", minutes=30)
        self.scheduler.start()
        logger.info("Scheduler started.")

    async def refresh_all_tokens(self):
        """Refresh tokens for all accounts every 12 hours."""
        logger.info("Starting token refresh job...")
        accounts = await self.db.get_all_accounts()

        for account in accounts:
            phone_number = account["phone_number"]
            refresh_token = account["refresh_token"]
            user_id = account["user_id"]

            try:
                async with AsiacellClient() as client:
                    token_response = await client.refresh_token(refresh_token)

                    if token_response.access_token:
                        await self.db.update_tokens(
                            phone_number,
                            token_response.access_token,
                            token_response.refresh_token
                        )
                        logger.info(f"Refreshed tokens for {phone_number}")
                    else:
                        logger.warning(f"Failed to refresh token for {phone_number}: {token_response.message}")
                        await self._notify_user(user_id, f"⚠️ Session expired for {phone_number}. Please login again.")

            except Exception as e:
                logger.error(f"Error refreshing token for {phone_number}: {e}")
                await self._notify_user(user_id, f"⚠️ Error refreshing session for {phone_number}. Please login again.")

    async def check_balances(self):
        """Check balances for all accounts every 30 minutes."""
        logger.info("Starting balance check job...")
        accounts = await self.db.get_all_accounts()

        for account in accounts:
            phone_number = account["phone_number"]
            access_token = account["access_token"]
            device_id = account["device_id"]
            cookie = account["cookie"]
            current_balance = account["current_balance"] or 0.0
            user_id = account["user_id"]

            try:
                async with AsiacellClient() as client:
                    balance_data = await client.get_balance(access_token, device_id, cookie)

                    if not isinstance(balance_data, dict):
                        logger.warning(f"Invalid balance data for {phone_number}: {balance_data}")
                        continue

                    # Extract balance safely
                    raw_balance = balance_data.get("mainBalance", balance_data.get("balance"))

                    if raw_balance is None:
                         logger.warning(f"Could not find balance field in response for {phone_number}: {balance_data}")
                         continue

                    new_balance = float(raw_balance)

                    if new_balance != current_balance:
                        diff = new_balance - current_balance

                        if diff > 0:
                            await self._notify_user(user_id, f"💰 Balance Added for {phone_number}: +{diff}")
                        elif diff < 0:
                             await self._notify_user(user_id, f"💸 Balance Deducted for {phone_number}: {diff}")

                        await self.db.update_balance(phone_number, new_balance)

            except Exception as e:
                logger.error(f"Error checking balance for {phone_number}: {e}")

    async def _notify_user(self, user_id: int, message: str):
        try:
            await self.application.bot.send_message(chat_id=user_id, text=message)
        except Exception as e:
            logger.error(f"Failed to send message to {user_id}: {e}")
