"""CSV 导出 / 导入：往返一致、重复跳过、坏行汇报、编码处理。"""

import io

from game_ledger import database


def _post_csv(client, text: str, filename: str = "test.csv"):
    return client.post(
        "/api/import/csv",
        data={"file": (io.BytesIO(text.encode("utf-8")), filename)},
        content_type="multipart/form-data",
    )


def test_export_csv_has_bom_and_rows(client):
    database.add("NS", "塞尔达传说", 199.0, notes="备注,含逗号")
    resp = client.get("/api/export/csv")
    assert resp.status_code == 200
    assert "text/csv" in resp.mimetype
    body = resp.get_data(as_text=True)
    assert body.startswith("\ufeff")  # Excel 中文不乱码
    assert "塞尔达传说" in body
    assert "备注,含逗号" in body.replace('"备注,含逗号"', "备注,含逗号")


def test_import_export_roundtrip(client):
    database.add("NS", "测试游戏", 123.5, source="拼多多福袋", notes="备注")
    export = client.get("/api/export/csv").get_data(as_text=True)
    database.delete(database.get_all(search="测试游戏")[0]["id"])

    resp = _post_csv(client, export)
    body = resp.get_json()
    assert body["success"] is True
    assert body["data"]["imported"] == 1
    restored = database.get_all(search="测试游戏")[0]
    assert restored["price"] == 123.5
    assert restored["source"] == "拼多多福袋"
    assert restored["notes"] == "备注"


def test_import_skips_existing_same_category_name(client):
    database.add("NS", "已有游戏", 10.0)
    resp = _post_csv(client, "category,name,price\nNS,已有游戏,99\nNS,新游戏,1\n")
    body = resp.get_json()
    assert body["success"] is True
    assert body["data"]["imported"] == 1
    assert body["data"]["skipped"] == 1
    assert database.get_all(search="已有游戏")[0]["price"] == 10.0


def test_import_reports_bad_rows_without_stopping(client):
    resp = _post_csv(
        client,
        "category,name,price\nXXX,坏分类,1\nNS,好游戏,5\nNS,坏价格,abc\n",
    )
    body = resp.get_json()
    assert body["success"] is True
    assert body["data"]["imported"] == 1
    assert body["data"]["failed"] == 2
    assert len(body["data"]["errors"]) == 2
    assert "第2行" in body["data"]["errors"][0]


def test_import_missing_required_column(client):
    resp = _post_csv(client, "name,price\n只有名字,1\n")
    assert resp.status_code == 400
    assert "category" in resp.get_json()["message"]


def test_import_requires_file(client):
    resp = client.post("/api/import/csv", data={})
    assert resp.status_code == 400


def test_import_utf8_bom_accepted(client):
    text = "\ufeffcategory,name,price\nNS,BOM游戏,3.5\n"
    resp = _post_csv(client, text)
    body = resp.get_json()
    assert body["success"] is True
    assert body["data"]["imported"] == 1
    assert database.get_all(search="BOM游戏")[0]["price"] == 3.5
