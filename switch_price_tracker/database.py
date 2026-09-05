"""SQLite 数据访问层。

设计要点：
- 所有 SQL 集中在本模块，路由层只调用函数、不接触 SQL；
- 连接统一通过 connect() 上下文管理器获取，自动提交/回滚，异常时也保证关闭；
- 使用 PRAGMA user_version 做轻量迁移：以后改表只需把 SCHEMA_VERSION 加 1，
  并在 MIGRATIONS 中追加对应版本的语句；
- 全部查询使用参数绑定，杜绝 SQL 注入。
"""

import shutil
import sqlite3
from contextlib import contextmanager

from .config import DB_PATH

def _add_source_column(conn) -> None:
    """v1 → v2：新增来源字段（先检查列是否存在，保证可重入）。"""
    columns = [row["name"] for row in conn.execute("PRAGMA table_info(cartridges)")]
    if "source" not in columns:
        conn.execute("ALTER TABLE cartridges ADD COLUMN source TEXT NOT NULL DEFAULT ''")


# 当前 schema 版本
SCHEMA_VERSION = 2

_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS cartridges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL CHECK (category IN ('NS', 'NS2')),
    name TEXT NOT NULL,
    price REAL NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

# 每个版本的迁移步骤：SQL 字符串（要求幂等）或接受连接对象的函数
MIGRATIONS: dict[int, list] = {
    1: [
        _TABLE_SQL,
        "CREATE INDEX IF NOT EXISTS idx_cartridges_name ON cartridges(name)",
        "CREATE INDEX IF NOT EXISTS idx_cartridges_category ON cartridges(category)",
        "CREATE INDEX IF NOT EXISTS idx_cartridges_updated_at ON cartridges(updated_at)",
    ],
    2: [
        _add_source_column,
        "CREATE INDEX IF NOT EXISTS idx_cartridges_source ON cartridges(source)",
    ],
}


@contextmanager
def connect():
    """获取数据库连接：退出时自动提交，异常时回滚，最终一定关闭。"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """建表、建索引并执行未应用的迁移；已有数据不受影响。

    迁移前会先把旧库备份为 data/prices.backup-v<旧版本>.db。
    """
    with connect() as conn:
        (version,) = conn.execute("PRAGMA user_version").fetchone()
        if version >= SCHEMA_VERSION:
            return

        # 迁移前备份旧库，保证数据安全（全新空库没有任何用户表，无需备份）
        has_tables = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' LIMIT 1"
        ).fetchone() is not None
        if has_tables:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            backup = DB_PATH.with_name(f"prices.backup-v{version}.db")
            if not backup.exists():
                shutil.copy2(DB_PATH, backup)

        for v in range(version + 1, SCHEMA_VERSION + 1):
            for step in MIGRATIONS[v]:
                if callable(step):
                    step(conn)
                else:
                    conn.executescript(step)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def _to_dict(row) -> dict | None:
    return dict(row) if row is not None else None


# ── 查询 ────────────────────────────────────────────────────────────────────

def get_all(
    search: str | None = None, category: str | None = None, source: str | None = None
) -> list[dict]:
    """获取全部卡带，支持名称模糊搜索与分类/来源筛选，按更新时间倒序。"""
    query = "SELECT * FROM cartridges WHERE 1=1"
    params: list = []
    if search:
        query += " AND name LIKE ?"
        params.append(f"%{search}%")
    if category:
        query += " AND category = ?"
        params.append(category)
    if source:
        query += " AND source = ?"
        params.append(source)
    query += " ORDER BY updated_at DESC, id DESC"

    with connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def get_by_id(cartridge_id: int) -> dict | None:
    """按 ID 获取单条记录，不存在时返回 None。"""
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM cartridges WHERE id = ?", (cartridge_id,)
        ).fetchone()
    return _to_dict(row)


def search_suggest(name: str) -> list[dict]:
    """输入联想：精确匹配优先，其余按名称模糊匹配，最多返回 5 条。"""
    with connect() as conn:
        exact = conn.execute(
            "SELECT * FROM cartridges WHERE name = ?", (name,)
        ).fetchall()
        exclude_ids = [row["id"] for row in exact]
        fuzzy_sql = "SELECT * FROM cartridges WHERE name LIKE ?"
        params: list = [f"%{name}%"]
        if exclude_ids:
            fuzzy_sql += f" AND id NOT IN ({','.join('?' * len(exclude_ids))})"
            params += exclude_ids
        fuzzy = conn.execute(fuzzy_sql + " LIMIT 5", params).fetchall()
    results = [dict(row) for row in exact]
    results += [dict(row) for row in fuzzy[: max(0, 5 - len(results))]]
    return results


# ── 写入 ────────────────────────────────────────────────────────────────────

def add(
    category: str, name: str, price: float, notes: str = "", source: str = ""
) -> dict:
    """新增一条卡带记录，返回完整的新记录。"""
    with connect() as conn:
        cursor = conn.execute(
            "INSERT INTO cartridges (category, name, price, notes, source) VALUES (?, ?, ?, ?, ?)",
            (category, name, price, notes, source),
        )
        row = conn.execute(
            "SELECT * FROM cartridges WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
    return dict(row)


def update(
    cartridge_id: int,
    category: str,
    name: str,
    price: float,
    notes: str = "",
    source: str = "",
) -> dict | None:
    """更新指定记录并返回更新后的数据；记录不存在时返回 None。"""
    with connect() as conn:
        cursor = conn.execute(
            """UPDATE cartridges
               SET category = ?, name = ?, price = ?, notes = ?, source = ?,
                   updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (category, name, price, notes, source, cartridge_id),
        )
        if cursor.rowcount == 0:
            return None
        row = conn.execute(
            "SELECT * FROM cartridges WHERE id = ?", (cartridge_id,)
        ).fetchone()
    return _to_dict(row)


def delete(cartridge_id: int) -> bool:
    """删除指定记录，返回是否确实删除了一条。"""
    with connect() as conn:
        cursor = conn.execute("DELETE FROM cartridges WHERE id = ?", (cartridge_id,))
        return cursor.rowcount > 0
