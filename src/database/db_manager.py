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
            await db.execute("PRAGMA foreign_keys = ON")
            await db.executescript(schema)

            # Migration: Check if is_primary_receiver column exists
            try:
                await db.execute("SELECT is_primary_receiver FROM accounts LIMIT 1")
            except aiosqlite.OperationalError:
                logger.info("Migrating database: Adding is_primary_receiver column to accounts table.")
                await db.execute("ALTER TABLE accounts ADD COLUMN is_primary_receiver BOOLEAN DEFAULT 0")

            # Migration: Check if users table has username column
            try:
                await db.execute("SELECT username FROM users LIMIT 1")
            except aiosqlite.OperationalError:
                logger.info("Migrating database: Adding new columns to users table.")
                await db.execute("ALTER TABLE users ADD COLUMN username TEXT")
                await db.execute("ALTER TABLE users ADD COLUMN first_name TEXT")
                await db.execute("ALTER TABLE users ADD COLUMN plan_id INTEGER REFERENCES plans(id)")
                await db.execute("ALTER TABLE users ADD COLUMN plan_expiry TIMESTAMP")

            # Check if plans table exists (handled by executescript but let's be safe regarding initial setup)
            # No specific action needed if executescript runs, but adding default plan if table is empty is good
            try:
                async with db.execute("SELECT count(*) FROM plans") as cursor:
                    count = await cursor.fetchone()
                    if count[0] == 0:
                        logger.info("Seeding default plan.")
                        await db.execute("INSERT INTO plans (name, price, max_accounts, description) VALUES ('Free', 0, 1, 'Free plan')")
            except Exception as e:
                logger.error(f"Error seeding plans: {e}")

            await db.commit()
            logger.info("Database initialized successfully.")

    async def create_user_if_not_exists(self, telegram_id: int):
        """Create a user if they don't exist."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            await db.execute(
                "INSERT OR IGNORE INTO users (telegram_id) VALUES (?)",
                (telegram_id,)
            )
            await db.commit()

    async def update_user_profile(self, user_id: int, username: str, first_name: str):
        """Update user profile info."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE users SET username = ?, first_name = ? WHERE telegram_id = ?",
                (username, first_name, user_id)
            )
            await db.commit()

    async def add_plan(self, name: str, price: float, max_accounts: int, description: str, duration_days: int):
        """Add a new subscription plan."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO plans (name, price, max_accounts, description, duration_days) VALUES (?, ?, ?, ?, ?)",
                (name, price, max_accounts, description, duration_days)
            )
            await db.commit()

    async def get_plans(self) -> List[dict]:
        """Get all available plans."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM plans") as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def delete_plan(self, plan_id: int):
        """Delete a plan."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM plans WHERE id = ?", (plan_id,))
            await db.commit()

    async def grant_subscription(self, user_id: int, plan_id: int, duration_days: int):
        """Grant a subscription plan to a user."""
        from datetime import timedelta
        expiry = datetime.now() + timedelta(days=duration_days)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE users SET plan_id = ?, plan_expiry = ? WHERE telegram_id = ?",
                (plan_id, expiry, user_id)
            )
            await db.commit()

    async def get_user_subscription(self, user_id: int) -> dict:
        """Get user subscription details."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            query = """
                SELECT u.plan_id, u.plan_expiry, p.name, p.max_accounts
                FROM users u
                LEFT JOIN plans p ON u.plan_id = p.id
                WHERE u.telegram_id = ?
            """
            async with db.execute(query, (user_id,)) as cursor:
                row = await cursor.fetchone()
                if row and row['plan_id']:
                    # Check expiry
                    expiry = datetime.fromisoformat(str(row['plan_expiry'])) if row['plan_expiry'] else None
                    if expiry and expiry > datetime.now():
                        return dict(row)

                # Default/Fallback (Free plan assumed if not found or expired)
                # Ideally, fetch default plan (ID 1 usually) or hardcode free limits
                return {"name": "Free", "max_accounts": 1, "plan_id": None}

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
            await db.execute("PRAGMA foreign_keys = ON")
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

    async def get_all_accounts(self) -> List[dict]:
        """Returns all accounts in the database."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM accounts") as cursor:
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

    async def get_account(self, phone_number: str, user_id: int) -> Optional[dict]:
        """Fetch a specific account for a user."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM accounts WHERE phone_number = ? AND user_id = ?",
                (phone_number, user_id)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def delete_account(self, phone_number: str, user_id: int) -> bool:
        """Delete an account if it belongs to the user."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM accounts WHERE phone_number = ? AND user_id = ?",
                (phone_number, user_id)
            )
            await db.commit()
            return cursor.rowcount > 0

    async def set_primary_receiver(self, user_id: int, phone_number: str):
        """Set an account as the primary receiver for a user."""
        async with aiosqlite.connect(self.db_path) as db:
            # First, set all accounts for this user to False
            await db.execute(
                "UPDATE accounts SET is_primary_receiver = 0 WHERE user_id = ?",
                (user_id,)
            )

            # Then set the specified account to True
            await db.execute(
                "UPDATE accounts SET is_primary_receiver = 1 WHERE user_id = ? AND phone_number = ?",
                (user_id, phone_number)
            )
            await db.commit()
            logger.info(f"Set account {phone_number} as primary receiver for user {user_id}.")

    async def get_all_users_with_accounts(self) -> List[dict]:
        """Fetch all users and their associated accounts for admin display."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            # Fetch users
            async with db.execute("SELECT * FROM users") as cursor:
                users = await cursor.fetchall()

            result = []
            for user in users:
                user_dict = dict(user)
                # Fetch accounts for this user
                async with db.execute("SELECT * FROM accounts WHERE user_id = ?", (user['telegram_id'],)) as acc_cursor:
                    accounts = await acc_cursor.fetchall()
                    user_dict['accounts'] = [dict(acc) for acc in accounts]
                result.append(user_dict)

            return result
