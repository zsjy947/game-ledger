"""抓取 PlayStation Store 港服游戏目录并入内置游戏库。

数据源：PlayStation Store 官方 GraphQL 接口（web.np.playstation.com）。
港服「全部游戏」分类（PS5+PS4 概念目录）全量分页枚举，产出与 Switch 目录
同构的记录（i/t/zh/zhs/c/g），id 统一加 ``PS`` 前缀避免与 NSUID 冲突，
合并进 game_ledger/assets/games.json——桌面端 /api/games/catalog 与安卓端
games.js 自动同步，无需其他改动。

接口要点（2026-09 实测）：
- 端点 /api/graphql/v1/op 只接受服务端注册的持久化查询（哈希白名单），
  内联查询会被拒（"Query not whitelisted"）；哈希取自商店网页实际请求。
- 请求必须带 ``x-apollo-operation-name`` 头，否则被 CSRF 防护拦截。
- 港服名称为原生繁体中文；zhs 用 OpenCC t2s 转换；大陆常用译名差异
  （羊蹄山戰鬼→羊蹄山之魂等）人工维护在 CURATED_ALIASES。

用法：
    .venv\\Scripts\\python.exe scripts\\fetch_ps_games.py                  # 全量
    .venv\\Scripts\\python.exe scripts\\fetch_ps_games.py --max-pages 4    # 限量试跑
    .venv\\Scripts\\python.exe scripts\\fetch_ps_games.py --dry-run        # 只抓取不写库
    .venv\\Scripts\\python.exe scripts\\fetch_ps_games.py --fixture X.json # 离线解析
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from game_ledger.config import ASSETS_DIR, STATIC_DIR  # noqa: E402

# ── 数据源常量（哈希为商店页面实际使用的持久化查询签名）────────────────────
ENDPOINT = "https://web.np.playstation.com/api/graphql/v1/op"
# 港服「全部游戏」（PS5+PS4 概念目录，cat.gma.x_All_games）
CATEGORY_ID = "28c9c2b2-cecc-415c-9a08-482a605cb104"
CATEGORY_HASH = "9845afc0dbaab4965f6563fffc703f588c8e76792000e8610843b8d3ee9c4c09"
# universalSearch（验证/补充用）
SEARCH_HASH = "4df6284f982e57bec70f23c77e2c219dc792eb19af7fb3d3a81767aa3f1958aa"
PAGE_SIZE = 50
REQUEST_GAP = 0.4  # 对商店接口保持克制的请求间隔（秒）

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) game-ledger"
_ID_RE = re.compile(r"[0-9A-Za-z_-]")
MAX_ID_LEN = 60  # 预留 "PS" 前缀后仍在 64 内

# 封面 role 优先级（type=IMAGE）
COVER_ROLES = ("GAMEHUB_COVER_ART", "KEY_ART", "BACKGROUND", "BACKGROUND_LAYER_ART", "MASTER")

# 大陆常用译名 → 港服条目 ID（Concept id 或 Product npTitleId；用词/译名差异
# OpenCC 转不出来，如 羊蹄山戰鬼→羊蹄山之魂、God of War→战神）。
# 维护方式：在港服商店搜索确认条目 ID 后补充。
CURATED_ALIASES: dict[str, list[str]] = {
    # ── Product 形态（npTitleId 作键）──
    "PPSA26344_00": ["羊蹄山之魂", "羊蹄山"],              # 《羊蹄山戰鬼》Ghost of Yotei
    "PPSA08340_00": ["漫威蜘蛛侠2", "漫威蜘蛛侠"],          # Marvel's Spider-Man 2
    "PPSA01472_00": ["漫威蜘蛛侠"],                        # Marvel's Spider-Man Remastered
    "PPSA01419_00": ["漫威蜘蛛侠迈尔斯", "漫威蜘蛛侠"],     # Miles Morales
    "CUSA09893_00": ["漫威蜘蛛侠"],                        # Marvel's Spider-Man GOTY (PS4)
    "CUSA07413_00": ["战神"],                              # God of War (2018)
    "CUSA34394_00": ["战神：诸神黄昏", "战神"],             # God of War Ragnarök
    "PPSA07644_00": ["最后生还者", "美国末日"],             # The Last of Us Part I
    "PPSA15512_00": ["最后生还者2", "最后生还者"],          # The Last of Us Part II Remaster
    "CUSA03023_00": ["血源诅咒"],                          # Bloodborne (Old Hunters Ed.)
    "CUSA01363_00": ["血源诅咒"],                          # Bloodborne (PS Hits)
    "CUSA00912_00": ["神秘海域4", "神秘海域"],              # UNCHARTED 4
    "PPSA05686_00": ["神秘海域盗贼传奇合辑", "神秘海域"],    # UNCHARTED 盜賊傳奇合輯
    # ── Concept 形态（目录枚举收录的英文名条目）──
    "10002456": ["漫威蜘蛛侠2", "漫威蜘蛛侠"],              # Marvel's Spider-Man 2
    "10000762": ["漫威蜘蛛侠"],                            # Marvel's Spider-Man
    "10000649": ["漫威蜘蛛侠迈尔斯", "漫威蜘蛛侠"],         # Miles Morales
    "227770": ["战神"],                                    # God of War
    "10001850": ["战神：诸神黄昏", "战神"],                 # God of War Ragnarök
    "10002694": ["最后生还者", "美国末日"],                 # The Last of Us Part I
    "230079": ["最后生还者2", "最后生还者"],                # The Last of Us Part II
    "235227": ["对马岛之魂"],                              # Ghost of Tsushima
    "200520": ["血源诅咒"],                                # Bloodborne
    "10000956": ["GT赛车7", "跑车浪漫旅7", "GT7"],          # Gran Turismo 7
    "221727": ["地平线零之曙光", "地平线"],                 # Horizon Zero Dawn
    "10000886": ["地平线西之绝境", "地平线"],               # Horizon Forbidden West
    "10002684": ["宇宙机器人"],                            # ASTRO BOT
    "10000669": ["瑞奇与叮当时空跳转", "瑞奇与叮当"],       # Ratchet & Clank: Rift Apart
    "214653": ["瑞奇与叮当"],                              # Ratchet & Clank
    "205354": ["神秘海域盗贼传奇合辑", "神秘海域"],          # UNCHARTED Legacy of Thieves
}


# ── 解析层（纯函数，fixture 可测）──────────────────────────────────────────

def _clean_id(raw: str) -> str:
    """概念 ID → 合法封面 ID：只留 [0-9A-Za-z_-]，截断到上限。"""
    cleaned = "".join(_ID_RE.findall(raw or ""))
    return cleaned[:MAX_ID_LEN]


def pick_cover(media: list | None) -> str:
    """media 列表 → 封面 URL（按 COVER_ROLES 优先级取第一张 IMAGE）。"""
    best = ""
    best_rank = len(COVER_ROLES)
    for item in media or []:
        if not isinstance(item, dict) or item.get("type") != "IMAGE":
            continue
        url = item.get("url") or ""
        if not url:
            continue
        try:
            rank = COVER_ROLES.index(item.get("role"))
        except ValueError:
            continue
        if rank < best_rank:
            best, best_rank = url, rank
    return best


def parse_concepts(payload: dict) -> list[dict]:
    """categoryGridRetrieve 响应 → 游戏库记录列表（容忍坏条目）。"""
    grid = (payload.get("data") or {}).get("categoryGridRetrieve") or {}
    concepts = grid.get("concepts") or []

    records: list[dict] = []
    for item in concepts:
        if not isinstance(item, dict):
            continue
        cid = _clean_id(str(item.get("id") or ""))
        name = (item.get("name") or "").strip()
        if not cid or not name:
            continue
        records.append(
            {
                "i": "PS" + cid,
                "t": name,  # 港服名即繁体中文
                "zh": name,
                "c": pick_cover(item.get("media")),
            }
        )
    return records


def to_simplified(text: str) -> str:
    """繁体 → 简体（OpenCC t2s；缺依赖时原样返回）。"""
    try:
        from opencc import OpenCC
    except ImportError:
        return text
    return OpenCC("t2s").convert(text or "")


def apply_aliases(records: list[dict]) -> int:
    """补 zhs（OpenCC 简体化名）与人工别名 zs；返回有条别名的条数。"""
    aliased = 0
    for rec in records:
        cid = rec["i"][2:]
        rec["zhs"] = to_simplified(rec["zh"])
        extra = CURATED_ALIASES.get(cid)
        if extra:
            rec["zs"] = list(extra)
            aliased += 1
    return aliased


# ── 网络层 ─────────────────────────────────────────────────────────────────

def _get(operation: str, variables: dict, sha: str, timeout: int = 25, retries: int = 4) -> dict:
    params = {
        "operationName": operation,
        "variables": json.dumps(variables, separators=(",", ":")),
        "extensions": json.dumps(
            {"persistedQuery": {"version": 1, "sha256Hash": sha}}, separators=(",", ":")
        ),
    }
    url = ENDPOINT + "?" + urllib.parse.urlencode(params)
    last_error: Exception | None = None
    for attempt in range(retries):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": _UA,
                "Accept": "application/json",
                # 缺少此头会被 Apollo 的 CSRF 防护以 400 拒绝
                "x-apollo-operation-name": operation,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code < 500:
                raise  # 4xx 是请求问题，重试无意义
            last_error = e
        except (urllib.error.URLError, OSError) as e:
            # 网络抖动（SSL 握手超时等）：指数退避后重试
            last_error = e
        time.sleep(1.5 * (attempt + 1))
    raise last_error if last_error else RuntimeError("request failed")


def search(term: str, limit: int = 5) -> list[dict]:
    """universalSearch 验证用：返回港服搜索结果（Concept/Product 混合）。"""
    payload = _get(
        "getSearchResults",
        {
            "countryCode": "HK",
            "languageCode": "ch",
            "searchTerm": term,
            "nextCursor": "",
            "pageOffset": 0,
            "pageSize": limit,
        },
        SEARCH_HASH,
    )
    return (payload.get("data") or {}).get("universalSearch", {}).get("results") or []


# 视为完整游戏的商品分类（其余为 DLC/升级包/体验版等，不入库）
FULL_GAME_CLASSIFICATIONS = ("正式版遊戲", "高級版")
# 名末括号内全是语言标注时剥掉（"宇宙機器人 (簡體中文, 韓文…)" → "宇宙機器人"）
_LANG_SUFFIX_RE = re.compile(r"\s*[（(][^()]*[語文][^()]*[)）]\s*")


def _clean_name(name: str) -> str:
    prev = None
    while prev != name:
        prev = name
        name = _LANG_SUFFIX_RE.sub("", name, count=1)
    return name.strip()


def _product_np_title_id(product_id: str) -> str:
    """产品 ID → 游戏 npTitleId（HP9000-CUSA07413_00-XXX → CUSA07413_00）。"""
    parts = (product_id or "").split("-")
    return parts[1] if len(parts) > 2 else product_id


def parse_search_results(payload: dict) -> tuple[list[dict], str, int]:
    """getSearchResults 响应 → (记录, next 游标, 总数)。

    Concept（游戏级）全收；Product 只收完整游戏（正式版/高級版），按
    npTitleId 去重（同游戏多版本取正式版），且与 Concept 同名时让位。
    """
    us = (payload.get("data") or {}).get("universalSearch") or {}
    concept_records: list[dict] = []
    concept_names: set[str] = set()
    products: dict[str, tuple[str, dict]] = {}  # npTitleId -> (分类, 记录)
    for item in us.get("results") or []:
        if not isinstance(item, dict):
            continue
        typename = item.get("__typename")
        cid = _clean_id(str(item.get("id") or ""))
        name = _clean_name((item.get("name") or "").strip())
        if not cid or not name:
            continue
        if typename == "Concept":
            concept_names.add(name.replace("《", "").replace("》", ""))
            concept_records.append(
                {
                    "i": "PS" + cid,
                    "t": name,
                    "zh": name,
                    "c": pick_cover(item.get("media")),
                }
            )
        elif typename == "Product":
            if item.get("localizedStoreDisplayClassification") not in FULL_GAME_CLASSIFICATIONS:
                continue
            np_title = _product_np_title_id(item.get("id") or "")
            if not np_title:
                continue
            classification = item["localizedStoreDisplayClassification"]
            kept = products.get(np_title)
            # 同 npTitleId 多版本：正式版优先于高級版；同级先到先得
            if kept is None or (
                kept[0] == "高級版" and classification == "正式版遊戲"
            ):
                products[np_title] = (
                    classification,
                    {
                        "i": "PS" + _clean_id(np_title),
                        "t": name,
                        "zh": name,
                        "c": pick_cover(item.get("media")),
                    },
                )

    records = concept_records
    for _np_title, (_classification, rec) in products.items():
        if rec["t"].replace("《", "").replace("》", "") in concept_names:
            continue  # 同名 Concept 已收录（更干净的游戏级条目）
        records.append(rec)
    return records, (us.get("next") or ""), (us.get("pageInfo") or {}).get("totalCount") or 0


def sweep_terms(terms: list[str], pages_per_term: int, size: int = 50) -> list[dict]:
    """按术语扫掠 universalSearch，深分页枚举港服目录（Concept 去重）。

    拉丁字母命中所有拉丁名游戏；单个 CJK 字符命中名称含该字的游戏
    （商店搜索为子串匹配），字符表取自现有中文库的用字，保证常用字全覆盖。
    """
    records: dict[str, dict] = {}
    failed_terms: list[str] = []
    for n, term in enumerate(terms, 1):
        cursor = ""
        offset = 0
        got = 0
        try:
            for _page in range(pages_per_term):
                payload = _get(
                    "getSearchResults",
                    {
                        "countryCode": "HK",
                        "languageCode": "ch",
                        "searchTerm": term,
                        "nextCursor": cursor,
                        "pageOffset": offset,
                        "pageSize": size,
                    },
                    SEARCH_HASH,
                )
                page, cursor, total = parse_search_results(payload)
                fresh = 0
                for rec in page:
                    if rec["i"] not in records:
                        records[rec["i"]] = rec
                        fresh += 1
                got += len(page)
                if not page or not cursor or (total and got >= total):
                    break
                offset += size
                time.sleep(REQUEST_GAP / 2)
        except Exception as e:  # noqa: BLE001 - 单术语失败跳过，不报废整体
            failed_terms.append(term)
            print(f"    术语 {term!r} 失败跳过: {str(e)[:80]}")
        if n % 25 == 0 or n == len(terms):
            print(f"  [{n}/{len(terms)}] 术语 {term!r} → 累计去重 {len(records)}")
        time.sleep(REQUEST_GAP / 2)
    if failed_terms:
        print(f"  完成（{len(failed_terms)} 个术语失败: {' '.join(map(repr, failed_terms[:8]))}…）")
    return list(records.values())


def sweep_charset() -> list[str]:
    """从现有中文库（Switch/PS 目录的中文字段）提取 CJK 用字作为扫掠字母表。"""
    chars: set[str] = set()
    games_json = ASSETS_DIR / "games.json"
    if games_json.exists():
        for g in json.loads(games_json.read_text(encoding="utf-8")):
            for key in ("t", "zh", "zhs"):
                for ch in str(g.get(key) or ""):
                    if "\u4e00" <= ch <= "\u9fff":
                        chars.add(ch)
    return sorted(chars)


def fetch_catalog(max_pages: int) -> tuple[list[dict], int]:
    """分页枚举港服「全部游戏」概念目录（注意：名称为商店默认语言）。"""
    records: list[dict] = []
    seen: set[str] = set()
    total = 0
    offset = 0
    for _page in range(max_pages):
        payload = _get(
            "categoryGridRetrieve",
            {"id": CATEGORY_ID, "pageArgs": {"size": PAGE_SIZE, "offset": offset}},
            CATEGORY_HASH,
        )
        grid = (payload.get("data") or {}).get("categoryGridRetrieve") or {}
        info = grid.get("pageInfo") or {}
        total = info.get("totalCount") or total

        page = parse_concepts(payload)
        fresh = [r for r in page if r["i"] not in seen]
        for rec in fresh:
            seen.add(rec["i"])
        records.extend(fresh)
        print(f"  offset={offset}: +{len(fresh)} (累计 {len(records)}/{total})")

        if not page or info.get("isLast") or len(records) >= total:
            break
        offset += PAGE_SIZE
        time.sleep(REQUEST_GAP)
    return records, total


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
    # 原子写：先写临时文件再替换，进程中断不会留下半个 games.json
    games_json.parent.mkdir(parents=True, exist_ok=True)
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
    parser.add_argument(
        "--sweep", action="store_true",
        help="用 universalSearch 术语扫掠抓取（繁中名，推荐）；默认分类目录抓取为英文名",
    )
    parser.add_argument("--max-pages", type=int, default=260, help="分类目录模式：最多抓取页数")
    parser.add_argument(
        "--pages-per-term", type=int, default=8, help="扫掠模式：每个术语最多分页数"
    )
    parser.add_argument("--fixture", type=Path, help="离线模式：解析本地 JSON 而不联网")
    parser.add_argument(
        "--games-json",
        type=Path,
        default=ASSETS_DIR / "games.json",
        help="目标 games.json（测试时可指向临时文件）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只抓取打印，不写库")
    args = parser.parse_args()

    if args.fixture:
        print(f"离线模式：解析 {args.fixture}")
        records = parse_concepts(json.loads(args.fixture.read_text(encoding="utf-8")))
    elif args.sweep:
        terms = [str(d) for d in range(10)] + [chr(c) for c in range(ord("a"), ord("z") + 1)]
        chars = sweep_charset()
        print(f"术语扫掠：36 个拉丁术语 + {len(chars)} 个 CJK 字符（每术语至多 {args.pages_per_term} 页）…")
        records = sweep_terms(terms + chars, args.pages_per_term)
        if not records:
            print("未取得任何记录，未写库。")
            return
    else:
        print(f"抓取 PlayStation Store 港服全部游戏目录（每页 {PAGE_SIZE} 条，至多 {args.max_pages} 页）…")
        records, total = fetch_catalog(args.max_pages)
        if not records:
            print("未取得任何记录，未写库。")
            return

    aliased = apply_aliases(records)
    print(f"解析出 {len(records)} 条 PS 记录（人工别名 {aliased} 条）")
    for rec in records[:5]:
        print(f"  {rec['i']}  {rec['t']}  封面: {'有' if rec['c'] else '无'}")

    if args.dry_run:
        return

    total, written = merge_into_catalog(records, args.games_json)
    print(f"合并完成：写入 {written} 条 PS 记录，目录总数 {total} → {args.games_json}")
    if args.games_json.resolve() == (ASSETS_DIR / "games.json").resolve():
        write_games_js(args.games_json)
        print("已同步 static/games.js；安卓重打包（prepare_assets）自动生效。")


if __name__ == "__main__":
    main()
