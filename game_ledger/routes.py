"""路由层：页面与 REST API（只做 HTTP——解析请求、构造响应）。

字段校验与 CSV 解析在 records.py，SQL 在 database.py，
本模块不出现业务规则与 SQL。响应统一为
{"success": bool, "data"?: ..., "message"?: ...} 结构。
"""

import re
from datetime import date

from flask import Blueprint, Response, jsonify, render_template, request

from . import __version__, database, games, records

bp = Blueprint("main", __name__)

# 封面 ID 只允许字母数字与下划线/连字符：阻断 ".."、"..\" 等路径穿越拼接
GAME_ID_RE = re.compile(r"[0-9A-Za-z_-]{1,64}")


# ── 页面 ────────────────────────────────────────────────────────────────────

@bp.get("/")
def index():
    """单页前端。"""
    return render_template(
        "index.html", version=__version__, source_presets=records.SOURCE_PRESETS
    )


# ── 内置游戏库 ──────────────────────────────────────────────────────────────

@bp.get("/cover/<game_id>")
def game_cover(game_id: str):
    """解析游戏封面：内置资源 → 本地缓存 → 在线下载缓存；失败返回 404。"""
    if not GAME_ID_RE.fullmatch(game_id):
        return Response("invalid cover id", status=404, mimetype="text/plain")
    data = games.resolve_cover(game_id)
    if data is None:
        return Response("cover not found", status=404, mimetype="text/plain")
    return Response(data, mimetype="image/jpeg", headers={"Cache-Control": "public, max-age=604800"})


@bp.get("/api/games/catalog")
def games_catalog():
    """内置游戏目录（桌面端搜索用）。

    唯一数据源是 assets/games.json（服务端已在内存里），不再随包携带
    同内容的静态 games.js；安卓分支仍使用静态 games.js 契约。
    """
    resp = jsonify({"success": True, "data": games.all_games()})
    resp.headers["Cache-Control"] = "no-cache"  # fetch_games 更新目录后立即生效
    return resp


# ── API：卡带 CRUD ──────────────────────────────────────────────────────────

@bp.get("/api/cartridges")
def list_cartridges():
    """获取全部卡带，支持 ?search= 与 ?category=、?source= 过滤。"""
    search = request.args.get("search", "").strip()
    category = request.args.get("category", "").strip()
    source = request.args.get("source", "").strip()
    records_list = database.get_all(
        search=search or None, category=category or None, source=source or None
    )
    return jsonify({"success": True, "data": records_list})


@bp.get("/api/cartridges/suggest")
def suggest_cartridges():
    """按名称片段联想已有卡带（新增时自动提示是否改为更新），附带历史最低价。"""
    q = request.args.get("q", "").strip()
    records_list = database.search_suggest(q) if q else []
    min_prices = database.get_min_prices([r["id"] for r in records_list])
    for record in records_list:
        record["min_price"] = min_prices.get(record["id"])
    return jsonify({"success": True, "data": records_list})


@bp.get("/api/cartridges/<int:cartridge_id>")
def get_cartridge(cartridge_id: int):
    record = database.get_by_id(cartridge_id)
    if record is None:
        return jsonify({"success": False, "message": "记录不存在"}), 404
    return jsonify({"success": True, "data": record})


@bp.get("/api/cartridges/<int:cartridge_id>/history")
def cartridge_price_history(cartridge_id: int):
    """某条卡带的价格变化历史（时间正序），记录不存在返回 404。"""
    if database.get_by_id(cartridge_id) is None:
        return jsonify({"success": False, "message": "记录不存在"}), 404
    return jsonify({"success": True, "data": database.get_price_history(cartridge_id)})


def _json_body():
    """解析 JSON 请求体；非法时返回 None（由调用方返回 400）。"""
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else None


@bp.post("/api/cartridges")
def add_cartridge():
    body = _json_body()
    if body is None:
        return jsonify({"success": False, "message": "请求体必须为 JSON"}), 400
    fields, error = records.parse_payload(body)
    if error:
        return jsonify({"success": False, "message": error}), 400
    record = database.add(**fields)
    return jsonify({"success": True, "data": record}), 201


@bp.put("/api/cartridges/<int:cartridge_id>")
def update_cartridge(cartridge_id: int):
    existing = database.get_by_id(cartridge_id)
    if existing is None:
        return jsonify({"success": False, "message": "记录不存在"}), 404
    body = _json_body()
    if body is None:
        return jsonify({"success": False, "message": "请求体必须为 JSON"}), 400
    fields, error = records.parse_payload(body, existing)
    if error:
        return jsonify({"success": False, "message": error}), 400
    # created_at/updated_at 均由服务端管理，普通更新不接受客户端值
    fields.pop("created_at", None)
    fields.pop("updated_at", None)
    record = database.update(cartridge_id, **fields)
    return jsonify({"success": True, "data": record})


@bp.delete("/api/cartridges/<int:cartridge_id>")
def delete_cartridge(cartridge_id: int):
    if not database.delete(cartridge_id):
        return jsonify({"success": False, "message": "记录不存在"}), 404
    return jsonify({"success": True, "message": "删除成功"})


# ── API：CSV 导出 / 导入 ────────────────────────────────────────────────────

@bp.get("/api/export/csv")
def export_csv():
    """导出全部记录为 CSV（UTF-8 带 BOM，Excel 直接打开不乱码）。"""
    csv_text = records.build_export_csv(database.get_all())
    filename = f"cartridges-{date.today():%Y%m%d}.csv"
    return Response(
        csv_text,
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

    entries, header_error = records.parse_import_csv(text)
    if header_error:
        return jsonify({"success": False, "message": header_error}), 400

    existing = {(r["category"], r["name"]) for r in database.get_all()}
    imported = skipped = failed = 0
    errors: list[str] = []
    for entry in entries:
        if entry["error"]:
            failed += 1
            if len(errors) < 10:
                errors.append(f"第{entry['line_no']}行：{entry['error']}")
            continue
        fields = entry["fields"]
        key = (fields["category"], fields["name"])
        if key in existing:
            skipped += 1
            continue
        database.add(**fields)
        existing.add(key)
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
