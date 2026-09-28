package com.gameledger.app;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;
import android.os.Build;
import android.os.Environment;
import android.provider.MediaStore;
import android.webkit.JavascriptInterface;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * 前端存储桥：把 Flask 后端的 REST 语义原样搬到安卓壳内。
 *
 * 前端在 file:// 协议下不再走 fetch，而是调用
 * GameLedgerBridge.request(method, path, query, jsonBody)，同步拿到
 * {"status": int, "body": object}——body 与桌面端 REST 响应完全一致
 * （{"success": bool, "data"?: ..., "message"?: ...}）。
 *
 * 表结构、迁移链（PRAGMA user_version v1→v5）与校验规则完整移植自
 * game_ledger/database.py 与 game_ledger/records.py，桌面端导出的 CSV
 * 可直接导入，数据库文件语义级兼容。
 */
public class StorageBridge {

    public static final String JS_NAME = "GameLedgerBridge";

    /** 与 game_ledger/records.py 保持一致的常量。 */
    private static final String[] VALID_CATEGORIES = {"NS", "NS2", "PS4", "PS5"};
    private static final int MAX_SOURCE_LENGTH = 50;
    private static final int MAX_INTRO_LENGTH = 6000;
    private static final int MAX_COVER_LENGTH = 64;
    private static final int MAX_ALIAS_LENGTH = 100;
    private static final Pattern TIMESTAMP_RE =
            Pattern.compile("\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}");
    private static final String[] CSV_FIELDS = {
            "id", "category", "name", "alias", "price", "source", "cover",
            "intro", "notes", "created_at", "updated_at",
    };

    private static final String TABLE_SQL =
            "CREATE TABLE IF NOT EXISTS cartridges ("
            + "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            + " category TEXT NOT NULL CHECK (category IN ('NS', 'NS2')),"
            + " name TEXT NOT NULL,"
            + " price REAL NOT NULL DEFAULT 0,"
            + " notes TEXT NOT NULL DEFAULT '',"
            + " created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
            + " updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)";

    private final Helper helper;
    private boolean v6Done = false;

    public StorageBridge(Context context) {
        helper = new Helper(context.getApplicationContext());
    }

    /**
     * 取可写库连接，并惰性完成 v6 迁移（放宽分类 CHECK 的表重建）。
     *
     * v6 重建必须 DROP 父表，而 SQLiteOpenHelper 的 onUpgrade 运行在框架
     * 事务内、PRAGMA foreign_keys 在事务内是空操作——那会让 DROP 触发
     * 级联清空 price_history。因此 v6 放到这里在事务外执行（与桌面端
     * database.py 的迁移语义一致）。
     */
    private SQLiteDatabase db() {
        SQLiteDatabase db = helper.getWritableDatabase();
        if (!v6Done) {
            v6Done = true;
            int version = db.getVersion();
            if (version < Helper.SCHEMA_VERSION_V6) {
                helper.backupBeforeMigrate(db, version);
                migrateV6(db);
            }
        }
        return db;
    }

    /** v6：重建 cartridges 去掉 CHECK (category IN ('NS','NS2'))。 */
    private static void migrateV6(SQLiteDatabase db) {
        db.execSQL("DROP TABLE IF EXISTS cartridges_v6"); // 清理可能的半成品
        db.execSQL("PRAGMA foreign_keys = OFF");
        db.execSQL(
                "CREATE TABLE cartridges_v6 ("
                + "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                + " category TEXT NOT NULL,"
                + " name TEXT NOT NULL,"
                + " price REAL NOT NULL DEFAULT 0,"
                + " notes TEXT NOT NULL DEFAULT '',"
                + " created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
                + " updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
                + " source TEXT NOT NULL DEFAULT '',"
                + " cover TEXT NOT NULL DEFAULT '',"
                + " intro TEXT NOT NULL DEFAULT '',"
                + " alias TEXT NOT NULL DEFAULT '')");
        db.execSQL("INSERT INTO cartridges_v6 (id, category, name, price, notes,"
                + " created_at, updated_at, source, cover, intro, alias)"
                + " SELECT id, category, name, price, notes, created_at,"
                + " updated_at, source, cover, intro, alias FROM cartridges");
        db.execSQL("DROP TABLE cartridges");
        db.execSQL("ALTER TABLE cartridges_v6 RENAME TO cartridges");
        for (String sql : new String[]{
                "CREATE INDEX IF NOT EXISTS idx_cartridges_name ON cartridges(name)",
                "CREATE INDEX IF NOT EXISTS idx_cartridges_category ON cartridges(category)",
                "CREATE INDEX IF NOT EXISTS idx_cartridges_updated_at ON cartridges(updated_at)",
                "CREATE INDEX IF NOT EXISTS idx_cartridges_source ON cartridges(source)"}) {
            db.execSQL(sql);
        }
        db.execSQL("PRAGMA foreign_keys = ON");
        db.setVersion(Helper.SCHEMA_VERSION_V6);
    }

    /** 前端唯一入口：同步 REST 调用，永不向 JS 抛异常。 */
    @JavascriptInterface
    public String request(String method, String path, String query, String jsonBody) {
        int status;
        Object body;
        try {
            Response resp = handle(
                    (method == null ? "GET" : method).toUpperCase(Locale.US),
                    path == null ? "" : path,
                    query == null ? "" : query,
                    jsonBody == null ? "" : jsonBody);
            status = resp.status;
            body = resp.body;
        } catch (JSONException e) {
            status = 400;
            body = fail("请求体必须为 JSON");
        } catch (Exception e) {
            status = 500;
            body = fail("本地存储错误");
        }
        try {
            JSONObject envelope = new JSONObject();
            envelope.put("status", status);
            envelope.put("body", body == null ? JSONObject.NULL : body);
            return envelope.toString();
        } catch (JSONException e) {
            return "{\"status\":500,\"body\":{\"success\":false,\"message\":\"本地存储错误\"}}";
        }
    }

    /**
     * 把文本保存到系统下载目录（CSV 导出用）。
     *
     * API 29+ 走 MediaStore.Downloads（无需权限）；旧版本先尝试公共
     * Downloads 目录，无写权限时回退应用外部私有目录。返回保存路径，
     * 失败返回空字符串——调用方据此提示。
     */
    @JavascriptInterface
    public String saveFile(String filename, String mimeType, String content) {
        String safeName = filename == null ? "" : filename.replaceAll("[\\\\/:*?\"<>|]", "_").trim();
        if (safeName.isEmpty()) safeName = "GameLedger-export.csv";
        String mime = (mimeType == null || mimeType.isEmpty()) ? "application/octet-stream" : mimeType;
        byte[] bytes = (content == null ? "" : content).getBytes(StandardCharsets.UTF_8);
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                ContentValues values = new ContentValues();
                values.put(MediaStore.MediaColumns.DISPLAY_NAME, safeName);
                values.put(MediaStore.MediaColumns.MIME_TYPE, mime);
                values.put(MediaStore.MediaColumns.IS_PENDING, 1);
                android.net.Uri uri = helper.getContext().getContentResolver()
                        .insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values);
                if (uri == null) return "";
                try (OutputStream os = helper.getContext().getContentResolver().openOutputStream(uri)) {
                    if (os == null) return "";
                    os.write(bytes);
                }
                values.clear();
                values.put(MediaStore.MediaColumns.IS_PENDING, 0);
                helper.getContext().getContentResolver().update(uri, values, null, null);
                return "Downloads/" + safeName;
            }
            File dir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS);
            try {
                if (!dir.exists() && !dir.mkdirs()) throw new IOException("mkdirs failed");
                File out = new File(dir, safeName);
                writeFile(out, bytes);
                return out.getAbsolutePath();
            } catch (IOException | SecurityException e) {
                File priv = helper.getContext().getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS);
                if (priv == null) return "";
                File out = new File(priv, safeName);
                writeFile(out, bytes);
                return out.getAbsolutePath();
            }
        } catch (Exception e) {
            return "";
        }
    }

    // ── 路由分发 ─────────────────────────────────────────────────────────────

    private static final class Response {
        final int status;
        final Object body;

        Response(int status, Object body) {
            this.status = status;
            this.body = body;
        }
    }

    private static JSONObject ok(Object data) throws JSONException {
        JSONObject o = new JSONObject();
        o.put("success", true);
        o.put("data", data);
        return o;
    }

    private static JSONObject fail(String message) {
        try {
            JSONObject o = new JSONObject();
            o.put("success", false);
            o.put("message", message);
            return o;
        } catch (JSONException e) {
            throw new IllegalStateException(e);
        }
    }

    private Response handle(String method, String path, String query, String jsonBody)
            throws JSONException {
        // /api/cartridges/<id> 与 /history
        java.util.regex.Matcher m = Pattern
                .compile("^/api/cartridges/(\\d+)(/history)?$").matcher(path);

        if (path.equals("/api/cartridges")) {
            if (method.equals("GET")) return new Response(200, listCartridges(query));
            if (method.equals("POST")) return addCartridge(jsonBody);
            return new Response(405, fail("请求方法不允许"));
        }
        if (path.equals("/api/cartridges/suggest") && method.equals("GET")) {
            return new Response(200, suggest(query));
        }
        if (m.matches()) {
            long id = Long.parseLong(m.group(1));
            boolean history = m.group(2) != null;
            if (history && method.equals("GET")) return priceHistory(id);
            if (!history && method.equals("GET")) return getCartridge(id);
            if (!history && method.equals("PUT")) return updateCartridge(id, jsonBody);
            if (!history && method.equals("DELETE")) return deleteCartridge(id);
            return new Response(405, fail("请求方法不允许"));
        }
        if (path.equals("/api/export/csv") && method.equals("GET")) {
            return new Response(200, exportCsv());
        }
        if (path.equals("/api/import/csv") && method.equals("POST")) {
            return importCsv(jsonBody);
        }
        return new Response(404, fail("接口不存在"));
    }

    // ── 查询参数 ─────────────────────────────────────────────────────────────

    private static String param(String query, String key) {
        for (String pair : query.split("&")) {
            int eq = pair.indexOf('=');
            if (eq > 0 && pair.substring(0, eq).equals(key)) {
                return android.net.Uri.decode(pair.substring(eq + 1));
            }
        }
        return "";
    }

    // ── 列表 / 联想 / 详情 ──────────────────────────────────────────────────

    private JSONObject listCartridges(String query) throws JSONException {
        String search = param(query, "search").trim();
        String category = param(query, "category").trim();
        String source = param(query, "source").trim();

        StringBuilder sql = new StringBuilder("SELECT * FROM cartridges WHERE 1=1");
        List<String> args = new ArrayList<>();
        if (!search.isEmpty()) {
            String like = "%" + escapeLike(search) + "%";
            sql.append(" AND (name LIKE ? ESCAPE '\\' OR alias LIKE ? ESCAPE '\\')");
            args.add(like);
            args.add(like);
        }
        if (!category.isEmpty()) {
            sql.append(" AND category = ?");
            args.add(category);
        }
        if (!source.isEmpty()) {
            sql.append(" AND source = ?");
            args.add(source);
        }
        sql.append(" ORDER BY updated_at DESC, id DESC");

        SQLiteDatabase db = db();
        try (Cursor c = db.rawQuery(sql.toString(), args.toArray(new String[0]))) {
            JSONArray arr = new JSONArray();
            while (c.moveToNext()) arr.put(rowToJson(c));
            return ok(arr);
        }
    }

    private JSONObject suggest(String query) throws JSONException {
        String q = param(query, "q").trim();
        if (q.isEmpty()) return ok(new JSONArray());
        SQLiteDatabase db = db();

        List<JSONObject> results = new ArrayList<>();
        List<Long> exactIds = new ArrayList<>();
        try (Cursor c = db.rawQuery(
                "SELECT * FROM cartridges WHERE name = ? OR alias = ?",
                new String[]{q, q})) {
            while (c.moveToNext()) {
                JSONObject row = rowToJson(c);
                results.add(row);
                exactIds.add(row.getLong("id"));
            }
        }
        if (results.size() < 5) {
            String like = "%" + escapeLike(q) + "%";
            StringBuilder fuzzy = new StringBuilder(
                    "SELECT * FROM cartridges WHERE (name LIKE ? ESCAPE '\\' OR alias LIKE ? ESCAPE '\\')");
            List<String> args = new ArrayList<>();
            args.add(like);
            args.add(like);
            if (!exactIds.isEmpty()) {
                fuzzy.append(" AND id NOT IN (");
                for (int i = 0; i < exactIds.size(); i++) fuzzy.append(i == 0 ? "?" : ",?");
                args.addAll(toStringList(exactIds));
                fuzzy.append(")");
            }
            fuzzy.append(" LIMIT 5");
            try (Cursor c = db.rawQuery(fuzzy.toString(), args.toArray(new String[0]))) {
                while (c.moveToNext() && results.size() < 5) results.add(rowToJson(c));
            }
        }

        Map<Long, Double> minPrices = minPrices(idsOf(results));
        for (JSONObject row : results) {
            long id = row.getLong("id");
            Double min = minPrices.get(id);
            row.put("min_price", min == null ? JSONObject.NULL : min.doubleValue());
        }
        return ok(new JSONArray(results));
    }

    private Response getCartridge(long id) throws JSONException {
        SQLiteDatabase db = db();
        try (Cursor c = db.rawQuery("SELECT * FROM cartridges WHERE id = ?",
                new String[]{String.valueOf(id)})) {
            if (!c.moveToFirst()) return new Response(404, fail("记录不存在"));
            return new Response(200, ok(rowToJson(c)));
        }
    }

    private Response priceHistory(long id) throws JSONException {
        SQLiteDatabase db = db();
        try (Cursor exists = db.rawQuery("SELECT 1 FROM cartridges WHERE id = ?",
                new String[]{String.valueOf(id)})) {
            if (!exists.moveToFirst()) return new Response(404, fail("记录不存在"));
        }
        JSONArray arr = new JSONArray();
        try (Cursor c = db.rawQuery(
                "SELECT price, changed_at FROM price_history"
                + " WHERE cartridge_id = ? ORDER BY changed_at ASC, id ASC",
                new String[]{String.valueOf(id)})) {
            while (c.moveToNext()) {
                JSONObject point = new JSONObject();
                point.put("price", c.getDouble(0));
                point.put("changed_at", c.getString(1));
                arr.put(point);
            }
        }
        return new Response(200, ok(arr));
    }

    // ── 写入 ────────────────────────────────────────────────────────────────

    private Response addCartridge(String jsonBody) throws JSONException {
        JSONObject body = parseBodyObject(jsonBody);
        if (body == null) return new Response(400, fail("请求体必须为 JSON"));
        Parsed fields = Parsed.parse(body, null);
        if (fields.error != null) return new Response(400, fail(fields.error));
        SQLiteDatabase db = db();
        db.beginTransaction();
        try {
            JSONObject record = insertRecord(db, fields);
            db.setTransactionSuccessful();
            return new Response(201, ok(record));
        } finally {
            db.endTransaction();
        }
    }

    private Response updateCartridge(long id, String jsonBody) throws JSONException {
        JSONObject body = parseBodyObject(jsonBody);
        if (body == null) return new Response(400, fail("请求体必须为 JSON"));
        SQLiteDatabase db = db();
        db.beginTransaction();
        try {
            JSONObject existing;
            try (Cursor c = db.rawQuery("SELECT * FROM cartridges WHERE id = ?",
                    new String[]{String.valueOf(id)})) {
                if (!c.moveToFirst()) {
                    return new Response(404, fail("记录不存在"));
                }
                existing = rowToJson(c);
            }
            double oldPrice = existing.optDouble("price", 0);
            Parsed fields = Parsed.parse(body, Parsed.fromExisting(existing));
            if (fields.error != null) return new Response(400, fail(fields.error));

            db.execSQL(
                    "UPDATE cartridges SET category = ?, name = ?, price = ?, notes = ?,"
                    + " source = ?, cover = ?, intro = ?, alias = ?,"
                    + " updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    new Object[]{fields.category, fields.name, fields.price, fields.notes,
                            fields.source, fields.cover, fields.intro, fields.alias, id});
            if (Math.abs(fields.price - oldPrice) > 1e-9) {
                recordPrice(db, id, fields.price, null);
            }
            JSONObject record;
            try (Cursor c = db.rawQuery("SELECT * FROM cartridges WHERE id = ?",
                    new String[]{String.valueOf(id)})) {
                c.moveToFirst();
                record = rowToJson(c);
            }
            db.setTransactionSuccessful();
            return new Response(200, ok(record));
        } finally {
            db.endTransaction();
        }
    }

    private Response deleteCartridge(long id) throws JSONException {
        SQLiteDatabase db = db();
        int rows = db.delete("cartridges", "id = ?", new String[]{String.valueOf(id)});
        if (rows == 0) return new Response(404, fail("记录不存在"));
        return new Response(200, okMessage("删除成功"));
    }

    private static JSONObject okMessage(String message) {
        try {
            JSONObject o = new JSONObject();
            o.put("success", true);
            o.put("message", message);
            return o;
        } catch (JSONException e) {
            throw new IllegalStateException(e);
        }
    }

    // ── CSV 导出 / 导入 ─────────────────────────────────────────────────────

    private JSONObject exportCsv() throws JSONException {
        StringBuilder sb = new StringBuilder("\uFEFF"); // UTF-8 BOM
        sb.append(String.join(",", CSV_FIELDS)).append("\r\n");
        SQLiteDatabase db = db();
        try (Cursor c = db.rawQuery(
                "SELECT * FROM cartridges ORDER BY updated_at DESC, id DESC", null)) {
            while (c.moveToNext()) {
                JSONObject row = rowToJson(c);
                String[] cells = new String[CSV_FIELDS.length];
                for (int i = 0; i < CSV_FIELDS.length; i++) {
                    String key = CSV_FIELDS[i];
                    cells[i] = key.equals("price")
                            ? String.valueOf(row.optDouble("price", 0))
                            : row.optString(key, "");
                }
                StringBuilder line = new StringBuilder();
                for (int i = 0; i < cells.length; i++) {
                    if (i > 0) line.append(',');
                    line.append(csvField(cells[i]));
                }
                sb.append(line).append("\r\n");
            }
        }
        String filename = "cartridges-"
                + new SimpleDateFormat("yyyyMMdd", Locale.US).format(new Date()) + ".csv";
        JSONObject data = new JSONObject();
        data.put("filename", filename);
        data.put("content", sb.toString());
        return ok(data);
    }

    private Response importCsv(String jsonBody) throws JSONException {
        JSONObject body = parseBodyObject(jsonBody);
        String text = body == null ? "" : body.optString("content", "");
        if (text.isEmpty()) text = body == null ? "" : body.optString("text", "");
        if (text.isEmpty()) return new Response(400, fail("请选择要导入的 CSV 文件"));

        List<List<String>> records = parseCsv(text);
        if (records.isEmpty()) return new Response(400, fail("CSV 缺少必需列：category、name"));
        List<String> header = records.get(0);
        Map<String, Integer> colIndex = new HashMap<>();
        for (int i = 0; i < header.size(); i++) colIndex.put(header.get(i).trim(), i);
        for (String required : new String[]{"category", "name"}) {
            if (!colIndex.containsKey(required)) {
                return new Response(400, fail("CSV 缺少必需列：category、name"));
            }
        }

        Set<String> existing = new HashSet<>();
        SQLiteDatabase db = db();
        db.beginTransaction();
        int imported = 0, skipped = 0, failed = 0;
        List<String> errors = new ArrayList<>();
        try {
            try (Cursor c = db.rawQuery("SELECT category, name FROM cartridges", null)) {
                while (c.moveToNext()) existing.add(c.getString(0) + "\u0001" + c.getString(1));
            }
            for (int r = 1; r < records.size(); r++) {
                List<String> row = records.get(r);
                int lineNo = r + 1;
                boolean anyNonBlank = false;
                for (String cell : row) {
                    if (cell != null && !cell.trim().isEmpty()) {
                        anyNonBlank = true;
                        break;
                    }
                }
                if (!anyNonBlank) continue;

                JSONObject rowBody = new JSONObject();
                for (String key : new String[]{"category", "name", "alias", "price",
                        "source", "cover", "intro", "notes", "created_at", "updated_at"}) {
                    Integer idx = colIndex.get(key);
                    if (idx != null) {
                        String cell = idx < row.size() ? row.get(idx) : null;
                        if (cell != null && !cell.isEmpty()) rowBody.put(key, cell);
                    }
                }
                Parsed fields = Parsed.parse(rowBody, null);
                if (fields.error != null) {
                    failed++;
                    if (errors.size() < 10) errors.add("第" + lineNo + "行：" + fields.error);
                    continue;
                }
                String key = fields.category + "\u0001" + fields.name;
                if (existing.contains(key)) {
                    skipped++;
                    continue;
                }
                insertRecord(db, fields);
                existing.add(key);
                imported++;
            }
            db.setTransactionSuccessful();
        } finally {
            db.endTransaction();
        }

        String message = "导入完成：新增 " + imported + " 条，跳过重复 " + skipped + " 条";
        if (failed > 0) message += "，失败 " + failed + " 条";
        JSONObject data = new JSONObject();
        data.put("imported", imported);
        data.put("skipped", skipped);
        data.put("failed", failed);
        data.put("errors", new JSONArray(errors));
        JSONObject result = new JSONObject();
        result.put("success", true);
        result.put("data", data);
        result.put("message", message);
        return new Response(200, result);
    }

    // ── 底层写入 ────────────────────────────────────────────────────────────

    private JSONObject insertRecord(SQLiteDatabase db, Parsed fields) throws JSONException {
        ContentValues values = new ContentValues();
        values.put("category", fields.category);
        values.put("name", fields.name);
        values.put("price", fields.price);
        values.put("notes", fields.notes);
        values.put("source", fields.source);
        values.put("cover", fields.cover);
        values.put("intro", fields.intro);
        values.put("alias", fields.alias);
        if (fields.createdAt != null) values.put("created_at", fields.createdAt);
        if (fields.updatedAt != null) values.put("updated_at", fields.updatedAt);
        long id = db.insert("cartridges", null, values);
        recordPrice(db, id, fields.price, fields.updatedAt != null
                ? fields.updatedAt : fields.createdAt);
        try (Cursor c = db.rawQuery("SELECT * FROM cartridges WHERE id = ?",
                new String[]{String.valueOf(id)})) {
            c.moveToFirst();
            return rowToJson(c);
        }
    }

    /** 写入一条价格历史：仅非零价；changed_at 用于 CSV 导入保真。 */
    private static void recordPrice(SQLiteDatabase db, long id, double price, String changedAt) {
        if (price <= 0) return;
        ContentValues values = new ContentValues();
        values.put("cartridge_id", id);
        values.put("price", price);
        if (changedAt != null) values.put("changed_at", changedAt);
        db.insert("price_history", null, values);
    }

    // ── 工具 ────────────────────────────────────────────────────────────────

    private static JSONObject parseBodyObject(String jsonBody) {
        if (jsonBody == null || jsonBody.trim().isEmpty()) return null;
        try {
            JSONObject o = new JSONObject(jsonBody);
            return o;
        } catch (JSONException e) {
            return null;
        }
    }

    private static JSONObject rowToJson(Cursor c) throws JSONException {
        JSONObject o = new JSONObject();
        String[] cols = c.getColumnNames();
        for (int i = 0; i < cols.length; i++) {
            switch (c.getType(i)) {
                case Cursor.FIELD_TYPE_INTEGER:
                    o.put(cols[i], c.getLong(i));
                    break;
                case Cursor.FIELD_TYPE_FLOAT:
                    o.put(cols[i], c.getDouble(i));
                    break;
                case Cursor.FIELD_TYPE_NULL:
                    o.put(cols[i], JSONObject.NULL);
                    break;
                default:
                    o.put(cols[i], c.getString(i));
            }
        }
        return o;
    }

    private static String escapeLike(String s) {
        return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_");
    }

    private static List<String> toStringList(List<Long> ids) {
        List<String> out = new ArrayList<>();
        for (long id : ids) out.add(String.valueOf(id));
        return out;
    }

    private static List<Long> idsOf(List<JSONObject> rows) throws JSONException {
        List<Long> ids = new ArrayList<>();
        for (JSONObject row : rows) ids.add(row.getLong("id"));
        return ids;
    }

    private Map<Long, Double> minPrices(List<Long> ids) {
        Map<Long, Double> out = new HashMap<>();
        if (ids.isEmpty()) return out;
        StringBuilder sql = new StringBuilder(
                "SELECT cartridge_id, MIN(price) AS min_price FROM price_history"
                + " WHERE cartridge_id IN (");
        List<String> args = new ArrayList<>();
        for (int i = 0; i < ids.size(); i++) sql.append(i == 0 ? "?" : ",?");
        sql.append(") GROUP BY cartridge_id");
        for (long id : ids) args.add(String.valueOf(id));
        SQLiteDatabase db = db();
        try (Cursor c = db.rawQuery(sql.toString(), args.toArray(new String[0]))) {
            while (c.moveToNext()) out.put(c.getLong(0), c.getDouble(1));
        }
        return out;
    }

    private static String csvField(String value) {
        String s = value == null ? "" : value;
        if (s.indexOf(',') >= 0 || s.indexOf('"') >= 0
                || s.indexOf('\n') >= 0 || s.indexOf('\r') >= 0) {
            return '"' + s.replace("\"", "\"\"") + '"';
        }
        return s;
    }

    /** RFC4180 风格 CSV 解析：支持引号字段、字段内逗号/换行、双写引号。 */
    private static List<List<String>> parseCsv(String text) {
        List<List<String>> records = new ArrayList<>();
        List<String> fields = new ArrayList<>();
        StringBuilder sb = new StringBuilder();
        boolean inQuotes = false;
        int i = 0;
        int n = text.length();
        while (i < n) {
            char ch = text.charAt(i);
            if (inQuotes) {
                if (ch == '"') {
                    if (i + 1 < n && text.charAt(i + 1) == '"') {
                        sb.append('"');
                        i += 2;
                    } else {
                        inQuotes = false;
                        i++;
                    }
                } else {
                    sb.append(ch);
                    i++;
                }
                continue;
            }
            if (ch == '"') {
                inQuotes = true;
                i++;
            } else if (ch == ',') {
                fields.add(sb.toString());
                sb.setLength(0);
                i++;
            } else if (ch == '\n' || ch == '\r') {
                if (ch == '\r' && i + 1 < n && text.charAt(i + 1) == '\n') i++;
                i++;
                fields.add(sb.toString());
                sb.setLength(0);
                records.add(fields);
                fields = new ArrayList<>();
            } else {
                sb.append(ch);
                i++;
            }
        }
        if (sb.length() > 0 || !fields.isEmpty() || inQuotes) {
            fields.add(sb.toString());
            records.add(fields);
        }
        return records;
    }

    // ── 字段校验（移植 records.parse_payload）──────────────────────────────

    /** 解析结果：校验失败时 error 非空。 */
    private static final class Parsed {
        String error;
        String category, name, notes, source, cover, intro, alias;
        double price;
        String createdAt, updatedAt;

        static Parsed fromExisting(JSONObject existing) throws JSONException {
            Parsed p = new Parsed();
            if (existing != null) {
                p.category = existing.optString("category", "");
                p.name = existing.optString("name", "");
                p.notes = existing.optString("notes", "");
                p.source = existing.optString("source", "");
                p.cover = existing.optString("cover", "");
                p.intro = existing.optString("intro", "");
                p.alias = existing.optString("alias", "");
                p.price = existing.optDouble("price", 0);
            }
            return p;
        }

        /** 返回 error 字符串，null 表示通过。 */
        static Parsed parse(JSONObject body, Parsed src) {
            Parsed p = fromExisting(null);
            Parsed s = src == null ? fromExisting(null) : src;
            p.category = nonEmptyOrNull(body, "category", s.category);
            p.name = nonEmptyOrNull(body, "name", s.name);
            p.notes = body.has("notes") ? body.optString("notes").trim()
                    : orEmpty(s.notes);
            p.source = body.has("source") ? body.optString("source").trim()
                    : orEmpty(s.source);
            p.cover = body.has("cover") ? body.optString("cover").trim()
                    : orEmpty(s.cover);
            p.intro = body.has("intro") ? body.optString("intro").trim()
                    : orEmpty(s.intro);
            p.alias = body.has("alias") ? body.optString("alias").trim()
                    : orEmpty(s.alias);

            if (p.category == null || p.category.isEmpty()) return err("分类必须为 NS 或 NS2");
            boolean valid = false;
            for (String c : VALID_CATEGORIES) {
                if (c.equals(p.category)) {
                    valid = true;
                    break;
                }
            }
            if (!valid) return err("分类必须为 NS 或 NS2");
            if (p.name == null || p.name.isEmpty()) return err("名称不能为空");
            if (p.source.length() > MAX_SOURCE_LENGTH) {
                return err("来源不能超过 " + MAX_SOURCE_LENGTH + " 个字符");
            }
            if (p.cover.length() > MAX_COVER_LENGTH) return err("封面引用无效");
            if (p.intro.length() > MAX_INTRO_LENGTH) {
                return err("介绍不能超过 " + MAX_INTRO_LENGTH + " 个字符");
            }
            if (p.alias.length() > MAX_ALIAS_LENGTH) {
                return err("别名不能超过 " + MAX_ALIAS_LENGTH + " 个字符");
            }

            Object raw = body.has("price") ? body.opt("price") : s.price;
            if (raw == null || (raw instanceof String && ((String) raw).trim().isEmpty())) {
                p.price = 0.0;
            } else if (raw instanceof Boolean) {
                return err("价格格式不正确");
            } else if (raw instanceof Number) {
                p.price = ((Number) raw).doubleValue();
            } else {
                try {
                    p.price = Double.parseDouble(((String) raw).trim());
                } catch (NumberFormatException e) {
                    return err("价格格式不正确");
                }
            }
            if (Double.isNaN(p.price) || Double.isInfinite(p.price) || p.price < 0) {
                return err("价格格式不正确");
            }

            for (String[] ts : new String[][]{
                    new String[]{"created_at", "createdAt"},
                    new String[]{"updated_at", "updatedAt"}}) {
                String value = body.has(ts[0]) ? body.optString(ts[0]).trim() : "";
                if (value.isEmpty()) continue;
                if (!TIMESTAMP_RE.matcher(value).matches()) {
                    return err("时间格式需为 YYYY-MM-DD HH:MM:SS");
                }
                if (ts[1].equals("createdAt")) p.createdAt = value;
                else p.updatedAt = value;
            }
            return p;
        }

        private static Parsed err(String message) {
            Parsed p = new Parsed();
            p.error = message;
            return p;
        }

        private static String nonEmptyOrNull(JSONObject body, String key, String fallback) {
            String v = body.has(key) ? body.optString(key).trim() : "";
            if (!v.isEmpty()) return v;
            return fallback == null ? "" : fallback;
        }

        private static String orEmpty(String v) {
            return v == null ? "" : v;
        }
    }

    // ── SQLite：建表 + 迁移链（移植 database.py）───────────────────────────

    private static final class Helper extends SQLiteOpenHelper {

        static final String DB_NAME = "prices.db";
        static final int SCHEMA_VERSION = 5;   // Helper 负责到 v5；v6 由 StorageBridge.db() 事务外惰性执行
        static final int SCHEMA_VERSION_V6 = 6;
        private final Context context;

        Helper(Context context) {
            super(context, DB_NAME, null, SCHEMA_VERSION);
            this.context = context;
        }

        Context getContext() {
            return context;
        }

        @Override
        public void onConfigure(SQLiteDatabase db) {
            super.onConfigure(db);
            db.setForeignKeyConstraintsEnabled(true);
            db.setWriteAheadLoggingEnabled(true);
        }

        @Override
        public void onCreate(SQLiteDatabase db) {
            migrate(db, 0);
        }

        @Override
        public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) {
            backupBeforeMigrate(db, oldVersion);
            migrate(db, oldVersion);
        }

        /**
         * v6 起版本号由 StorageBridge.db() 在事务外推进（库版本会高于
         * Helper 目标 5）。静默忽略该差异，避免被当作降级异常抛出。
         */
        @Override
        public void onDowngrade(SQLiteDatabase db, int oldVersion, int newVersion) {
            // 有意留空：见方法注释
        }

        /** 迁移前备份旧库（与 database.py 行为一致）；空库/失败不阻塞迁移。 */
        void backupBeforeMigrate(SQLiteDatabase db, int oldVersion) {
            try {
                try (Cursor c = db.rawQuery(
                        "SELECT 1 FROM sqlite_master WHERE type='table'"
                        + " AND name NOT LIKE 'sqlite_%' LIMIT 1", null)) {
                    if (!c.moveToFirst()) return;
                }
                db.execSQL("PRAGMA wal_checkpoint(TRUNCATE)");
                File dbFile = context.getDatabasePath(DB_NAME);
                File backup = context.getDatabasePath("prices.backup-v" + oldVersion + ".db");
                if (dbFile.exists() && !backup.exists()) {
                    copyFile(dbFile, backup);
                }
            } catch (Exception e) {
                // 备份失败不阻塞迁移（与桌面端不同：移动端无法交互确认）
            }
        }

        private static void copyFile(File src, File dst) throws IOException {
            try (FileInputStream in = new FileInputStream(src);
                 FileOutputStream out = new FileOutputStream(dst)) {
                byte[] buf = new byte[8192];
                int n;
                while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
            }
        }

        private static void migrate(SQLiteDatabase db, int fromVersion) {
            for (int v = fromVersion + 1; v <= SCHEMA_VERSION; v++) {
                applyVersion(db, v);
            }
            db.execSQL("PRAGMA user_version = " + SCHEMA_VERSION);
        }

        private static void applyVersion(SQLiteDatabase db, int v) {
            switch (v) {
                case 1:
                    db.execSQL(TABLE_SQL);
                    db.execSQL("CREATE INDEX IF NOT EXISTS idx_cartridges_name"
                            + " ON cartridges(name)");
                    db.execSQL("CREATE INDEX IF NOT EXISTS idx_cartridges_category"
                            + " ON cartridges(category)");
                    db.execSQL("CREATE INDEX IF NOT EXISTS idx_cartridges_updated_at"
                            + " ON cartridges(updated_at)");
                    break;
                case 2:
                    addColumnIfMissing(db, "source", "TEXT NOT NULL DEFAULT ''");
                    db.execSQL("CREATE INDEX IF NOT EXISTS idx_cartridges_source"
                            + " ON cartridges(source)");
                    break;
                case 3:
                    addColumnIfMissing(db, "cover", "TEXT NOT NULL DEFAULT ''");
                    addColumnIfMissing(db, "intro", "TEXT NOT NULL DEFAULT ''");
                    break;
                case 4:
                    db.execSQL("CREATE TABLE IF NOT EXISTS price_history ("
                            + "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                            + " cartridge_id INTEGER NOT NULL"
                            + " REFERENCES cartridges(id) ON DELETE CASCADE,"
                            + " price REAL NOT NULL,"
                            + " changed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)");
                    db.execSQL("CREATE INDEX IF NOT EXISTS idx_price_history_cartridge"
                            + " ON price_history(cartridge_id)");
                    db.execSQL("INSERT INTO price_history (cartridge_id, price, changed_at)"
                            + " SELECT id, price, updated_at FROM cartridges WHERE price > 0");
                    break;
                case 5:
                    addColumnIfMissing(db, "alias", "TEXT NOT NULL DEFAULT ''");
                    break;
                default:
                    break;
            }
        }

        private static void addColumnIfMissing(SQLiteDatabase db, String column, String decl) {
            try (Cursor c = db.rawQuery("PRAGMA table_info(cartridges)", null)) {
                while (c.moveToNext()) {
                    if (column.equals(c.getString(c.getColumnIndexOrThrow("name")))) return;
                }
            }
            db.execSQL("ALTER TABLE cartridges ADD COLUMN " + column + " " + decl);
        }
    }
}
