"""PyInstaller 打包入口：双击 exe 弹出独立软件窗口（不打开浏览器、无控制台）。

数据（SQLite 数据库）保存在 exe 同目录的 data 文件夹下，整个文件夹可随意拷贝。
"""

import sys

from game_ledger.window import _alert, open_window


def main() -> None:
    # --windowed 打包环境下没有 stderr，跳过日志配置以免无效写入
    if sys.stderr is not None:
        import logging

        logging.basicConfig(
            level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
        )
    try:
        open_window()
    except SystemExit:
        raise
    except Exception:
        import traceback

        if sys.stderr is not None:
            import logging

            logging.getLogger(__name__).exception("启动失败")
        if getattr(sys, "frozen", False):
            # 无控制台的打包环境下，用弹窗展示错误，避免闪退
            _alert("程序启动失败：\n\n" + traceback.format_exc(limit=3), "错误")
        raise


if __name__ == "__main__":
    main()
