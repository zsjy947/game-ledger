"""数据访问层单元测试。"""

import sqlite3

from switch_price_tracker import database


def test_add_and_get(client):
    record = database.add("NS", "塞尔达传说 旷野之息", 199.0, "9成新")
    assert record["id"] > 0
    assert record["name"] == "塞尔达传说 旷野之息"
    assert database.get_by_id(record["id"])["notes"] == "9成新"
    assert database.get_by_id(99999) is None


def test_source_field(client):
    """来源字段可写入预设值与自定义值。"""
    r1 = database.add("NS", "卡带A", 100.0, source="拼多多福袋")
    r2 = database.add("NS2", "卡带B", 200.0, source="闲鱼收的")
    assert database.get_by_id(r1["id"])["source"] == "拼多多福袋"
    assert database.get_by_id(r2["id"])["source"] == "闲鱼收的"
    assert database.get_by_id(database.add("NS", "卡带C", 1.0)["id"])["source"] == ""


def test_get_all_filters(client):
    database.add("NS", "马里奥奥德赛", 199.0, source="拼多多福袋")
    database.add("NS2", "马力欧赛车世界", 299.0, source="支付宝刷券")
    assert len(database.get_all()) == 2
    assert [r["name"] for r in database.get_all(category="NS2")] == ["马力欧赛车世界"]
    assert len(database.get_all(search="奥德赛")) == 1
    assert [r["name"] for r in database.get_all(source="支付宝刷券")] == ["马力欧赛车世界"]
    assert len(database.get_all(source="拼多多V3")) == 0


def test_update(client):
    record = database.add("NS", "测试卡带", 100.0)
    updated = database.update(record["id"], "NS2", "测试卡带2", 150.0, "改价", "拼多多V3")
    assert updated["price"] == 150.0
    assert updated["category"] == "NS2"
    assert updated["source"] == "拼多多V3"
    assert updated["updated_at"] >= record["updated_at"]
    assert database.update(99999, "NS", "不存在", 1.0) is None


def test_delete(client):
    record = database.add("NS", "待删除", 10.0)
    assert database.delete(record["id"]) is True
    assert database.delete(record["id"]) is False
    assert database.get_by_id(record["id"]) is None


def test_suggest_exact_first(client):
    database.add("NS", "塞尔达传说 旷野之息", 199.0)
    database.add("NS", "塞尔达传说 王国之泪", 259.0)
    result = database.search_suggest("塞尔达传说 旷野之息")
    assert result[0]["name"] == "塞尔达传说 旷野之息"  # 精确匹配排最前
    fuzzy = database.search_suggest("塞尔达")
    assert {r["name"] for r in fuzzy} == {"塞尔达传说 旷野之息", "塞尔达传说 王国之泪"}


def test_suggest_limit(client):
    for i in range(8):
        database.add("NS", f"卡带{i:02d}", 10.0)
    assert len(database.search_suggest("卡带")) == 5


def test_init_idempotent(client):
    database.init_db()
    database.init_db()
    assert database.add("NS", "重复初始化", 5.0)["id"] > 0


def test_migration_v1_to_v2(tmp_path):
    """模拟 v1 旧库（无 source 列）：init_db 应自动升级且数据无损。"""
    import importlib

    db_path = tmp_path / "old.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE cartridges (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               category TEXT NOT NULL CHECK (category IN ('NS', 'NS2')),
               name TEXT NOT NULL,
               price REAL,
               notes TEXT DEFAULT '',
               created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
               updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
           )"""
    )
    conn.execute(
        "INSERT INTO cartridges (category, name, price, notes) VALUES ('NS', '旧记录', 88.0, 'v1数据')"
    )
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()

    database.DB_PATH = db_path
    try:
        database.init_db()
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        columns = [r["name"] for r in conn.execute("PRAGMA table_info(cartridges)")]
        assert "source" in columns
        assert conn.execute("PRAGMA user_version").fetchone()[0] == database.SCHEMA_VERSION
        row = conn.execute("SELECT * FROM cartridges WHERE name = '旧记录'").fetchone()
        assert row["price"] == 88.0
        assert row["source"] == ""
        conn.close()

        # 幂等：再次初始化不报错
        database.init_db()
    finally:
        importlib.reload(database)  # 恢复模块全局状态，避免影响其他测试
