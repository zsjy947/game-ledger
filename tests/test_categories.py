"""P0 新分类（PS4/PS5）与迁移 v6 的测试。"""

import sqlite3

import pytest

from game_ledger import database, records


def test_valid_categories_extended():
    assert "PS4" in records.VALID_CATEGORIES
    assert "PS5" in records.VALID_CATEGORIES
    assert "NS" in records.VALID_CATEGORIES
    # 配置的 value/class 一一对应，供前端配色使用
    for cat in records.CATEGORIES:
        assert cat["class"] == cat["value"].lower()


def test_add_ps4_record(client):
    resp = client.post(
        "/api/cartridges",
        json={"category": "PS4", "name": "瑞奇与叮当 时空跳转", "price": 268},
    )
    assert resp.status_code == 201
    assert resp.get_json()["data"]["category"] == "PS4"


def test_ps5_crud_roundtrip(client):
    resp = client.post(
        "/api/cartridges",
        json={"category": "PS5", "name": "漫威蜘蛛侠2", "price": 389, "source": "京东"},
    )
    rid = resp.get_json()["data"]["id"]

    got = client.get(f"/api/cartridges/{rid}")
    assert got.get_json()["data"]["name"] == "漫威蜘蛛侠2"

    put = client.put(f"/api/cartridges/{rid}", json={"price": 349})
    assert put.get_json()["data"]["price"] == 349

    assert client.delete(f"/api/cartridges/{rid}").status_code == 200


def test_invalid_category_still_rejected(client):
    resp = client.post(
        "/api/cartridges", json={"category": "XBOX", "name": "光环 无限"}
    )
    assert resp.status_code == 400
    assert "分类" in resp.get_json()["message"]


def test_ps4_csv_roundtrip(client):
    client.post("/api/cartridges", json={"category": "PS4", "name": "战神 诸神黄昏", "price": 299})
    exported = client.get("/api/export/csv").get_data(as_text=True)
    assert "PS4" in exported
    assert "战神 诸神黄昏" in exported


@pytest.fixture()
def v5_database(tmp_path, monkeypatch):
    """构造一个停在 v5 的旧库（含数据与价格历史），驱动真实迁移路径。"""
    db_path = tmp_path / "prices.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE cartridges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL CHECK (category IN ('NS', 'NS2')),
            name TEXT NOT NULL,
            price REAL NOT NULL DEFAULT 0,
            notes TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            source TEXT NOT NULL DEFAULT '',
            cover TEXT NOT NULL DEFAULT '',
            intro TEXT NOT NULL DEFAULT '',
            alias TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cartridge_id INTEGER NOT NULL REFERENCES cartridges(id) ON DELETE CASCADE,
            price REAL NOT NULL,
            changed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO cartridges (category, name, price, alias, source)
            VALUES ('NS', '塞尔达传说 旷野之息', 185.5, '野炊', '拼多多福袋');
        INSERT INTO price_history (cartridge_id, price, changed_at)
            VALUES (1, 185.5, '2026-01-01 00:00:00'), (1, 159.0, '2026-02-01 00:00:00');
        PRAGMA user_version = 5;
        """
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(database, "DB_PATH", db_path)
    database.init_db()
    return db_path


def test_v6_migration_preserves_data_and_history(v5_database):
    conn = sqlite3.connect(v5_database)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 6

    rows = conn.execute("SELECT id, category, name, price, alias FROM cartridges").fetchall()
    assert rows == [(1, "NS", "塞尔达传说 旷野之息", 185.5, "野炊")]

    # 关键回归点：DROP 父表重建不得级联清空价格历史
    history = conn.execute(
        "SELECT price FROM price_history WHERE cartridge_id = 1 ORDER BY changed_at"
    ).fetchall()
    assert [h[0] for h in history] == [185.5, 159.0]
    conn.close()


def test_v6_migration_drops_category_check(v5_database):
    conn = sqlite3.connect(v5_database)
    # CHECK 已移除：新平台可直接写入（合法性由 records 层校验）
    conn.execute("INSERT INTO cartridges (category, name) VALUES ('PS5', '最后生还者 第一章')")
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM cartridges").fetchone()[0] == 2
    conn.close()


def test_v6_backup_created(v5_database, tmp_path):
    backups = list(tmp_path.glob("prices.backup-v5.db"))
    assert backups, "迁移前应备份 v5 旧库"
