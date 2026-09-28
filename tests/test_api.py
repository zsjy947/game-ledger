"""REST API 接口测试。"""

from switch_price_tracker import __version__


def test_index_page(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Switch 卡带价格统计".encode() in resp.data
    # 来源预设（tojson 转义注入）与版本号
    html = resp.get_data(as_text=True)
    assert "sourcePresets" in html
    assert "\\u62fc\\u591a\\u591a\\u798f\\u888b" in html  # "拼多多福袋" 的 JS 转义形式
    assert f"v{__version__}" in html


def test_add_and_list(client):
    resp = client.post(
        "/api/cartridges",
        json={"category": "NS", "name": "新卡带", "price": "129.9", "source": "拼多多福袋"},
    )
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["success"] is True
    assert body["data"]["price"] == 129.9
    assert body["data"]["source"] == "拼多多福袋"

    resp = client.get("/api/cartridges")
    assert resp.get_json()["success"] is True
    assert len(resp.get_json()["data"]) == 1


def test_add_defaults(client):
    """缺省价格/备注/来源时补默认值，而不是写入 NULL。"""
    resp = client.post("/api/cartridges", json={"category": "NS2", "name": "无价格"})
    data = resp.get_json()["data"]
    assert resp.status_code == 201
    assert data["price"] == 0.0
    assert data["notes"] == ""
    assert data["source"] == ""


def test_add_validation(client):
    resp = client.post("/api/cartridges", json={"category": "XX", "name": "x"})
    assert resp.status_code == 400
    assert "分类" in resp.get_json()["message"]

    resp = client.post("/api/cartridges", json={"category": "NS", "name": "  "})
    assert resp.status_code == 400
    assert "名称" in resp.get_json()["message"]

    resp = client.post("/api/cartridges", json={"category": "NS", "name": "x", "price": "abc"})
    assert resp.status_code == 400
    assert "价格" in resp.get_json()["message"]

    resp = client.post("/api/cartridges", json={"category": "NS", "name": "x", "price": -1})
    assert resp.status_code == 400


def test_price_rejects_non_finite_and_bool(client):
    """NaN/Infinity/布尔值价格一律 400：NaN 写入 SQLite 会变成 NULL，触发未处理的 500。"""
    for bad in (float("nan"), float("inf"), float("-inf"), True):
        resp = client.post(
            "/api/cartridges", json={"category": "NS", "name": "x", "price": bad}
        )
        assert resp.status_code == 400, f"price={bad!r} 应返回 400"
        assert "价格" in resp.get_json()["message"]

    record = client.post(
        "/api/cartridges", json={"category": "NS", "name": "x", "price": 1}
    ).get_json()["data"]
    resp = client.put(
        f"/api/cartridges/{record['id']}", json={"price": float("nan")}
    )
    assert resp.status_code == 400

    resp = client.post(
        "/api/cartridges", json={"category": "NS", "name": "x", "source": "超" * 51}
    )
    assert resp.status_code == 400
    assert "来源" in resp.get_json()["message"]

    resp = client.post("/api/cartridges", data="not json", content_type="text/plain")
    assert resp.status_code == 400


def test_update_partial_fields(client):
    record = client.post(
        "/api/cartridges",
        json={"category": "NS", "name": "旧名字", "price": 10, "source": "支付宝刷券"},
    ).get_json()["data"]

    resp = client.put(f"/api/cartridges/{record['id']}", json={"price": 20})
    body = resp.get_json()
    assert body["success"] is True
    assert body["data"]["name"] == "旧名字"  # 未提供的字段保留原值
    assert body["data"]["price"] == 20.0
    assert body["data"]["source"] == "支付宝刷券"

    # 也可清除来源
    resp = client.put(f"/api/cartridges/{record['id']}", json={"source": ""})
    assert resp.get_json()["data"]["source"] == ""


def test_source_filter(client):
    client.post("/api/cartridges", json={"category": "NS", "name": "A", "source": "拼多多福袋"})
    client.post("/api/cartridges", json={"category": "NS", "name": "B", "source": "自定义渠道"})

    resp = client.get("/api/cartridges?source=拼多多福袋")
    names = [r["name"] for r in resp.get_json()["data"]]
    assert names == ["A"]


def test_cover_and_intro_roundtrip(client):
    resp = client.post(
        "/api/cartridges",
        json={
            "category": "NS",
            "name": "塞尔达",
            "cover": "70010000000234",
            "intro": "开放世界冒险。",
        },
    )
    assert resp.status_code == 201
    data = resp.get_json()["data"]
    assert data["cover"] == "70010000000234"
    assert data["intro"] == "开放世界冒险。"

    # 解除关联
    resp = client.put(f"/api/cartridges/{data['id']}", json={"cover": "", "intro": ""})
    assert resp.get_json()["data"]["cover"] == ""

    # intro 超长校验
    resp = client.post(
        "/api/cartridges", json={"category": "NS", "name": "x", "intro": "长" * 6001}
    )
    assert resp.status_code == 400
    assert "介绍" in resp.get_json()["message"]


def test_cover_route(client, monkeypatch):
    """/cover/<id>：命中返回图片，未命中返回 404。"""
    from switch_price_tracker import games

    resp = client.get("/cover/unknown-game")
    assert resp.status_code == 404

    monkeypatch.setattr(games, "resolve_cover", lambda gid: b"\xff\xd8fake-jpeg")
    resp = client.get("/cover/70010000000234")
    assert resp.status_code == 200
    assert resp.mimetype == "image/jpeg"
    assert resp.data == b"\xff\xd8fake-jpeg"


def test_delete_flow(client):
    record = client.post(
        "/api/cartridges", json={"category": "NS", "name": "待删", "price": 1}
    ).get_json()["data"]

    resp = client.delete(f"/api/cartridges/{record['id']}")
    assert resp.get_json()["success"] is True

    resp = client.get(f"/api/cartridges/{record['id']}")
    assert resp.status_code == 404
    assert resp.get_json()["success"] is False


def test_update_missing_record(client):
    resp = client.put("/api/cartridges/4242", json={"name": "x"})
    assert resp.status_code == 404


def test_unknown_api_returns_json(client):
    resp = client.get("/api/unknown")
    assert resp.status_code == 404
    assert resp.get_json()["success"] is False


def test_suggest_endpoint(client):
    client.post("/api/cartridges", json={"category": "NS", "name": "塞尔达传说", "price": 199})
    resp = client.get("/api/cartridges/suggest?q=塞尔达")
    body = resp.get_json()
    assert body["success"] is True
    assert len(body["data"]) == 1


def test_games_catalog_api(client, monkeypatch):
    """游戏目录单源接口：服务端内存直出，桌面端不再依赖静态 games.js。"""
    from switch_price_tracker import games

    monkeypatch.setattr(games, "_catalog", [{"i": "1", "t": "Fake Game"}], raising=False)
    resp = client.get("/api/games/catalog")
    body = resp.get_json()
    assert body["success"] is True
    assert body["data"][0]["t"] == "Fake Game"
    assert "no-cache" in resp.headers["Cache-Control"]
