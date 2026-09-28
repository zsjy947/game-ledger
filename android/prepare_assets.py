"""组装安卓 WebView 资产目录 android/app/src/main/assets/www。

- 用 Jinja2 预渲染 index.html（注入版本号/来源预设），并把 /static/ 引用改为相对路径；
- 注入 games.js（安卓端游戏目录数据源，由 assets/games.json 生成；
  桌面端走 /api/games/catalog，两者单一数据源都是 games.json）；
- 复制 app.js / style.css 与内置封面目录。

由 android/build_apk.py 自动调用；数据变化后重新打包即可。
"""

import json
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from jinja2 import Template  # noqa: E402

from game_ledger import __version__, records  # noqa: E402

PACKAGE_DIR = PROJECT_ROOT / "game_ledger"
OUT_DIR = PROJECT_ROOT / "android" / "app" / "src" / "main" / "assets" / "www"


def prepare() -> None:
    template_text = (PACKAGE_DIR / "templates" / "index.html").read_text(encoding="utf-8")
    html_text = Template(template_text).render(
        version=__version__,
        source_presets=records.SOURCE_PRESETS,
        categories=records.CATEGORIES,
    )
    # file:// 下无法使用 /static/ 绝对路径，改为相对路径
    html_text = html_text.replace("/static/", "")
    # 注入 games.js：必须在 app.js 之前执行（defer 脚本按文档顺序执行），
    # app.js 的 NATIVE_MODE 分支从 window.__GAMES__ 读目录
    html_text = html_text.replace(
        '<script src="app.js" defer></script>',
        '<script src="games.js" defer></script>\n    <script src="app.js" defer></script>',
    )

    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True)

    (OUT_DIR / "index.html").write_text(html_text, encoding="utf-8")
    for name in ("app.js", "style.css"):
        shutil.copy2(PACKAGE_DIR / "static" / name, OUT_DIR / name)

    # 安卓端游戏目录：assets/games.json → window.__GAMES__（紧凑 JSON 直拼）
    games_json = (PACKAGE_DIR / "assets" / "games.json").read_text(encoding="utf-8")
    (OUT_DIR / "games.js").write_text(
        "window.__GAMES__=" + games_json, encoding="utf-8"
    )

    covers_src = PACKAGE_DIR / "assets" / "covers"
    covers_dst = OUT_DIR / "covers"
    if covers_src.exists():
        shutil.copytree(covers_src, covers_dst)

    n_games = len(json.loads(games_json))
    n_covers = len(list(covers_dst.glob("*.jpg"))) if covers_dst.exists() else 0
    size_mb = sum(f.stat().st_size for f in OUT_DIR.rglob("*") if f.is_file()) / 1024 / 1024
    print(f"assets ready: {OUT_DIR}")
    print(f"games bundled: {n_games} | covers bundled: {n_covers} | total {size_mb:.1f} MB")


if __name__ == "__main__":
    prepare()
