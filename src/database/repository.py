import aiosqlite
from pathlib import Path
from loguru import logger

class AccountRepository:
    def __init__(self, db_path: str = "data/asiabot.db"):
        self.db_path = db_path
        self._ensure_db_dir()

    def _ensure_db_dir(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    async def init_db(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS accounts (
                    phone_number TEXT PRIMARY KEY,
                    access_token TEXT,
                    refresh_token TEXT,
                    device_id TEXT,
                    cookie TEXT
                )
            """)
            await db.commit()
            logger.info("Database initialized.")

    async def save_account(self, phone_number: str, access_token: str, refresh_token: str, device_id: str, cookie: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO accounts (phone_number, access_token, refresh_token, device_id, cookie)
                VALUES (?, ?, ?, ?, ?)
            """, (phone_number, access_token, refresh_token, device_id, cookie))
            await db.commit()
            logger.info(f"Account {phone_number} saved.")
