import aiosqlite
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Tuple
from loguru import logger

class DBManager:
    def __init__(self, db_path: str = "data/asiabot.db", schema_path: str = "src/database/schema.sql"):
        self.db_path = db_path
        self.schema_path = schema_path
        self._ensure_db_dir()

    def _ensure_db_dir(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    async def init_db(self):
        """Initialize the database with the schema."""
        if not Path(self.schema_path).exists():
            logger.error(f"Schema file not found at {self.schema_path}")
            return

        with open(self.schema_path, "r") as f:
            schema = f.read()

        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(schema)
            await db.commit()
            logger.info("Database initialized successfully.")

    async def create_user_if_not_exists(self, telegram_id: int):
        """Create a user if they don't exist."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO users (telegram_id) VALUES (?)",
                (telegram_id,)
            )
            await db.commit()

    async def add_account(
        self,
        user_id: int,
        phone_number: str,
        device_id: str,
        cookie: str,
        access_token: str,
        refresh_token: str
    ):
        """Add a new account for a user."""
        # Ensure user exists first
        await self.create_user_if_not_exists(user_id)

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO accounts (
                    user_id, phone_number, device_id, cookie,
                    access_token, refresh_token, token_updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(phone_number) DO UPDATE SET
                    user_id=excluded.user_id,
                    device_id=excluded.device_id,
                    cookie=excluded.cookie,
                    access_token=excluded.access_token,
                    refresh_token=excluded.refresh_token,
                    token_updated_at=excluded.token_updated_at
                """,
                (
                    user_id, phone_number, device_id, cookie,
                    access_token, refresh_token, datetime.now()
                )
            )
            await db.commit()
            logger.info(f"Account {phone_number} added/updated for user {user_id}.")

    async def get_user_accounts(self, user_id: int) -> List[dict]:
        """Returns all accounts added by a specific user."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM accounts WHERE user_id = ?", (user_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def update_tokens(self, phone_number: str, new_access: str, new_refresh: str):
        """Update access and refresh tokens for a specific account."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                UPDATE accounts
                SET access_token = ?, refresh_token = ?, token_updated_at = ?
                WHERE phone_number = ?
                """,
                (new_access, new_refresh, datetime.now(), phone_number)
            )
            await db.commit()
            logger.info(f"Tokens updated for {phone_number}.")

    async def update_balance(self, phone_number: str, new_balance: float):
        """Update the balance for a specific account."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                UPDATE accounts
                SET current_balance = ?, last_balance_update = ?
                WHERE phone_number = ?
                """,
                (new_balance, datetime.now(), phone_number)
            )
            await db.commit()
            logger.info(f"Balance updated for {phone_number}: {new_balance}.")
