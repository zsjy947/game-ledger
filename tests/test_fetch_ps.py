"""fetch_ps_games 的离线解析与合并测试（不联网）。"""

import importlib.util
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "ps_store_sample.json"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "fetch_ps_games", PROJECT_ROOT / "scripts" / "fetch_ps_games.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["fetch_ps_games"] = module
    spec.loader.exec_module(module)
    return module


fps = _load_module()


def test_parse_products_shape():
    records = fps.parse_products(json.loads(FIXTURE.read_text(encoding="utf-8")))
    # 坏条目（无 id）被跳过
    assert len(records) == 2
    gow = records[0]
    assert gow["i"].startswith("PS")
    assert gow["t"] == "戰神：諸神黃昏"
    assert gow["zh"] == gow["t"]  # 港服名即中文名
    assert gow["p"] == "Sony Interactive Entertainment"
    assert gow["dt"] == "2022-11-09"
    assert gow["c"].startswith("https://")
    assert gow["g"] == "動作、冒險"
    assert gow["pl"] == "PS5"  # 双平台优先标 PS5
    assert records[1]["pl"] == "PS5"


def test_parse_products_tolerates_bad_payload():
    assert fps.parse_products({}) == []
    assert fps.parse_products({"data": None}) == []
    assert fps.parse_products({"data": {"categoryGridRetrieve": None}}) == []


def test_clean_id_charset_and_length():
    assert fps._clean_id("EP9000-PPSA03415_00-GOW") == "EP9000-PPSA03415_00-GOW"
    assert fps._clean_id("含中文与空格 id") == "id"
    assert len("PS" + fps._clean_id("x" * 500)) <= 64


def test_platform_tag():
    assert fps.platform_tag(["PS5", "PS4"]) == "PS5"
    assert fps.platform_tag(["PS4"]) == "PS4"
    assert fps.platform_tag([]) == ""


def test_merge_preserves_switch_and_is_idempotent(tmp_path):
    games_json = tmp_path / "games.json"
    games_json.write_text(
        json.dumps([{"i": "70010000000025", "t": "Zelda"}]), encoding="utf-8"
    )
    records = fps.parse_products(json.loads(FIXTURE.read_text(encoding="utf-8")))

    total1, written1 = fps.merge_into_catalog(records, games_json)
    assert total1 == 3 and written1 == 2
    merged = json.loads(games_json.read_text(encoding="utf-8"))
    # Switch 条目与排序保留在前，PS 段在后
    assert merged[0]["i"] == "70010000000025"
    assert [g["i"] for g in merged[1:]] == [r["i"] for r in records]

    # 重复合并 = 原地更新，不重复
    total2, written2 = fps.merge_into_catalog(records, games_json)
    assert total2 == 3
    assert len(json.loads(games_json.read_text(encoding="utf-8"))) == 3


def test_merge_updates_existing_ps_entry(tmp_path):
    games_json = tmp_path / "games.json"
    records = fps.parse_products(json.loads(FIXTURE.read_text(encoding="utf-8")))
    fps.merge_into_catalog(records, games_json)

    updated = [dict(records[0], d="更新后的介绍")]
    fps.merge_into_catalog(updated, games_json)
    merged = json.loads(games_json.read_text(encoding="utf-8"))
    entry = next(g for g in merged if g["i"] == records[0]["i"])
    assert entry["d"] == "更新后的介绍"
    assert len(merged) == 2
