"""用户自定义别名字段（v5）：检索、联想、更新与 CSV 往返。"""

import io

from game_ledger import database, records


def _post_csv(client, text: str):
    return client.post(
        "/api/import/csv",
        data={"file": (io.BytesIO(text.encode("utf-8")), "test.csv")},
        content_type="multipart/form-data",
    )


def test_alias_stored_and_searchable(client):
    rec = database.add("NS", "塞尔达传说 旷野之息", 100.0, alias="野炊")
    assert rec["alias"] == "野炊"
    assert [r["id"] for r in database.get_all(search="野炊")] == [rec["id"]]
    # 正常名称检索不受影响
    assert [r["id"] for r in database.get_all(search="旷野之息")] == [rec["id"]]


def test_alias_empty_by_default(client):
    other = database.add("NS", "普通游戏", 1.0)
    assert other["alias"] == ""
    assert database.get_all(search="游戏")


def test_alias_suggest(client):
    database.add("NS", "塞尔达传说 旷野之息", 100.0, alias="野炊")
    hits = database.search_suggest("野炊")
    assert len(hits) == 1
    assert hits[0]["name"] == "塞尔达传说 旷野之息"


def test_update_alias(client):
    rec = database.add("NS", "测试A", 1.0)
    database.update(rec["id"], "NS", "测试A", 1.0, alias="别名1")
    assert database.get_by_id(rec["id"])["alias"] == "别名1"
    database.update(rec["id"], "NS", "测试A", 1.0, alias="")
    assert database.get_by_id(rec["id"])["alias"] == ""


def test_alias_max_length_rejected(client):
    fields, error = records.parse_payload(
        {"category": "NS", "name": "x", "alias": "a" * 101}
    )
    assert fields is None and "别名" in error
    fields, error = records.parse_payload(
        {"category": "NS", "name": "x", "alias": "野炊"}
    )
    assert error is None and fields["alias"] == "野炊"


def test_csv_alias_roundtrip(client):
    database.add("NS", "塞尔达传说 旷野之息", 99.0, alias="野炊")
    export = client.get("/api/export/csv").get_data(as_text=True)
    database.delete(database.get_all(search="旷野之息")[0]["id"])

    body = _post_csv(client, export).get_json()
    assert body["data"]["imported"] == 1
    assert database.get_all(search="野炊")[0]["alias"] == "野炊"


def test_alias_api_roundtrip(client):
    resp = client.post(
        "/api/cartridges",
        json={"category": "NS", "name": "塞尔达传说 旷野之息", "price": 199, "alias": "野炊"},
    )
    assert resp.status_code == 201
    data = resp.get_json()["data"]
    assert data["alias"] == "野炊"
    # 别名可被列表检索接口命中
    resp = client.get("/api/cartridges?search=" + "野炊")
    assert len(resp.get_json()["data"]) == 1
