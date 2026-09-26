"""桌面窗口模式：内嵌 WebView，像常见 Windows 软件一样在独立窗口中运行。

由打包入口 launcher.py 使用（双击 exe 直接弹出软件窗口，不打开浏览器、
没有黑色控制台窗口）。开发模式 run.py 仍使用浏览器方式，便于调试。

技术要点：
- Flask 服务通过 werkzeug 在 127.0.0.1 随机空闲端口上启动（永不端口冲突）；
- pywebview 使用系统自带的 Edge WebView2 渲染；
- Windows 下用命名互斥量保证单实例，重复启动时弹窗提示后退出；
- 服务线程为守护线程，窗口关闭即整个程序退出。
"""

import logging
import sys
import threading

from . import config, database

logger = logging.getLogger(__name__)

_MUTEX_NAME = "SwitchPriceTracker_SingleInstance_Mutex"


def _ensure_single_instance() -> bool:
    """Windows 下保证只运行一个实例。返回 False 表示已有实例在运行。"""
    if sys.platform != "win32":
        return True
    import ctypes

    # use_last_error=True：把 Win32 last error 保存到 ctypes 线程私有存储，
    # 避免被 Python/ctypes 中间的系统调用覆盖（GetLastError() 直接读不可靠）
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    # ERROR_ALREADY_EXISTS = 183
    return ctypes.get_last_error() != 183


def _alert(message: str, title: str = "提示") -> None:
    """弹窗提示（无控制台的打包环境下也能让用户看到信息）。"""
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, title, 0x40)  # MB_ICONINFORMATION
    else:
        print(message)


def open_window() -> None:
    """启动本地服务并打开桌面窗口（阻塞直到窗口关闭）。"""
    try:
        import webview
    except ImportError:
        _alert("缺少 pywebview 组件，无法打开窗口。\n请先运行: pip install -r requirements.txt", "错误")
        raise SystemExit(1)

    if not _ensure_single_instance():
        _alert("Switch 卡带价格统计 已在运行中。", "提示")
        raise SystemExit(0)

    database.init_db()

    from . import create_app

    app = create_app()

    # 随机空闲端口启动服务（仅监听本机回环地址）
    from werkzeug.serving import make_server

    server = make_server(config.HOST, 0, app, threaded=True)
    url = f"http://{config.HOST}:{server.server_address[1]}"
    threading.Thread(target=server.serve_forever, daemon=True, name="flask-server").start()
    logger.info("本地服务已启动：%s", url)

    window = webview.create_window(
        "Switch 卡带价格统计",
        url,
        width=1180,
        height=780,
        min_size=(960, 620),
        background_color="#0f1117",
    )
    webview.start()
    # 走到这里说明窗口已关闭
    server.shutdown()
    logger.info("窗口已关闭，程序退出。")
