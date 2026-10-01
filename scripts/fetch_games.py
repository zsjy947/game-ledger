"""从 Nintendo eShop（欧洲区官方搜索接口）抓取 Switch 游戏目录，生成内置游戏库。

产出（均可由 --skip-* 控制）：
- game_ledger/assets/games.json   游戏目录（唯一数据源：服务端封面解析、
                                           桌面前端经 /api/games/catalog 加载）
- game_ledger/static/games.js     同数据的 JS 形式（仅安卓分支契约：
                                           android/prepare_assets.py 复制进 APK；
                                           桌面端已不使用、打包时也不再携带）
- game_ledger/assets/covers/<id>.jpg  热门游戏封面缩略图（本地化，离线可用）

数据来源：
- 目录：任天堂欧洲官网 eShop 搜索接口（Solr），字段含英文介绍与官方方形盒装封面；
  application_id_s（十六进制 Title ID）跨区通用，是跨区映射的枢纽。
- 中文名：blawar/titledb 仓库的 HK.zh.json（港服目录镜像，MIT 许可，仅公开目录元数据）
  按 Title ID 映射，为每条记录补充繁体中文名 zh / 简体化名 zhs（OpenCC t2s + 官方译名修正）。
  港服名为英文时，尝试从繁体介绍开头的《官方译名》提取。需联网一次，失败时跳过中文化。
- 搜索别名：scripts/zh_aliases.py 中人工维护的常用译名（键为欧服 NSUID）。

其余封面在应用运行时按需下载并缓存到 data/covers/。

用法：
    python scripts/fetch_games.py                # 全量目录 + 中文接入 + 前 400 个热门封面
    python scripts/fetch_games.py --covers 200   # 自定义封面数量
    python scripts/fetch_games.py --skip-covers  # 只更新目录
    python scripts/fetch_games.py --refresh-zh   # 强制重新下载港服中文数据
仅开发时运行，应用本身不需要联网即可使用内置游戏库（封面按需缓存除外）。
"""

import argparse
import html
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = PROJECT_ROOT / "game_ledger" / "assets"
STATIC_DIR = PROJECT_ROOT / "game_ledger" / "static"
COVERS_DIR = ASSETS_DIR / "covers"
CACHE_DIR = Path(__file__).resolve().parent / ".cache"

SOLR_URL = "https://search.nintendo-europe.com/en/select"
FQ = "type:GAME AND system_type:nintendoswitch AND nsuid_txt:* AND image_url_sq_s:* AND date_from:[* TO NOW]"
PAGE_ROWS = 500
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) switch-price-tracker-fetch"

HK_TITLEDB_URL = "https://raw.githubusercontent.com/blawar/titledb/master/HK.zh.json"
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
BOOK_TITLE_RE = re.compile(r"《([^》]{2,40})》")

# 港台译名 → 大陆官方译名修正（OpenCC 只做字形转换，用词差异需此处纠正）
T2S_CORRECTIONS = {
    "萨尔达": "塞尔达",
    "玛利欧": "马力欧",
}


def http_get(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def solr_page(start: int, rows: int) -> dict:
    query = urllib.parse.urlencode(
        {
            "q": "*:*",
            "fq": FQ,
            "start": start,
            "rows": rows,
            "wt": "json",
            "indent": "off",
            "spellcheck": "false",
            "sort": "date_from desc, hits_i desc",
        }
    )
    data = json.loads(http_get(f"{SOLR_URL}?{query}").decode("utf-8", "ignore"))
    return data["response"]


TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def clean_text(text: str, limit: int = 900) -> str:
    text = html.unescape(TAG_RE.sub(" ", text or ""))
    text = WS_RE.sub(" ", text).strip()
    return text[:limit].rstrip()


def to_record(doc: dict) -> dict | None:
    nsuids = doc.get("nsuid_txt") or []
    gid = nsuids[0] if nsuids else None
    if not gid:
        return None
    cover = doc.get("image_url_sq_s") or doc.get("image_url") or ""
    if not cover:
        return None
    description = clean_text(
        doc.get("product_catalog_description_s") or doc.get("excerpt") or ""
    )
    date = (doc.get("date_from") or "")[:10]
    players = doc.get("players_to")
    rec = {
        "i": gid,
        "t": (doc.get("title") or "").strip(),
        "d": description,
        "c": cover,
        "p": (doc.get("publisher") or "").strip(),
        "g": ", ".join(doc.get("pretty_game_categories_txt") or []),
        "dt": date,
        "h": int(doc.get("hits_i") or 0),
        "pl": players if isinstance(players, int) else None,
    }
    # application_id_s：十六进制 Title ID，跨区通用（港服中文映射的连接键）
    app_id = (doc.get("application_id_s") or "").strip().upper()
    if app_id:
        rec["tid"] = app_id
    return rec


def fetch_catalog() -> list[dict]:
    records: dict[str, dict] = {}
    start, total = 0, None
    while True:
        response = solr_page(start, PAGE_ROWS)
        total = response["numFound"]
        docs = response["docs"]
        for doc in docs:
            rec = to_record(doc)
            if rec and rec["t"] and rec["i"] not in records:
                records[rec["i"]] = rec
        print(f"  solr {start + len(docs)}/{total} -> kept {len(records)}", flush=True)
        if start + len(docs) >= total or not docs:
            break
        start += PAGE_ROWS
        time.sleep(0.05)
    return sorted(records.values(), key=lambda r: -r["h"])


# ── 港服中文数据接入 ─────────────────────────────────────────────────────────


def fetch_hk_catalog(path: Path) -> Path:
    """下载港服目录镜像到缓存文件（已存在且未强制刷新时直接复用）。"""
    if path.exists():
        print(f"  reuse cached {path.name} ({path.stat().st_size / 1024 / 1024:.0f} MB)")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    print("  downloading HK.zh.json (about 50 MB)...")
    req = urllib.request.Request(HK_TITLEDB_URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as resp, open(path, "wb") as f:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    return path


def load_hk_entries(path: Path) -> list[dict]:
    """解析港服目录为条目列表（跳过试玩版）。"""
    entries = json.loads(path.read_text(encoding="utf-8"))
    return [item for item in entries.values() if not item.get("isDemo")]


def extract_zh(hk: dict) -> str:
    """取繁体中文名：名称含中文优先；否则从繁体介绍开头的《官方译名》提取。"""
    name = (hk.get("name") or "").strip()
    if CJK_RE.search(name):
        return name
    for text in (hk.get("intro"), hk.get("description")):
        m = BOOK_TITLE_RE.search(text or "")
        if m and CJK_RE.search(m.group(1)):
            return m.group(1).strip()
    return ""


def extract_zh_intro(hk: dict) -> str:
    """取繁体中文介绍：港服长介绍优先，其次一句话简介。"""
    for key in ("description", "intro"):
        text = clean_text(hk.get(key) or "", limit=600)
        if text and CJK_RE.search(text):
            return text
    return ""


def to_simplified(text: str) -> str:
    """繁转简，并修正港台与大陆官方译名的用词差异。"""
    try:
        from opencc import OpenCC
    except ImportError:
        return text
    converted = OpenCC("t2s").convert(text)
    for src, dst in T2S_CORRECTIONS.items():
        converted = converted.replace(src, dst)
    return converted


def zh_aliases() -> dict[str, list[str]]:
    """人工维护的常用搜索别名（键为欧服 NSUID 或 Title ID），文件缺失时静默跳过。"""
    try:
        from zh_aliases import ALIASES

        return ALIASES
    except ImportError:
        return {}


def _pick_hk_entry(candidates: list[dict], eu_title: str) -> dict:
    """同一条 Title ID 在港服常有本体/同捆包/NS2 版多条记录，挑最合适的一条。

    优先级：NS2 版跟随欧服标题（欧服是 NS2 版就选港服 NS2 版）→
    非同捆（名称里不带「+」「組合」）→ 名称更短的。
    """
    eu_is_ns2 = "switch 2" in eu_title.lower()

    def score(hk: dict) -> float:
        name = hk.get("name") or ""
        name_l = name.lower()
        s = 0.0
        if eu_is_ns2 and "switch 2 edition" in name_l:
            s += 4
        if not eu_is_ns2 and "switch 2 edition" not in name_l:
            s += 2
        if "+" not in name:
            s += 2
        if "組合" not in name and "セット" not in name:
            s += 1
        return s - len(name) / 1000.0  # 同分时取更短的（接近本体名）

    return max(candidates, key=score)


def enrich_with_chinese(records: list[dict], hk_path: Path) -> None:
    """按 Title ID 为目录条目补充 zh（繁体）/ zhs（简体）/ zs（人工别名）。"""
    by_tid: dict[str, list[dict]] = {}
    for item in load_hk_entries(hk_path):
        tid = (item.get("id") or "").strip().upper()
        if tid:
            by_tid.setdefault(tid, []).append(item)
    aliases = zh_aliases()
    zh_n = zhs_n = zi_n = alias_n = 0
    for rec in records:
        # 先清掉旧字段再重建，保证重复运行（或别名表增删后）结果幂等
        for key in ("zh", "zhs", "zs", "zi"):
            rec.pop(key, None)
        tid = rec.get("tid", "")
        candidates = by_tid.get(tid, [])
        hk = _pick_hk_entry(candidates, rec["t"]) if candidates else None
        if hk:
            zh = extract_zh(hk)
            if zh:
                rec["zh"] = zh
                rec["zhs"] = to_simplified(zh)
                zh_n += 1
                if rec["zhs"] != zh:
                    zhs_n += 1
            zh_intro = extract_zh_intro(hk)
            if zh_intro:
                rec["zi"] = zh_intro
                zi_n += 1
        extra = aliases.get(rec["i"]) or aliases.get(tid)
        if extra:
            rec["zs"] = list(extra)
            alias_n += 1
    print(
        f"  zh names: {zh_n} (simplified differs: {zhs_n}), "
        f"zh intros: {zi_n}, curated aliases: {alias_n}"
    )


def save_catalog(records: list[dict]) -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    # 原子写：先写临时文件再替换，进程中断不会留下半个 games.json
    games_json = ASSETS_DIR / "games.json"
    tmp_path = games_json.with_suffix(".json.tmp")
    tmp_path.write_text(
        json.dumps(records, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    os.replace(tmp_path, games_json)
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    (STATIC_DIR / "games.js").write_text(
        "window.__GAMES__=" + json.dumps(records, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def fetch_covers(records: list[dict], count: int) -> None:
    COVERS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image
        import io

        have_pillow = True
    except ImportError:
        have_pillow = False

    done = 0
    for rec in records:
        if done >= count:
            break
        dest = COVERS_DIR / f"{rec['i']}.jpg"
        if dest.exists():
            done += 1
            continue
        try:
            data = http_get(rec["c"], timeout=25)
            if have_pillow:
                img = Image.open(io.BytesIO(data)).convert("RGB")
                img.thumbnail((256, 256))
                img.save(dest, "JPEG", quality=85)
            else:
                dest.write_bytes(data)
            done += 1
        except Exception as e:  # noqa: BLE001 - 单张失败不影响整体
            print(f"  cover fail {rec['i']} {rec['t'][:30]}: {e}", flush=True)
        time.sleep(0.08)
    print(f"covers localized: {done}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--covers", type=int, default=400, help="本地化热门封面数量")
    parser.add_argument("--skip-covers", action="store_true")
    parser.add_argument("--skip-zh", action="store_true", help="跳过港服中文名接入")
    parser.add_argument("--refresh-zh", action="store_true", help="强制重新下载港服中文数据")
    args = parser.parse_args()

    print("fetching catalog from Nintendo eShop (EU)...", flush=True)
    records = fetch_catalog()
    print(f"catalog records: {len(records)}")

    if not args.skip_zh:
        try:
            hk_path = fetch_hk_catalog(CACHE_DIR / "HK.zh.json")
            print("enriching with Chinese names (HK store)...", flush=True)
            enrich_with_chinese(records, hk_path)
        except Exception as e:  # noqa: BLE001 - 中文数据失败不影响目录本身
            print(f"  WARN: Chinese enrichment skipped: {e}", flush=True)

    save_catalog(records)
    size_mb = (ASSETS_DIR / "games.json").stat().st_size / 1024 / 1024
    print(f"games.json: {size_mb:.1f} MB")

    if not args.skip_covers:
        print(f"localizing top covers ({args.covers})...", flush=True)
        fetch_covers(records, args.covers)
    print("done.")


if __name__ == "__main__":
    sys.exit(main())
