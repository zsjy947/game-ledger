"""内置游戏库：加载打包时生成的 games.json，提供搜索与封面解析。

目录数据由 scripts/fetch_games.py 从 Nintendo eShop（欧洲区）抓取生成，
随应用内置，离线可用；封面优先使用内置资源，其余按需下载缓存到 data/covers。
"""

import html
import json
import re
import urllib.request

from .config import ASSETS_DIR, BUNDLED_COVERS_DIR, COVER_CACHE_DIR

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) switch-price-tracker"
_TAG_RE = re.compile(r"<[^>]+>")
# 中文名（繁/简/别名）判定：反向包含匹配只对含中文的短名启用
CJK_RE = re.compile(r"[\u4e00-\u9fff]")

_catalog: list | None = None
_index: dict | None = None


def _load() -> list:
    global _catalog, _index
    if _catalog is None:
        path = ASSETS_DIR / "games.json"
        _catalog = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        _index = {g["i"]: g for g in _catalog}
    return _catalog


def all_games() -> list:
    """返回完整内置目录（按热度倒序）。"""
    return _load()


def get(game_id: str):
    """按游戏 ID（NSUID）取目录条目。"""
    _load()
    return _index.get(game_id)


def search(keyword: str, limit: int = 8) -> list:
    """按名称模糊搜索内置目录（英文名 / 繁体中文名 / 简体名 / 人工别名）。

    目录本身已按热度排序；前缀匹配优先，其余按命中顺序。
    """
    q = _normalize(keyword)
    if not q:
        return []
    _load()
    matched = []
    for g in _catalog:
        rank = _match_rank(q, g)
        if rank is not None:
            matched.append((rank, g))
    matched.sort(key=lambda pair: pair[0])
    return [g for _, g in matched[:limit]]


def _normalize(text: str) -> str:
    """归一化：小写 + 去空白（中文搜索与英文共用一套逻辑）。"""
    return re.sub(r"\s+", "", (text or "").lower())


def _searchable_fields(game: dict) -> list[str]:
    """参与搜索的字段：英文标题、繁/简中文名（若有）、人工别名（若有）。"""
    fields = [game["t"]]
    for key in ("zh", "zhs"):
        value = game.get(key)
        if value:
            fields.append(value)
    fields.extend(game.get("zs") or [])
    return fields


def _match_rank(q: str, game: dict) -> int | None:
    """返回命中优先级：0=前缀命中，1=包含命中，None=未命中。

    中文短名（别名/简称）还允许反向包含——输入「耀西与不可思议图鉴」
    能命中别名为「耀西」的游戏；英文标题不参与反向匹配，避免误伤。
    """
    best: int | None = None
    for field in _searchable_fields(game):
        f = _normalize(field)
        if not f:
            continue
        if q in f:
            rank = 0 if f.startswith(q) else 1
            best = rank if best is None else min(best, rank)
        elif f in q and len(f) >= 2 and CJK_RE.search(f):
            best = 1 if best is None else min(best, 1)
    return best


def clean_game_desc(text: str) -> str:
    """去除介绍里的 HTML 标签与多余空白。"""
    return re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub(" ", text or ""))).strip()


def resolve_cover(game_id: str) -> bytes | None:
    """解析游戏封面：内置资源 → 本地缓存 → 在线下载（成功后缓存）。"""
    if not game_id:
        return None
    filename = f"{game_id}.jpg"
    for directory in (BUNDLED_COVERS_DIR, COVER_CACHE_DIR):
        path = directory / filename
        if path.exists():
            return path.read_bytes()

    game = get(game_id)
    if not game or not game.get("c"):
        return None
    try:
        req = urllib.request.Request(game["c"], headers={"User-Agent": _UA, "Accept": "image/*"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read()
    except Exception:  # noqa: BLE001 - 离线/网络失败时优雅降级
        return None

    try:
        COVER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (COVER_CACHE_DIR / filename).write_bytes(data)
    except OSError:
        # 表格与联想可能并发下载同一封面，Windows 下并发写同一文件会报错；
        # 缓存写失败只影响下次离线命中，不影响本次返回
        pass
    return data
