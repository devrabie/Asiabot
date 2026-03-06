import pytest
import os
import tempfile
import aiosqlite
from src.database.db_manager import DBManager

@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp()
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.remove(path)

@pytest.mark.asyncio
async def test_settings_get_set(db_path):
    db = DBManager(db_path=db_path)
    await db.init_db()

    # Test default
    val = await db.get_setting("non_existent", "default")
    assert val == "default"

    # Test set/get
    await db.set_setting("test_key", "test_value")
    val = await db.get_setting("test_key")
    assert val == "test_value"

    # Test overwrite
    await db.set_setting("test_key", "new_value")
    val = await db.get_setting("test_key")
    assert val == "new_value"

@pytest.mark.asyncio
async def test_update_plan(db_path):
    db = DBManager(db_path=db_path)
    await db.init_db()

    # Add a plan
    await db.add_plan("Old Plan", 1000, 1, 10, 5, "Desc", 30)
    plans = await db.get_plans()
    plan = next(p for p in plans if p['name'] == "Old Plan")
    pid = plan['id']

    # Update it
    await db.update_plan(pid, "New Plan", 2000, 5, 20, 10, "New Desc", 60)

    plans = await db.get_plans()
    updated_plan = next(p for p in plans if p['id'] == pid)
    assert updated_plan['name'] == "New Plan"
    assert updated_plan['price'] == 2000
    assert updated_plan['max_accounts'] == 5
    assert updated_plan['description'] == "New Desc"
    assert updated_plan['duration_days'] == 60

@pytest.mark.asyncio
async def test_get_user_subscription_fallback(db_path):
    db = DBManager(db_path=db_path)
    await db.init_db()

    user_id = 999
    await db.create_user_if_not_exists(user_id)

    # Seeded Free plan should be default
    sub = await db.get_user_subscription(user_id)
    assert sub['name'] == "Free"

    # Add another plan 'Pro'
    await db.add_plan("Pro", 5000, 8, 100, 50, "Pro plan", 30)

    # Delete 'Free' plan (usually ID 1)
    await db.delete_plan(1)

    # User should NOT fallback to 'Pro', should get 'No active plan'
    sub = await db.get_user_subscription(999)
    assert sub['name'] == "No active plan"
    assert sub['max_accounts'] == 0

@pytest.mark.asyncio
async def test_get_user_subscription_orphaned_id(db_path):
    db = DBManager(db_path=db_path)
    await db.init_db()

    user_id = 111
    await db.create_user_if_not_exists(user_id)

    # Manually set an orphaned plan_id
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("UPDATE users SET plan_id = 999 WHERE telegram_id = ?", (user_id,))
        await conn.commit()

    # Should fallback to 'Free' (seeded in init_db)
    sub = await db.get_user_subscription(user_id)
    assert sub['name'] == "Free"
