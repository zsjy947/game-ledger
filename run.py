"""开发模式入口：python run.py。

日常使用建议直接双击「start.bat」（自动准备虚拟环境并打开浏览器）。
"""

import logging

from game_ledger.serve import serve


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
    )
    try:
        serve(debug=True)  # 开发模式：显示详细错误页
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("服务已停止。")


if __name__ == "__main__":
    main()
