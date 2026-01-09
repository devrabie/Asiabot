CREATE TABLE IF NOT EXISTS users (
    telegram_id INTEGER PRIMARY KEY,
    is_admin BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    username TEXT,
    first_name TEXT,
    plan_id INTEGER,
    plan_expiry TIMESTAMP,
    FOREIGN KEY(plan_id) REFERENCES plans(id)
);

CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    price REAL DEFAULT 0,
    max_accounts INTEGER DEFAULT 1,
    description TEXT,
    duration_days INTEGER DEFAULT 30
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
    is_primary_receiver BOOLEAN DEFAULT 0,
    FOREIGN KEY(user_id) REFERENCES users(telegram_id) ON DELETE CASCADE
);
