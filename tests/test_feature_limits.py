import pytest
import os
import tempfile
from src.database.db_manager import DBManager

@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp()
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.remove(path)

@pytest.mark.asyncio
async def test_recharge_feature_limits(db_path):
    db = DBManager(db_path=db_path)
    await db.init_db()

    user_id = 12345
    await db.create_user_if_not_exists(user_id)

    # Custom plan with limits
    await db.add_plan("Limited", 0, 1, 2, 1, "Limited recharges", 30)
    # Assign plan
    await db.grant_subscription(user_id, 2, 30) # Assuming it's the second plan after Free

    sub = await db.get_user_subscription(user_id)
    assert sub['max_text_recharges'] == 2
    assert sub['max_image_recharges'] == 1
    assert sub['text_recharges_count'] == 0

    # Increment text usage
    await db.increment_usage(user_id, "text")
    sub = await db.get_user_subscription(user_id)
    assert sub['text_recharges_count'] == 1

    # Increment image usage
    await db.increment_usage(user_id, "image")
    sub = await db.get_user_subscription(user_id)
    assert sub['image_recharges_count'] == 1

    # Test update plan limits
    await db.update_plan(2, "Limited v2", 0, 1, 5, 3, "New limits", 30)
    sub = await db.get_user_subscription(user_id)
    assert sub['max_text_recharges'] == 5
    assert sub['max_image_recharges'] == 3
