"""测试公共夹具：每个测试使用独立的临时数据库，不碰真实数据。"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from game_ledger import create_app, database  # noqa: E402


@pytest.fixture()
def client(tmp_path):
    """提供指向临时数据库的 Flask 测试客户端。"""
    database.DB_PATH = tmp_path / "test.db"
    database.init_db()
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c
