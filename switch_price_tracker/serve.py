"""统一的启动逻辑：开发入口 run.py 与打包入口 launcher.py 共用。

职责：端口冲突检测（已运行则直接打开浏览器）、初始化数据库、
启动 Web 服务并自动打开默认浏览器。
"""

import logging
import os
import socket
import threading
import webbrowser
from urllib.request import urlopen

from . import database
from .config import HOST, PORT

logger = logging.getLogger(__name__)


def _probe_port() -> str:
    """探测端口状态：'ours'（本应用已在运行）/ 'busy'（被其他程序占用）/ 'free'。"""
    try:
        with socket.create_connection((HOST, PORT), timeout=1):
            pass
    except OSError:
        return "free"

    try:
        with urlopen(f"http://{HOST}:{PORT}/api/cartridges", timeout=2) as resp:
            if b'"success"' in resp.read(256):
                return "ours"
    except Exception:
        pass
    return "busy"


def serve(debug: bool = False, open_browser: bool = True) -> None:
    """初始化数据库并启动 Web 服务（阻塞直到 Ctrl+C 或关闭窗口）。

    若检测到本应用已在运行，则只打开浏览器，不再重复启动第二个实例。
    """
    state = _probe_port()
    url = f"http://{HOST}:{PORT}"
    open_browser = open_browser and not os.environ.get("SWPT_NO_BROWSER")

    if state == "ours":
        logger.info("应用已在运行，直接打开浏览器：%s", url)
        if open_browser:
            webbrowser.open(url)
        return
    if state == "busy":
        raise SystemExit(
            f"端口 {PORT} 已被其他程序占用。"
            f"可设置环境变量 SWPT_PORT 换一个端口后重试。"
        )

    database.init_db()
    logger.info("Switch 卡带价格统计已启动 → %s （关闭此窗口即退出服务）", url)
    if open_browser:
        # 等服务真正监听后再打开浏览器
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()

    from . import create_app

    app = create_app()
    # 不启用 reloader：打包环境不支持，且会导致重复打开浏览器
    app.run(host=HOST, port=PORT, debug=debug, use_reloader=False)
