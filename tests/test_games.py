"""内置游戏库搜索测试：中文名 / 简体化名 / 人工别名的匹配与排序。"""

import pytest

from game_ledger import games


@pytest.fixture()
def catalog(monkeypatch):
    """注入小型目录夹具，覆盖英文名/繁体/简体/别名各形态。"""
    fixture = [
        {"i": "1", "t": "The Legend of Zelda: Tears of the Kingdom",
         "zh": "薩爾達傳說 王國之淚", "zhs": "塞尔达传说 王国之泪",
         "zs": ["王国之泪", "塞尔达王国之泪"], "c": "x"},
        {"i": "2", "t": "Splatoon 3", "zh": "斯普拉遁 3", "zhs": "斯普拉遁 3",
         "zs": ["喷射战士3", "喷射战士"], "c": "x"},
        {"i": "3", "t": "Super Mario Odyssey", "zh": "超級瑪利歐 奧德賽",
         "zhs": "超级马力欧 奥德赛", "c": "x"},
        {"i": "4", "t": "Yoshi and the Mysterious Book", "zs": ["耀西"], "c": "x"},
        {"i": "5", "t": "Kirby and the Forgotten Land", "zh": "星之卡比 探索發現",
         "zhs": "星之卡比 探索发现", "c": "x"},
    ]
    monkeypatch.setattr(games, "_catalog", fixture, raising=False)
    monkeypatch.setattr(
        games, "_index", {g["i"]: g for g in fixture}, raising=False
    )
    return fixture


def test_search_english(catalog):
    hits = games.search("zelda")
    assert hits and hits[0]["i"] == "1"


def test_search_by_simplified(catalog):
    hits = games.search("王国之泪")
    assert hits and hits[0]["i"] == "1"


def test_search_by_traditional(catalog):
    hits = games.search("斯普拉遁")
    assert hits and hits[0]["i"] == "2"


def test_search_by_alias(catalog):
    hits = games.search("喷射战士3")
    assert hits and hits[0]["i"] == "2"


def test_search_alias_reverse_containment(catalog):
    """输入长记录名命中短别名（别名 ⊆ 输入）。"""
    hits = games.search("耀西与不可思议图鉴")
    assert hits and hits[0]["i"] == "4"


def test_search_prefix_beats_contains(catalog):
    hits = games.search("塞尔达")
    assert hits[0]["i"] == "1"
    hits = games.search("星之卡比")
    assert hits[0]["i"] == "5"


def test_search_no_result(catalog):
    assert games.search("不存在游戏xyz") == []


def test_search_empty(catalog):
    assert games.search("") == []
    assert games.search("   ") == []


def test_search_ignores_whitespace(catalog):
    hits = games.search("王国 之泪")
    assert hits and hits[0]["i"] == "1"


def test_clean_game_desc_strips_tags():
    assert games.clean_game_desc("<p>A  <b>B</b></p>") == "A B"
