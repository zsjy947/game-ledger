"""从 Nintendo eShop（欧洲区官方搜索接口）抓取 Switch 游戏目录，生成内置游戏库。

产出（均可由 --skip-* 控制）：
- switch_price_tracker/assets/games.json   游戏目录（服务端封面解析用）
- switch_price_tracker/static/games.js     同数据的 JS 形式（前端/安卓内置搜索用）
- switch_price_tracker/assets/covers/<id>.jpg  热门游戏封面缩略图（本地化，离线可用）

数据来源：任天堂欧洲官网 eShop 搜索接口（Solr），字段含英文介绍与官方方形盒装封面。
其余封面在应用运行时按需下载并缓存到 data/covers/。

用法：
    python scripts/fetch_games.py                # 全量目录 + 前 400 个热门封面
    python scripts/fetch_games.py --covers 200   # 自定义封面数量
    python scripts/fetch_games.py --skip-covers  # 只更新目录
仅开发时运行，应用本身不需要联网即可使用内置游戏库（封面按需缓存除外）。
"""

import argparse
import html
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = PROJECT_ROOT / "switch_price_tracker" / "assets"
STATIC_DIR = PROJECT_ROOT / "switch_price_tracker" / "static"
COVERS_DIR = ASSETS_DIR / "covers"

SOLR_URL = "https://search.nintendo-europe.com/en/select"
FQ = "type:GAME AND system_type:nintendoswitch AND nsuid_txt:* AND image_url_sq_s:* AND date_from:[* TO NOW]"
PAGE_ROWS = 500
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) switch-price-tracker-fetch"


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
    return {
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


def save_catalog(records: list[dict]) -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    (ASSETS_DIR / "games.json").write_text(
        json.dumps(records, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
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
    args = parser.parse_args()

    print("fetching catalog from Nintendo eShop (EU)...", flush=True)
    records = fetch_catalog()
    print(f"catalog records: {len(records)}")
    save_catalog(records)
    size_mb = (ASSETS_DIR / "games.json").stat().st_size / 1024 / 1024
    print(f"games.json: {size_mb:.1f} MB")

    if not args.skip_covers:
        print(f"localizing top covers ({args.covers})...", flush=True)
        fetch_covers(records, args.covers)
    print("done.")


if __name__ == "__main__":
    sys.exit(main())
