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
    """按名称模糊搜索内置目录，目录本身已按热度排序。"""
    q = (keyword or "").strip().lower()
    if not q:
        return []
    _load()
    matched = [g for g in _catalog if q in g["t"].lower()]
    return matched[:limit]


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

    COVER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (COVER_CACHE_DIR / filename).write_bytes(data)
    return data
