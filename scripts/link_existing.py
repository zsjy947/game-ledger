"""存量反查：为未关联游戏库的卡带记录自动匹配内置游戏（补封面与介绍）。

背景：游戏库支持中文搜索之前的存量记录多为手输中文名，无法按英文名关联。
本脚本用「记录名 ↔ 中文名/简体化名/别名」双向包含匹配打分，为每条未关联
记录挑选最佳游戏；高置信度自动关联，模糊的列出候选供人工确认。

安全设计：
- 运行前自动把 data/prices.db 备份为 prices.backup-manual-<日期>.db；
- 默认 dry-run 只打印结果，加 --apply 才真正写库；
- 已关联（cover 非空）的记录不动；已有自定义介绍（intro 非空）时保留原文。

用法：
    python scripts/link_existing.py            # 预览匹配结果
    python scripts/link_existing.py --apply    # 实际写库
"""

import argparse
import re
import shutil
import sys
import unicodedata
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from switch_price_tracker import database, games  # noqa: E402

# 归一化：小写 + NFKC（全角４→4）+ 去空白与常见中英文标点
# （塞尔达传说 王国之泪 → 塞尔达传说王国之泪，皮克敏４ → 皮克敏4）
# ™/®/© 必须在 NFKC 之前删除：NFKC 会把它们展开成 "tm"/"rc"，
# 破坏「Nintendo Switch™ 2 Edition」→ switch2edition 的判断
_TRADEMARK_RE = re.compile(r"[™®©]")
_NOISE_RE = re.compile(r"[\s，。、：:；！!？?·（）()\[\]【】・~～\-—_+&,'’″\".．*™®!]+")


def norm(text: str) -> str:
    text = _TRADEMARK_RE.sub("", text or "")
    return _NOISE_RE.sub("", unicodedata.normalize("NFKC", text).lower())


def _game_names(game: dict) -> list[str]:
    """参与匹配的中文名（zh/zhs/别名），用于与用户手输中文名比对。"""
    names = []
    for key in ("zh", "zhs"):
        if game.get(key):
            names.append(game[key])
    names.extend(game.get("zs") or [])
    return names


def score_match(record: dict, game: dict) -> float:
    """记录名与游戏的匹配置信度（0-100+，越高越可信）。"""
    rn = norm(record["name"])
    if len(rn) < 2:
        return 0.0
    best = 0.0
    for name in _game_names(game):
        fn = norm(name)
        if not fn:
            continue
        if rn == fn:
            score = 100.0
        elif len(rn) >= 3 and rn in fn:
            score = 80.0 + 10.0 * len(rn) / len(fn)  # 记录名覆盖率越高越好
        elif len(fn) >= 2 and fn in rn:
            score = 78.0 + 10.0 * len(fn) / len(rn)  # 短别名（耀西/p3r）命中长记录名
        else:
            continue
        best = max(best, score)
    if not best:
        # 英文兜底：记录名本身像英文名时与英文标题比对。
        # 反向包含（短英文标题 ⊆ 长记录名）要求标题至少 5 字符，
        # 避免 "P.3" 之类的短名误伤
        tn = norm(game["t"])
        if len(rn) >= 4:
            if rn == tn:
                best = 100.0
            elif rn in tn:
                best = 80.0 + 10.0 * len(rn) / len(tn)
            elif len(tn) >= 5 and tn in rn:
                best = 80.0 + 10.0 * len(tn) / len(rn)
    if best:
        best += min(game.get("h", 0) / 10000.0, 3.0)  # 热度微调，同分时偏向热门游戏
        if record["category"] == "NS2":
            if "switch2edition" in norm(game["t"]):
                best += 8.0
        elif "switch2edition" in norm(game["t"]):
            best -= 15.0  # NS 记录优先匹配非 NS2 版
    return best


def best_candidates(record: dict, catalog: list[dict], top: int = 3) -> list[tuple[float, dict]]:
    scored = []
    for game in catalog:
        s = score_match(record, game)
        if s >= 60:
            scored.append((s, game))
    scored.sort(key=lambda pair: (-pair[0], -pair[1].get("h", 0)))
    return scored[:top]


AUTO_SCORE = 80.0   # 达到此分且领先明显时自动关联
AUTO_MARGIN = 8.0   # 首名需领先第二名多少分
EXACT_SCORE = 95.0  # 精确命中无需领先幅度


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="实际写库（默认只预览）")
    args = parser.parse_args()

    catalog = games.all_games()
    records = database.get_all()
    todo = [r for r in records if not r["cover"]]
    print(f"共 {len(records)} 条记录，其中 {len(todo)} 条未关联游戏库\n")
    if not todo:
        return 0

    if args.apply:
        db_path = database.DB_PATH
        backup = db_path.with_name(f"prices.backup-manual-{date.today():%Y%m%d}.db")
        shutil.copy2(db_path, backup)
        print(f"已备份：{backup.name}\n")

    linked, ambiguous, unmatched = 0, [], []
    for record in todo:
        cands = best_candidates(record, catalog)
        if not cands:
            unmatched.append(record)
            print(f"✗ 未匹配  {record['name']}（{record['category']}）")
            continue
        top_score, top_game = cands[0]
        second_score = cands[1][0] if len(cands) > 1 else 0.0
        confident = top_score >= EXACT_SCORE or (
            top_score >= AUTO_SCORE and top_score - second_score >= AUTO_MARGIN
        )
        display = top_game.get("zhs") or top_game.get("zh") or top_game["t"]
        if confident and args.apply:
            intro = record["intro"] or top_game.get("d", "")
            database.update(
                record["id"], record["category"], record["name"], record["price"],
                record["notes"], record["source"], top_game["i"], intro,
            )
            linked += 1
            print(f"✓ 已关联  {record['name']}（{record['category']}） → {display} [{top_game['i']}] {top_score:.0f}分")
        elif confident:
            print(f"✓ 可关联  {record['name']}（{record['category']}） → {display} [{top_game['i']}] {top_score:.0f}分")
        else:
            ambiguous.append(record)
            alt = " | ".join(
                f"{g.get('zhs') or g.get('zh') or g['t']}({s:.0f})" for s, g in cands
            )
            print(f"? 待确认  {record['name']}（{record['category']}） → 候选：{alt}")

    print(f"\n小结：自动关联 {linked}，待确认 {len(ambiguous)}，未匹配 {len(unmatched)}")
    if not args.apply:
        print("以上为预览结果，确认无误后加 --apply 执行写库。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
