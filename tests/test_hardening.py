"""审查加固项：LIKE 转义、封面路由防路径穿越、CSV 时间戳保真。"""

import io

from switch_price_tracker import database


def _post_csv(client, text: str):
    return client.post(
        "/api/import/csv",
        data={"file": (io.BytesIO(text.encode("utf-8")), "test.csv")},
        content_type="multipart/form-data",
    )


# ── LIKE 通配符按字面匹配 ────────────────────────────────────────────────────

def test_search_escapes_percent_wildcard(client):
    database.add("NS", "100%酒馆", 10.0)
    database.add("NS", "普通游戏", 20.0)
    # 旧实现里 % 是通配符，搜「%」会命中全部记录
    hits = database.get_all(search="%")
    assert len(hits) == 1
    assert hits[0]["name"] == "100%酒馆"


def test_search_escapes_underscore_wildcard(client):
    database.add("NS", "x_y游戏", 10.0)
    database.add("NS", "xyy游戏", 20.0)
    # 旧实现里 _ 是通配符，搜「x_y」会同时命中「xyy游戏」
    hits = database.get_all(search="x_y")
    assert len(hits) == 1
    assert hits[0]["name"] == "x_y游戏"


def test_suggest_escapes_like_wildcards(client):
    database.add("NS", "50%off游戏", 10.0)
    database.add("NS", "另一个游戏", 20.0)
    hits = database.search_suggest("%")
    assert len(hits) == 1
    assert hits[0]["name"] == "50%off游戏"


# ── 封面路由防路径穿越 ───────────────────────────────────────────────────────

def test_cover_route_rejects_traversal(client):
    for bad in ["..%5C..%5Cprices", "..", "a/b", r"..\\x"]:
        resp = client.get(f"/cover/{bad}")
        assert resp.status_code == 404, bad


def test_cover_route_valid_but_unknown_id(client):
    # 合法格式的未知 ID：不触网直接 404
    assert client.get("/cover/99999999999999").status_code == 404


# ── CSV 导入时间戳保真 ───────────────────────────────────────────────────────

def test_import_preserves_timestamps(client):
    database.add("NS", "老游戏", 50.0)
    original = database.get_all(search="老游戏")[0]
    export = client.get("/api/export/csv").get_data(as_text=True)
    database.delete(original["id"])

    body = _post_csv(client, export).get_json()
    assert body["data"]["imported"] == 1
    restored = database.get_all(search="老游戏")[0]
    assert restored["created_at"] == original["created_at"]
    assert restored["updated_at"] == original["updated_at"]
    # 价格历史沿用记录的原始时间
    hist = database.get_price_history(restored["id"])
    assert hist and hist[0]["changed_at"] == original["updated_at"]


def test_import_rejects_malformed_timestamp(client):
    body = _post_csv(
        client, "category,name,price,created_at\nNS,坏时间,1,2026/01/01\n"
    ).get_json()
    assert body["data"]["failed"] == 1
    assert "时间格式" in body["data"]["errors"][0]
