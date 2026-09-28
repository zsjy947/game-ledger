/**
 * NATIVE_MODE 端到端冒烟测试（Node + jsdom）。
 *
 * 用安卓壳构建产物（android/app/src/main/assets/www）验证：
 * index.html + games.js + app.js 在 file:// 语义下能通过模拟的
 * GameLedgerBridge 完成 列表加载 → 渲染 → 提交新增 → 删除 全流程。
 *
 * 用法：node tests/native_smoke.mjs（在 /tmp/gl-jsdom 下运行，
 *       环境变量 GL_WWW 指向 www 目录）
 */
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const JSDOM_DIR = process.env.GL_JSDOM_DIR; // jsdom 所在目录（npm install jsdom 的位置）
if (!JSDOM_DIR) {
  console.error("GL_JSDOM_DIR not set");
  process.exit(2);
}
const require2 = createRequire(join(JSDOM_DIR, "package.json"));
const { JSDOM } = require2("jsdom");

const WWW = process.env.GL_WWW;
if (!WWW) {
  console.error("GL_WWW not set");
  process.exit(2);
}

const html = readFileSync(join(WWW, "index.html"), "utf-8");
const gamesJs = readFileSync(join(WWW, "games.js"), "utf-8");
const appJs = readFileSync(join(WWW, "app.js"), "utf-8");

// ── 模拟 SQLite 后端（与 StorageBridge 语义一致的最小实现）─────────────────
const db = {
  seq: 3,
  now: "2026-09-29 00:00:00",
  rows: [
    { id: 1, category: "NS", name: "塞尔达传说 旷野之息", alias: "野炊", price: 185.5, notes: "", source: "拼多多福袋", cover: "", intro: "", created_at: "2026-09-28 10:00:00", updated_at: "2026-09-28 10:00:00" },
    { id: 2, category: "NS2", name: "马力欧卡丁车 世界", alias: "", price: 359, notes: "", source: "", cover: "", intro: "", created_at: "2026-09-28 11:00:00", updated_at: "2026-09-28 11:00:00" },
  ],
  history: { 1: [{ price: 185.5, changed_at: "2026-09-28 10:00:00" }] },
};

function listRows(params) {
  let rows = db.rows.slice();
  const search = params.get("search");
  const category = params.get("category");
  const source = params.get("source");
  if (search) rows = rows.filter((r) => r.name.includes(search) || r.alias.includes(search));
  if (category) rows = rows.filter((r) => r.category === category);
  if (source) rows = rows.filter((r) => r.source === source);
  rows.sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)));
  return rows;
}

function request(method, path, query, jsonBody) {
  const params = new URLSearchParams(query || "");
  const body = jsonBody ? JSON.parse(jsonBody) : {};
  const ok = (data) => JSON.stringify({ status: 200, body: { success: true, data } });
  const idMatch = path.match(/^\/api\/cartridges\/(\d+)$/);

  if (path === "/api/cartridges" && method === "GET") {
    const rows = listRows(params);
    for (const r of rows) r.min_price = (db.history[r.id] || []).length ? Math.min(...db.history[r.id].map((h) => h.price)) : null;
    return ok(rows);
  }
  if (path === "/api/cartridges/suggest" && method === "GET") {
    return ok([]);
  }
  if (path === "/api/cartridges" && method === "POST") {
    const record = { id: ++db.seq, created_at: db.now, updated_at: db.now, notes: "", source: "", cover: "", intro: "", alias: "", price: 0, ...body };
    db.rows.push(record);
    if (record.price > 0) db.history[record.id] = [{ price: record.price, changed_at: db.now }];
    return JSON.stringify({ status: 201, body: { success: true, data: record } });
  }
  if (idMatch && method === "DELETE") {
    const id = Number(idMatch[1]);
    db.rows = db.rows.filter((r) => r.id !== id);
    return JSON.stringify({ status: 200, body: { success: true, message: "删除成功" } });
  }
  if (idMatch && /\.history$/.test(path) === false && method === "GET") {
    const row = db.rows.find((r) => r.id === Number(idMatch[1]));
    return row ? ok(row) : JSON.stringify({ status: 404, body: { success: false, message: "记录不存在" } });
  }
  if (path.endsWith("/history") && method === "GET") {
    const id = Number(path.split("/")[3]);
    return ok(db.history[id] || []);
  }
  return JSON.stringify({ status: 404, body: { success: false, message: "接口不存在" } });
}

// ── jsdom 装载 www 页面 ────────────────────────────────────────────────────
const dom = new JSDOM(html, {
  url: "file:///android_asset/www/index.html", // 触发 NATIVE_MODE
  runScripts: "outside-only",
  pretendToBeVisual: true,
});
const { window } = dom;

window.GameLedgerBridge = {
  request,
  saveFile: (filename) => `/Downloads/${filename}`,
};
window.requestAnimationFrame = (fn) => setTimeout(fn, 0);
// index.html 的内联注入脚本在 outside-only 模式下不会执行，这里手动补上
window.__APP__ = {
  version: "1.0.0-test",
  sourcePresets: ["拼多多福袋", "拼多多V3", "支付宝刷券"],
  categories: [
    { value: "NS", label: "NS 卡带", class: "ns" },
    { value: "NS2", label: "NS2 卡带", class: "ns2" },
    { value: "PS4", label: "PS4 光盘", class: "ps4" },
    { value: "PS5", label: "PS5 光盘", class: "ps5" },
  ],
};

// 依 index.html 的脚本顺序执行：games.js（内联文本）→ app.js
window.eval(gamesJs);
window.eval(appJs);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const $ = (sel) => window.document.querySelector(sel);
const results = [];
const check = (name, cond) => {
  results.push([name, !!cond]);
  console.log(`${cond ? "PASS" : "FAIL"}  ${name}`);
};

await sleep(300); // 等 loadData 渲染

check("NATIVE_MODE 生效（卡片渲染）", $("#cardList").textContent.includes("塞尔达传说"));
check("分类下拉动态生成（含 PS5）", [...$("#formCategory").options].some((o) => o.value === "PS5"));
check("统计卡动态生成（PS4 卡片存在）", $("#statCat-ps4") !== null);
check("游戏库已加载（19579 款）", Array.isArray(window.__GAMES__) && window.__GAMES__.length > 10000);
check("游戏搜索可用（索引已构建）", typeof window.searchGames === "function" && window.searchGames("塞尔达").length > 0);
check("统计卡：总数 = 2", $("#statTotal").textContent === "2");
check("统计卡：总花费 544.50", $("#statCost").textContent.includes("544.50"));

// 模拟新增：填表 → 提交
$("#fabAdd").dispatchEvent(new window.Event("click"));
await sleep(50);
$("#formCategory").value = "NS";
$("#formName").value = "喷射战士3";
$("#formPrice").value = "149.9";
$("#cartridgeForm").dispatchEvent(new window.Event("submit", { cancelable: true }));
await sleep(300); // 等 nativeApi + loadData 回刷

check("新增后总数 = 3", $("#statTotal").textContent === "3");
check("新增记录出现在卡片列表", $("#cardList").textContent.includes("喷射战士3"));
check("价格历史写入（模拟桥内校验）", db.history[db.seq] && db.history[db.seq][0].price === 149.9);

// 模拟删除第一条
const firstDelete = $("#cardList .delete-btn");
firstDelete.dispatchEvent(new window.Event("click"));
await sleep(50);
$("#confirmDelete").dispatchEvent(new window.Event("click"));
await sleep(300);
check("删除后总数 = 2", $("#statTotal").textContent === "2");

// 返回键处理函数已暴露
check("__onBackPressed 已暴露", typeof window.__onBackPressed === "function");
check("返回键：无弹层时返回 false", window.__onBackPressed() === false);
$("#fabAdd").dispatchEvent(new window.Event("click"));
await sleep(50);
check("返回键：抽屉打开时返回 true 并关闭", window.__onBackPressed() === true && !$("#modalOverlay").classList.contains("active"));

const failed = results.filter(([, ok]) => !ok);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
process.exit(failed.length ? 1 : 0);
