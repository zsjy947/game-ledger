"""卡带记录的领域逻辑：字段校验、CSV 导入/导出解析。

路由层只做 HTTP（解析请求、构造响应），校验与 CSV 解析集中在本模块，
所有 SQL 仍集中在 database.py——「records 校验 → database 落库」构成领域层。
"""

import csv
import io
import math
import re

VALID_CATEGORIES = ("NS", "NS2")

# 来源预设选项（前端下拉框以此为准，选择「其他」时可自由填写）
SOURCE_PRESETS = ("拼多多福袋", "拼多多V3", "支付宝刷券")

MAX_SOURCE_LENGTH = 50
MAX_INTRO_LENGTH = 6000
MAX_COVER_LENGTH = 64
MAX_ALIAS_LENGTH = 100

# SQLite CURRENT_TIMESTAMP 的格式（CSV 往返时校验时间戳列）
TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")

CSV_FIELDS = (
    "id", "category", "name", "alias", "price", "source", "cover", "intro",
    "notes", "created_at", "updated_at",
)
CSV_REQUIRED = ("category", "name")


def parse_payload(body: dict, existing: dict | None = None) -> tuple[dict | None, str | None]:
    """解析并校验记录字段，返回 (字段字典, None) 或 (None, 错误消息)。

    更新场景传入 existing，未提供的字段回退到已有记录的值；
    created_at/updated_at 仅在调用方显式提供且格式合法时包含在结果里
    （CSV 导入保真用；普通 API 不传，由数据库取当前时间）。
    """
    src = existing or {}
    category = str(body.get("category") or src.get("category") or "").strip()
    name = str(body.get("name") or src.get("name") or "").strip()
    notes = str(body.get("notes") if "notes" in body else src.get("notes") or "").strip()
    source = str(body.get("source") if "source" in body else src.get("source") or "").strip()
    cover = str(body.get("cover") if "cover" in body else src.get("cover") or "").strip()
    intro = str(body.get("intro") if "intro" in body else src.get("intro") or "").strip()
    alias = str(body.get("alias") if "alias" in body else src.get("alias") or "").strip()
    price = body["price"] if "price" in body else src.get("price")

    if category not in VALID_CATEGORIES:
        return None, "分类必须为 NS 或 NS2"
    if not name:
        return None, "名称不能为空"
    if len(source) > MAX_SOURCE_LENGTH:
        return None, f"来源不能超过 {MAX_SOURCE_LENGTH} 个字符"
    if len(cover) > MAX_COVER_LENGTH:
        return None, "封面引用无效"
    if len(intro) > MAX_INTRO_LENGTH:
        return None, f"介绍不能超过 {MAX_INTRO_LENGTH} 个字符"
    if len(alias) > MAX_ALIAS_LENGTH:
        return None, f"别名不能超过 {MAX_ALIAS_LENGTH} 个字符"

    if price is None or (isinstance(price, str) and not price.strip()):
        price = 0.0
    elif isinstance(price, bool):
        return None, "价格格式不正确"
    else:
        try:
            price = float(price)
        except (TypeError, ValueError):
            return None, "价格格式不正确"
        # NaN/Infinity 能通过上面的转换却无法写入 NOT NULL 列（SQLite 存为 NULL）
        if not math.isfinite(price):
            return None, "价格格式不正确"
        if price < 0:
            return None, "价格不能为负数"

    fields = {
        "category": category,
        "name": name,
        "price": price,
        "notes": notes,
        "source": source,
        "cover": cover,
        "intro": intro,
        "alias": alias,
    }
    for key in ("created_at", "updated_at"):
        value = str(body.get(key) or "").strip()
        if not value:
            continue
        if not TIMESTAMP_RE.fullmatch(value):
            return None, "时间格式需为 YYYY-MM-DD HH:MM:SS"
        fields[key] = value
    return fields, None


def build_export_csv(records: list[dict]) -> str:
    """把记录列表构建为 CSV 文本（UTF-8 带 BOM，Excel 打开中文不乱码）。"""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_FIELDS)
    for record in records:
        writer.writerow([record.get(field, "") for field in CSV_FIELDS])
    return "\ufeff" + buf.getvalue()


def parse_import_csv(text: str) -> tuple[list[dict], str | None]:
    """解析导入的 CSV 文本，返回 (行条目, 表头错误)。

    条目为 {"line_no", "fields": dict|None, "error": str|None}：
    校验失败的行 fields 为 None、error 给出原因（含行号），不中断整体解析。
    """
    reader = csv.DictReader(io.StringIO(text))
    missing = [f for f in CSV_REQUIRED if f not in (reader.fieldnames or [])]
    if missing:
        return [], f"CSV 缺少必需列：{'、'.join(missing)}"

    entries: list[dict] = []
    for line_no, row in enumerate(reader, start=2):
        if not any((cell or "").strip() for cell in row.values() if isinstance(cell, str)):
            continue  # 空行
        fields, error = parse_payload(
            {
                "category": row.get("category"),
                "name": row.get("name"),
                "price": row.get("price") or "",
                "source": row.get("source") or "",
                "cover": row.get("cover") or "",
                "intro": row.get("intro") or "",
                "notes": row.get("notes") or "",
                "alias": row.get("alias") or "",
                "created_at": row.get("created_at") or "",
                "updated_at": row.get("updated_at") or "",
            }
        )
        entries.append(
            {"line_no": line_no, "fields": fields, "error": error}
        )
    return entries, None
