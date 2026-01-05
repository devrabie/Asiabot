CREATE TABLE IF NOT EXISTS users (
    telegram_id INTEGER PRIMARY KEY,
    is_admin BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    phone_number TEXT UNIQUE NOT NULL,
    device_id TEXT,
    cookie TEXT,
    access_token TEXT,
    refresh_token TEXT,
    current_balance REAL DEFAULT 0.0,
    last_balance_update TIMESTAMP,
    token_updated_at TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(telegram_id) ON DELETE CASCADE
);
