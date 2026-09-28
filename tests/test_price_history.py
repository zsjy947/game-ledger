"""价格历史：写入时机、级联删除、查询与联想接口附带最低价。"""

import pytest

from game_ledger import database


def test_add_records_initial_price(client):
    rec = database.add("NS", "测试A", 199.0)
    hist = database.get_price_history(rec["id"])
    assert len(hist) == 1
    assert hist[0]["price"] == 199.0
    assert hist[0]["changed_at"]


def test_add_zero_price_no_history(client):
    rec = database.add("NS", "测试A", 0)
    assert database.get_price_history(rec["id"]) == []


def test_update_price_change_records_history(client):
    rec = database.add("NS", "测试A", 100.0)
    database.update(rec["id"], "NS", "测试A", 80.0)
    database.update(rec["id"], "NS", "测试A", 80.0)  # 同价不重复记录
    hist = database.get_price_history(rec["id"])
    assert [h["price"] for h in hist] == [100.0, 80.0]


def test_update_clear_price_no_history_row(client):
    rec = database.add("NS", "测试A", 100.0)
    database.update(rec["id"], "NS", "测试A", 0)  # 清空价格不记历史
    assert [h["price"] for h in database.get_price_history(rec["id"])] == [100.0]


def test_delete_cascades_history(client):
    rec = database.add("NS", "测试A", 50.0)
    assert database.delete(rec["id"])
    assert database.get_price_history(rec["id"]) == []


def test_get_min_prices_batch(client):
    a = database.add("NS", "测试A", 100.0)
    b = database.add("NS", "测试B", 0)
    database.update(a["id"], "NS", "测试A", 60.0)
    mins = database.get_min_prices([a["id"], b["id"]])
    assert mins[a["id"]] == 60.0
    assert b["id"] not in mins  # 无历史的不在结果里
    assert database.get_min_prices([]) == {}


def test_history_api_404_for_missing(client):
    resp = client.get("/api/cartridges/9999/history")
    assert resp.status_code == 404
    assert resp.get_json()["success"] is False


def test_history_api_returns_rows(client):
    rec = database.add("NS", "测试A", 100.0)
    database.update(rec["id"], "NS", "测试A", 88.0)
    resp = client.get(f"/api/cartridges/{rec['id']}/history")
    body = resp.get_json()
    assert body["success"] is True
    assert [h["price"] for h in body["data"]] == [100.0, 88.0]


def test_suggest_includes_min_price(client):
    rec = database.add("NS", "塞尔达传说", 100.0)
    database.update(rec["id"], "NS", "塞尔达传说", 60.0)
    resp = client.get("/api/cartridges/suggest?q=塞尔达")
    data = resp.get_json()["data"]
    assert data and data[0]["min_price"] == 60.0
