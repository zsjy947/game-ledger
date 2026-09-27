"""数据访问层单元测试。"""

import sqlite3

from switch_price_tracker import database


def test_add_and_get(client):
    record = database.add("NS", "塞尔达传说 旷野之息", 199.0, "9成新")
    assert record["id"] > 0
    assert record["name"] == "塞尔达传说 旷野之息"
    assert database.get_by_id(record["id"])["notes"] == "9成新"
    assert database.get_by_id(99999) is None


def test_source_and_game_fields(client):
    """来源与游戏库字段（cover/intro）可写入。"""
    r1 = database.add("NS", "卡带A", 100.0, source="拼多多福袋", cover="70010000000234", intro="这是一段游戏介绍。")
    got = database.get_by_id(r1["id"])
    assert got["source"] == "拼多多福袋"
    assert got["cover"] == "70010000000234"
    assert got["intro"] == "这是一段游戏介绍。"
    r2 = database.add("NS2", "卡带B", 200.0)
    assert database.get_by_id(r2["id"])["cover"] == ""
    assert database.get_by_id(r2["id"])["intro"] == ""


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
    updated = database.update(record["id"], "NS2", "测试卡带2", 150.0, "改价", "拼多多V3", "70010000000123", "新介绍")
    assert updated["price"] == 150.0
    assert updated["category"] == "NS2"
    assert updated["source"] == "拼多多V3"
    assert updated["cover"] == "70010000000123"
    assert updated["intro"] == "新介绍"
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
    """模拟 v1 旧库（无 source/cover/intro 列）：init_db 应自动升级且数据无损。"""
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
        assert "cover" in columns
        assert "intro" in columns
        assert conn.execute("PRAGMA user_version").fetchone()[0] == database.SCHEMA_VERSION
        row = conn.execute("SELECT * FROM cartridges WHERE name = '旧记录'").fetchone()
        assert row["price"] == 88.0
        assert row["source"] == ""
        assert row["cover"] == ""
        conn.close()

        # 幂等：再次初始化不报错
        database.init_db()
    finally:
        importlib.reload(database)  # 恢复模块全局状态，避免影响其他测试


def test_games_module(tmp_path, monkeypatch):
    """内置游戏库：搜索与封面解析（内置资源优先，其次缓存，最后在线）。"""
    import json

    from switch_price_tracker import config, games

    games_dir = tmp_path / "assets"
    games_dir.mkdir()
    fake = [
        {"i": "70010000000234", "t": "The Legend of Zelda: Breath of the Wild",
         "d": "An open-world adventure.", "c": "https://example.com/a.jpg",
         "p": "Nintendo", "g": "Action", "dt": "2017-03-03", "h": 999, "pl": 1},
        {"i": "70010000002406", "t": "Splatoon 3", "d": "Ink up!", "c": "",
         "p": "Nintendo", "g": "Shooter", "dt": "2022-09-09", "h": 500, "pl": 8},
    ]
    (games_dir / "games.json").write_text(json.dumps(fake), encoding="utf-8")
    covers_dir = games_dir / "covers"
    covers_dir.mkdir()
    (covers_dir / "70010000000234.jpg").write_bytes(b"\xff\xd8 bundled-jpeg")

    monkeypatch.setattr(games, "_catalog", None)
    monkeypatch.setattr(games, "_index", None)
    monkeypatch.setattr(config, "ASSETS_DIR", games_dir)
    monkeypatch.setattr(games, "ASSETS_DIR", games_dir)
    monkeypatch.setattr(games, "BUNDLED_COVERS_DIR", covers_dir)

    games._load()
    assert len(games.all_games()) == 2
    assert games.search("zelda")[0]["i"] == "70010000000234"   # 按标题搜索
    assert games.search("zelda")[0]["d"] == "An open-world adventure."
    assert games.get("70010000002406")["t"] == "Splatoon 3"
    assert games.get("99999") is None

    # 封面解析：内置资源命中
    assert games.resolve_cover("70010000000234") == b"\xff\xd8 bundled-jpeg"

    # 封面解析：在线下载并写入缓存
    monkeypatch.setattr(config, "COVER_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(games, "COVER_CACHE_DIR", tmp_path / "cache")

    def fake_urlopen(req, timeout=20):
        class R:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def read(self, n=-1):
                return b"\xff\xd8 downloaded"

        return R()

    monkeypatch.setattr(games.urllib.request, "urlopen", fake_urlopen)
    assert games.resolve_cover("70010000002406") is None  # 目录里没有封面 URL
    fake2 = dict(fake[1], c="https://example.com/b.jpg")
    monkeypatch.setattr(games, "_index", {"70010000002406": fake2})
    assert games.resolve_cover("70010000002406") == b"\xff\xd8 downloaded"
    assert (tmp_path / "cache" / "70010000002406.jpg").read_bytes() == b"\xff\xd8 downloaded"
