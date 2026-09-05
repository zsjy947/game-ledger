"""集中配置：目录、主机端口等。

所有路径在导入时解析为绝对路径，其他模块只读取本模块的常量；
支持环境变量覆盖，便于测试与多实例部署。
"""

import os
import sys
from pathlib import Path


def _base_dir() -> Path:
    """数据存放基准：开发时为项目根目录；打包后为 exe 所在目录（便携使用）。"""
    if getattr(sys, "frozen", False):  # PyInstaller 打包后
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _resource_dir() -> Path:
    """静态资源基准：开发时为项目根目录；打包后为 PyInstaller 解包目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # PyInstaller 约定的解包目录
    return _base_dir()


# ── 目录 ────────────────────────────────────────────────────────────────────
BASE_DIR = _base_dir()
RESOURCE_DIR = _resource_dir()
TEMPLATE_DIR = RESOURCE_DIR / "switch_price_tracker" / "templates"
STATIC_DIR = RESOURCE_DIR / "switch_price_tracker" / "static"

# 数据目录：默认 <根目录>/data，可用环境变量 SWPT_DATA_DIR 覆盖
DATA_DIR = Path(os.environ.get("SWPT_DATA_DIR", str(BASE_DIR / "data"))).resolve()
DB_PATH = DATA_DIR / "prices.db"

# ── 服务器 ──────────────────────────────────────────────────────────────────
HOST = os.environ.get("SWPT_HOST", "127.0.0.1")
PORT = int(os.environ.get("SWPT_PORT", "5000"))
