"""路由层：页面与 REST API。

只负责参数解析/校验和调用数据层，不写 SQL。
响应统一为 {"success": bool, "data"?: ..., "message"?: ...} 结构。
"""

import csv
import io
import math
from datetime import date

from flask import Blueprint, Response, jsonify, render_template, request

from . import __version__, database, games

bp = Blueprint("main", __name__)

VALID_CATEGORIES = ("NS", "NS2")

# 来源预设选项（前端下拉框以此为准，选择「其他」时可自由填写）
SOURCE_PRESETS = ("拼多多福袋", "拼多多V3", "支付宝刷券")

MAX_SOURCE_LENGTH = 50
MAX_INTRO_LENGTH = 6000


def _parse_payload(body: dict, existing: dict | None = None):
    """解析并校验请求体。

    更新场景传入 existing，未提供的字段回退到已有记录的值。
    Returns:
        ((category, name, price, notes, source, cover, intro), None) 或 (None, 错误消息)。
    """
    src = existing or {}
    category = str(body.get("category") or src.get("category") or "").strip()
    name = str(body.get("name") or src.get("name") or "").strip()
    notes = str(body.get("notes") if "notes" in body else src.get("notes") or "").strip()
    source = str(body.get("source") if "source" in body else src.get("source") or "").strip()
    cover = str(body.get("cover") if "cover" in body else src.get("cover") or "").strip()
    intro = str(body.get("intro") if "intro" in body else src.get("intro") or "").strip()
    price = body["price"] if "price" in body else src.get("price")

    if category not in VALID_CATEGORIES:
        return None, "分类必须为 NS 或 NS2"
    if not name:
        return None, "名称不能为空"
    if len(source) > MAX_SOURCE_LENGTH:
        return None, f"来源不能超过 {MAX_SOURCE_LENGTH} 个字符"
    if len(cover) > 64:
        return None, "封面引用无效"
    if len(intro) > MAX_INTRO_LENGTH:
        return None, f"介绍不能超过 {MAX_INTRO_LENGTH} 个字符"

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

    return (category, name, price, notes, source, cover, intro), None


# ── 页面 ────────────────────────────────────────────────────────────────────

@bp.get("/")
def index():
    """单页前端。"""
    return render_template(
        "index.html", version=__version__, source_presets=SOURCE_PRESETS
    )


# ── 内置游戏库 ──────────────────────────────────────────────────────────────

@bp.get("/cover/<game_id>")
def game_cover(game_id: str):
    """解析游戏封面：内置资源 → 本地缓存 → 在线下载缓存；失败返回 404。"""
    data = games.resolve_cover(game_id)
    if data is None:
        return Response("cover not found", status=404, mimetype="text/plain")
    return Response(data, mimetype="image/jpeg", headers={"Cache-Control": "public, max-age=604800"})


# ── API ─────────────────────────────────────────────────────────────────────

@bp.get("/api/cartridges")
def list_cartridges():
    """获取全部卡带，支持 ?search= 与 ?category=、?source= 过滤。"""
    search = request.args.get("search", "").strip()
    category = request.args.get("category", "").strip()
    source = request.args.get("source", "").strip()
    records = database.get_all(
        search=search or None, category=category or None, source=source or None
    )
    return jsonify({"success": True, "data": records})


@bp.get("/api/cartridges/suggest")
def suggest_cartridges():
    """按名称片段联想已有卡带（新增时自动提示是否改为更新），附带历史最低价。"""
    q = request.args.get("q", "").strip()
    records = database.search_suggest(q) if q else []
    min_prices = database.get_min_prices([r["id"] for r in records])
    for record in records:
        record["min_price"] = min_prices.get(record["id"])
    return jsonify({"success": True, "data": records})


@bp.get("/api/cartridges/<int:cartridge_id>/history")
def cartridge_price_history(cartridge_id: int):
    """某条卡带的价格变化历史（时间正序），记录不存在返回 404。"""
    if database.get_by_id(cartridge_id) is None:
        return jsonify({"success": False, "message": "记录不存在"}), 404
    return jsonify({"success": True, "data": database.get_price_history(cartridge_id)})


@bp.get("/api/cartridges/<int:cartridge_id>")
def get_cartridge(cartridge_id: int):
    record = database.get_by_id(cartridge_id)
    if record is None:
        return jsonify({"success": False, "message": "记录不存在"}), 404
    return jsonify({"success": True, "data": record})


@bp.post("/api/cartridges")
def add_cartridge():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"success": False, "message": "请求体必须为 JSON"}), 400
    fields, error = _parse_payload(body)
    if error:
        return jsonify({"success": False, "message": error}), 400
    record = database.add(*fields)
    return jsonify({"success": True, "data": record}), 201


@bp.put("/api/cartridges/<int:cartridge_id>")
def update_cartridge(cartridge_id: int):
    existing = database.get_by_id(cartridge_id)
    if existing is None:
        return jsonify({"success": False, "message": "记录不存在"}), 404
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"success": False, "message": "请求体必须为 JSON"}), 400
    fields, error = _parse_payload(body, existing)
    if error:
        return jsonify({"success": False, "message": error}), 400
    record = database.update(cartridge_id, *fields)
    return jsonify({"success": True, "data": record})


@bp.delete("/api/cartridges/<int:cartridge_id>")
def delete_cartridge(cartridge_id: int):
    if not database.delete(cartridge_id):
        return jsonify({"success": False, "message": "记录不存在"}), 404
    return jsonify({"success": True, "message": "删除成功"})


# ── CSV 导出 / 导入 ─────────────────────────────────────────────────────────

CSV_FIELDS = (
    "id", "category", "name", "price", "source", "cover", "intro", "notes",
    "created_at", "updated_at",
)
CSV_REQUIRED = ("category", "name")


@bp.get("/api/export/csv")
def export_csv():
    """导出全部记录为 CSV（UTF-8 带 BOM，Excel 直接打开不乱码）。"""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_FIELDS)
    for record in database.get_all():
        writer.writerow([record.get(field, "") for field in CSV_FIELDS])
    filename = f"cartridges-{date.today():%Y%m%d}.csv"
    # 前置 BOM：无 BOM 的 UTF-8 CSV 在 Excel 里中文会乱码
    return Response(
        "\ufeff" + buf.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "Cache-Control": "no-store",
        },
    )


@bp.post("/api/import/csv")
def import_csv():
    """从 CSV 批量导入记录；分类+名称重复的行跳过，坏行汇报不中断。"""
    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify({"success": False, "message": "请选择要导入的 CSV 文件"}), 400
    try:
        text = file.stream.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        return jsonify({"success": False, "message": "文件需为 UTF-8 编码（Excel 请另存为「CSV UTF-8」）"}), 400

    reader = csv.DictReader(io.StringIO(text))
    missing = [f for f in CSV_REQUIRED if f not in (reader.fieldnames or [])]
    if missing:
        return jsonify({"success": False, "message": f"CSV 缺少必需列：{'、'.join(missing)}"}), 400

    existing = {(r["category"], r["name"]) for r in database.get_all()}
    imported = skipped = failed = 0
    errors: list[str] = []
    for line_no, row in enumerate(reader, start=2):
        if not any((cell or "").strip() for cell in row.values() if isinstance(cell, str)):
            continue  # 空行
        fields, error = _parse_payload(
            {
                "category": row.get("category"),
                "name": row.get("name"),
                "price": row.get("price") or "",
                "source": row.get("source") or "",
                "cover": row.get("cover") or "",
                "intro": row.get("intro") or "",
                "notes": row.get("notes") or "",
            }
        )
        if error:
            failed += 1
            if len(errors) < 10:
                errors.append(f"第{line_no}行：{error}")
            continue
        category, name, price, notes, source, cover, intro = fields
        if (category, name) in existing:
            skipped += 1
            continue
        database.add(category, name, price, notes, source, cover, intro)
        existing.add((category, name))
        imported += 1

    message = f"导入完成：新增 {imported} 条，跳过重复 {skipped} 条"
    if failed:
        message += f"，失败 {failed} 条"
    return jsonify(
        {
            "success": True,
            "data": {"imported": imported, "skipped": skipped, "failed": failed, "errors": errors},
            "message": message,
        }
    )
