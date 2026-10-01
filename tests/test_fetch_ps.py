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


def test_parse_concepts_shape():
    records = fps.parse_concepts(json.loads(FIXTURE.read_text(encoding="utf-8")))
    # 坏条目（无 id / 空名 / null）被跳过
    assert len(records) == 2
    yotei = records[0]
    assert yotei["i"] == "PS10007201"
    assert yotei["t"] == "羊蹄山戰鬼"
    assert yotei["zh"] == yotei["t"]  # 港服名即繁体中文
    # 封面按 role 优先级取 GAMEHUB_COVER_ART 而非 BACKGROUND_LAYER_ART
    assert yotei["c"] == "https://image.api.playstation.com/cover.jpg"
    # 无高优先级 role 时回退 MASTER
    assert records[1]["c"] == "https://image.api.playstation.com/master.jpg"


def test_parse_concepts_tolerates_bad_payload():
    assert fps.parse_concepts({}) == []
    assert fps.parse_concepts({"data": None}) == []
    assert fps.parse_concepts({"data": {"categoryGridRetrieve": None}}) == []


def test_clean_id_charset_and_length():
    assert fps._clean_id("UP9000-PPSA26344_00-GHOST2") == "UP9000-PPSA26344_00-GHOST2"
    assert fps._clean_id("含中文与空格 id") == "id"
    assert len("PS" + fps._clean_id("x" * 500)) <= 64


def test_pick_cover_roles():
    assert fps.pick_cover([]) == ""
    assert fps.pick_cover(None) == ""
    assert fps.pick_cover([{"type": "VIDEO", "role": "PREVIEW", "url": "http://x/v.mp4"}]) == ""
    assert fps.pick_cover([None, {"type": "IMAGE", "role": "KEY_ART", "url": "http://x/k.jpg"}]) == "http://x/k.jpg"


def test_apply_aliases_adds_zhs_and_curated():
    records = [
        # 羊蹄山以 Product 形态收录（npTitleId 作别名键）
        {"i": "PSPPSA26344_00", "t": "《羊蹄山戰鬼》完全版", "zh": "《羊蹄山戰鬼》完全版", "c": ""},
        {"i": "PS228748", "t": "Fortnite", "zh": "Fortnite", "c": ""},
    ]
    aliased = fps.apply_aliases(records)
    yotei = records[0]
    # OpenCC t2s
    assert yotei["zhs"] == "《羊蹄山战鬼》完全版"
    # 人工别名按条目 ID 命中
    assert yotei["zs"] == ["羊蹄山之魂", "羊蹄山"]
    assert records[1].get("zs") is None
    assert aliased == 1


def test_merge_preserves_switch_and_is_idempotent(tmp_path):
    games_json = tmp_path / "games.json"
    games_json.write_text(
        json.dumps([{"i": "70010000000025", "t": "Zelda"}]), encoding="utf-8"
    )
    records = fps.parse_concepts(json.loads(FIXTURE.read_text(encoding="utf-8")))

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
    records = fps.parse_concepts(json.loads(FIXTURE.read_text(encoding="utf-8")))
    fps.merge_into_catalog(records, games_json)

    updated = [dict(records[0], c="https://new.cover.jpg")]
    fps.merge_into_catalog(updated, games_json)
    merged = json.loads(games_json.read_text(encoding="utf-8"))
    entry = next(g for g in merged if g["i"] == records[0]["i"])
    assert entry["c"] == "https://new.cover.jpg"
    assert len(merged) == 2


SEARCH_FIXTURE = Path(__file__).parent / "fixtures" / "ps_search_sample.json"


def test_parse_search_results_concepts_and_products():
    records, cursor, total = fps.parse_search_results(
        json.loads(SEARCH_FIXTURE.read_text(encoding="utf-8"))
    )
    ids = [r["i"] for r in records]
    # 概念 + 正式版产品；DLC 与 null/坏条目被剔除
    assert "PS10012116" in ids
    assert "PSCUSA07413_00" in ids
    assert "PSPPSA26344_00" in ids
    # 同 npTitleId 的豪華版让位正式版（不重复）
    assert ids.count("PSCUSA07413_00") == 1
    assert not any("DLC" in i or "DDE" in i for i in ids)
    # 名称清洗语言后缀括号
    gow = next(r for r in records if r["i"] == "PSCUSA07413_00")
    assert gow["t"] == "God of War"
    yotei = next(r for r in records if r["i"] == "PSPPSA26344_00")
    assert yotei["t"] == "《羊蹄山戰鬼》完全版"
    assert yotei["c"] == "https://img/yotei.jpg"
    assert cursor == "CURSOR_TOKEN_1" and total == 128


def test_parse_search_results_tolerates_bad_payload():
    assert fps.parse_search_results({}) == ([], "", 0)
    assert fps.parse_search_results({"data": {"universalSearch": None}}) == ([], "", 0)
