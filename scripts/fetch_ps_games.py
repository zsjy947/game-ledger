"""抓取 PlayStation Store 游戏目录（港服中文）并入内置游戏库。

产出与 Switch 目录同构的记录（i/t/d/c/p/dt/g/pl/zh），id 统一加 ``PS``
前缀避免与 NSUID 数值冲突，合并进 game_ledger/assets/games.json——
安卓端 games.js 与桌面端 /api/games/catalog 自动同步，无需其他改动。

数据源：PlayStation Store GraphQL 接口（web.np.playstation.com）。
商店接口随改版变动：首次使用前请用浏览器 DevTools 确认 ENDPOINT 与
CATEGORY_ID 仍有效（见下文常量注释）；解析层与网络层分离，可用
``--fixture`` 离线验证。

用法：
    .venv\\Scripts\\python.exe scripts\\fetch_ps_games.py --limit 100
    .venv\\Scripts\\python.exe scripts\\fetch_ps_games.py --platform ps4
    .venv\\Scripts\\python.exe scripts\\fetch_ps_games.py --fixture tests/fixtures/ps_store_sample.json
    .venv\\Scripts\\python.exe scripts\\fetch_ps_games.py --dry-run   # 只解析不写库
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from game_ledger.config import ASSETS_DIR, STATIC_DIR  # noqa: E402

# ── 数据源常量（接口改版时仅需调整这里）────────────────────────────────────
ENDPOINT = "https://web.np.playstation.com/api/graphql/v1/op"
# 港服（zh-Hant-HK）「游戏」分类网格的 category id；以 DevTools 抓包为准。
CATEGORY_IDS = {
    "ps5": "d3a8b1e6-9eb4-4d16-a33d-e0f5cfe9c3a4",
    "ps4": "4492c0b1-7e0c-4dd8-a54e-e5b5c8b6b9d4",
}
PAGE_SIZE = 30
REQUEST_GAP = 1.0  # 抓取间隔（秒），对商店接口保持克制

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) game-ledger"
# 封面 ID 与桌面端同一约束（routes.GAME_ID_RE）
_ID_RE = re.compile(r"[0-9A-Za-z_-]")
MAX_ID_LEN = 60  # 预留 "PS" 前缀后仍在 64 内

GRAPHQL_QUERY = """query categoryGridRetrieve($id: ID!, $pageSize: Int!, $offsetBy: Int!) {
  categoryGridRetrieve(id: $id) {
    products(pageSize: $pageSize, offsetBy: $offsetBy) {
      products { id name shortName description providerName releaseDate
                 genres { name } platforms keyArt { url } }
      total
    }
  }
}"""


# ── 解析层（纯函数，fixture 可测）──────────────────────────────────────────

def _clean_id(raw: str) -> str:
    """商店产品 ID → 合法封面 ID：只留 [0-9A-Za-z_-]，截断到上限。"""
    cleaned = "".join(_ID_RE.findall(raw or ""))
    return cleaned[:MAX_ID_LEN]


def platform_tag(platforms: list | None) -> str:
    """平台列表 → 单一标签：有 PS5 标 PS5，否则有 PS4 标 PS4。

    接口偶发在列表里混入 null 元素，先过滤掉非字符串项再判断。
    """
    platforms = [p for p in (platforms or []) if isinstance(p, str)]
    if "PS5" in platforms:
        return "PS5"
    if "PS4" in platforms:
        return "PS4"
    return "PS4" if platforms else ""


def parse_products(payload: dict) -> list[dict]:
    """GraphQL categoryGridRetrieve 响应 → 游戏库记录列表。

    容忍结构变动：任一产品字段缺失时跳过该条而不是整体失败。
    """
    try:
        products = payload["data"]["categoryGridRetrieve"]["products"]["products"]
    except (KeyError, TypeError):
        return []

    records: list[dict] = []
    for item in products:
        if not isinstance(item, dict):
            continue  # 接口偶发返回 null 条目，跳过而不是整体失败
        cid = _clean_id(item.get("id") or "")
        name = (item.get("name") or item.get("shortName") or "").strip()
        if not cid or not name:
            continue
        cover = ""
        for art in item.get("keyArt") or []:
            url = (art or {}).get("url") or ""
            if url:
                cover = url
                break
        rec = {
            "i": "PS" + cid,
            "t": name,               # 港服目录名即繁体中文
            "zh": name,
            "d": (item.get("description") or "").strip(),
            "p": item.get("providerName") or "",
            "dt": (item.get("releaseDate") or "")[:10],
            "c": cover,
            "g": "、".join(
                (g or {}).get("name", "")
                for g in item.get("genres") or []
                if (g or {}).get("name")
            ),
        }
        pl = platform_tag(item.get("platforms"))
        if pl:
            rec["pl"] = pl
        records.append(rec)
    return records


# ── 网络层 ─────────────────────────────────────────────────────────────────

def fetch_page(platform: str, offset: int, timeout: int = 20) -> dict:
    """抓一页目录（POST GraphQL）。失败抛 urllib 异常，由调用方决定终止。"""
    body = json.dumps(
        {
            "operationName": "categoryGridRetrieve",
            "query": GRAPHQL_QUERY,
            "variables": {
                "id": CATEGORY_IDS[platform],
                "pageSize": PAGE_SIZE,
                "offsetBy": offset,
            },
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT,
        data=body,
        headers={
            "User-Agent": _UA,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Accept-Language": "zh-Hant-HK,zh;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_platform(platform: str, limit: int) -> list[dict]:
    """分页抓取某平台目录，最多 limit 条。"""
    records: list[dict] = []
    offset = 0
    while len(records) < limit:
        try:
            payload = fetch_page(platform, offset)
        except (urllib.error.URLError, OSError, ValueError) as e:
            print(f"  抓取失败（{platform} offset={offset}）：{e}")
            print("  商店接口可能已改版，请按脚本头部注释用 DevTools 核对常量。")
            break
        page = parse_products(payload)
        if not page:
            break
        records.extend(page[: limit - len(records)])
        print(f"  {platform}: {len(records)} fetched")
        offset += PAGE_SIZE
        time.sleep(REQUEST_GAP)
    return records


# ── 合并层 ─────────────────────────────────────────────────────────────────

def merge_into_catalog(ps_records: list[dict], games_json: Path) -> tuple[int, int]:
    """把 PS 记录并入 games.json：保留 Switch 条目与排序，PS 段可重入。

    返回 (合并后总数, 本次写入 PS 条数)。同 id 视为同一条（重新抓取即更新）。
    """
    existing = []
    if games_json.exists():
        existing = json.loads(games_json.read_text(encoding="utf-8"))
    ns_records = [g for g in existing if not str(g.get("i", "")).startswith("PS")]
    ps_merged = [g for g in existing if str(g.get("i", "")).startswith("PS")]
    ps_index = {g["i"]: n for n, g in enumerate(ps_merged)}
    written = 0
    for rec in ps_records:
        if rec["i"] in ps_index:
            ps_merged[ps_index[rec["i"]]] = rec
        else:
            ps_index[rec["i"]] = len(ps_merged)
            ps_merged.append(rec)
        written += 1

    merged = ns_records + ps_merged
    games_json.parent.mkdir(parents=True, exist_ok=True)
    # 原子写：先写临时文件再替换，进程中断不会留下半个 games.json
    tmp_path = games_json.with_suffix(".json.tmp")
    tmp_path.write_text(
        json.dumps(merged, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    os.replace(tmp_path, games_json)
    return len(merged), written


def write_games_js(games_json: Path) -> None:
    """同步安卓契约文件 static/games.js（与 fetch_games.py 相同格式）。"""
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    (STATIC_DIR / "games.js").write_text(
        "window.__GAMES__=" + games_json.read_text(encoding="utf-8"), encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--platform", choices=["ps5", "ps4"], default="ps5")
    parser.add_argument("--limit", type=int, default=100, help="最多抓取条数")
    parser.add_argument("--fixture", type=Path, help="离线模式：解析本地 JSON 而不联网")
    parser.add_argument(
        "--games-json", type=Path, default=ASSETS_DIR / "games.json",
        help="目标 games.json（测试时可指向临时文件）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只解析，不写任何文件")
    args = parser.parse_args()

    if args.fixture:
        print(f"离线模式：解析 {args.fixture}")
        records = parse_products(json.loads(args.fixture.read_text(encoding="utf-8")))
        print(f"解析出 {len(records)} 条")
        for rec in records[:5]:
            print(f"  {rec['i']}  {rec['t']}  [{rec.get('pl', '')}]  {rec['p']}")
        if args.dry_run or not records:
            return
    else:
        print(f"抓取 PlayStation Store（港服 {args.platform}，上限 {args.limit} 条）…")
        records = fetch_platform(args.platform, args.limit)
        if not records:
            print("未取得任何记录，未写库。")
            return

    total, written = merge_into_catalog(records, args.games_json)
    print(f"合并完成：写入 {written} 条 PS 记录，目录总数 {total} → {args.games_json}")
    # resolve() 后比较：测试或命令行传入等价路径（相对/绝对）也能识别为主目录
    primary_catalog = ASSETS_DIR / "games.json"
    if not args.dry_run and args.games_json.resolve() == primary_catalog.resolve():
        write_games_js(args.games_json)
        print("已同步 static/games.js；安卓重打包（prepare_assets）自动生效。")


if __name__ == "__main__":
    main()
