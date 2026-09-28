/**
 * Switch 卡带价格统计 — 前端交互逻辑
 */

// ── 常量（服务端注入，前后端单一数据源）────────────────────────────────────
const SOURCE_PRESETS = window.__APP__.sourcePresets || [];
const SOURCE_CUSTOM = "__custom__";
const SOURCE_CLASS = {
    "拼多多福袋": "src-fudai",
    "拼多多V3": "src-v3",
    "支付宝刷券": "src-zfb",
};

// 安卓壳（file:// 协议）下走原生存储桥；?native=1 供浏览器模拟测试
const NATIVE_MODE =
    location.protocol === "file:" ||
    new URLSearchParams(location.search).has("native");

// 内置游戏库：桌面端从 /api/games/catalog 加载（服务端内存直出）；
// 安卓壳由打包期生成的 games.js 提供（window.__GAMES__，见 android/prepare_assets.py）
let GAMES = [];
const GAMES_INDEX = {};
let GAMES_SEARCH = [];

function buildGamesIndex() {
    for (const g of GAMES) GAMES_INDEX[g.i] = g;
    // 预归一化搜索字段（约 2 万款 × 若干字段，避免每次键入重复正则）
    GAMES_SEARCH = GAMES.map((g) => {
        const fields = [g.t];
        if (g.zh) fields.push(g.zh);
        if (g.zhs) fields.push(g.zhs);
        if (g.zs) fields.push(...g.zs);
        return { g, fields: fields.map(normText) };
    });
}

// 微任务里初始化：buildGamesIndex 依赖文件后部定义的 normText
const gamesReady = NATIVE_MODE
    ? Promise.resolve().then(() => {
          GAMES = Array.isArray(window.__GAMES__) ? window.__GAMES__ : [];
          buildGamesIndex();
      })
    : fetch("/api/games/catalog")
          .then((res) => (res.ok ? res.json() : { data: [] }))
          .then((result) => {
              GAMES = Array.isArray(result.data) ? result.data : [];
              buildGamesIndex();
          })
          .catch(() => {}); // 加载失败时游戏库功能降级为空，记录功能不受影响

/** 封面地址：桌面端走 /cover/<id>（内置资源→缓存→在线）；安卓端用内置资产封面。 */
function coverUrl(gameId) {
    return NATIVE_MODE
        ? `covers/${encodeURIComponent(gameId)}.jpg`
        : `/cover/${encodeURIComponent(gameId)}`;
}

/**
 * 封面加载失败的回退链：安卓壳内置封面缺失时切换到在线官方地址；
 * 在线也失败（或非安卓环境）返回 false，由调用方移除/隐藏元素。
 */
function coverImgError(img, gameId) {
    const game = gameId ? GAMES_INDEX[gameId] : null;
    if (NATIVE_MODE && game && game.c && img.dataset.onlineFallback !== "1") {
        img.dataset.onlineFallback = "1";
        img.src = game.c;
        return true;
    }
    return false;
}
window.coverImgError = coverImgError; // 供内联 onerror 调用

// ── State ──────────────────────────────────────────────────────────────────
let cartridges = [];
let sortField = "updated_at";
let sortDir = "desc";
let deleteTargetId = null;
let suggestTimer = null;
let suggestData = [];
let suggestSeq = 0;      // 联想请求序号：丢弃过期的慢响应，防止旧结果覆盖新输入
let selectedGame = null; // 新增/编辑弹窗中关联的内置游戏条目
let introDraft = "";     // 待提交的游戏介绍
let detailRecord = null; // 详情弹窗当前记录

// ── DOM refs ───────────────────────────────────────────────────────────────
const $ = (sel) => document.querySelector(sel);
const tableBody = $("#tableBody");
const cardList = $("#cardList");
const statsBar = $("#statsBar");
const searchInput = $("#searchInput");
const categoryFilter = $("#categoryFilter");
const sourceFilter = $("#sourceFilter");
const filterToggle = $("#filterToggle");
const filterPanel = $("#filterPanel");
const mobileSort = $("#mobileSort");
const fabAdd = $("#fabAdd");
const modalOverlay = $("#modalOverlay");
const modalTitle = $("#modalTitle");
const cartridgeForm = $("#cartridgeForm");
const confirmOverlay = $("#confirmOverlay");
const detailOverlay = $("#detailOverlay");
const toast = $("#toast");
const formName = $("#formName");
const formAlias = $("#formAlias");
const formPrice = $("#formPrice");
const formCategory = $("#formCategory");
const formSource = $("#formSource");
const formSourceCustom = $("#formSourceCustom");
const formNotes = $("#formNotes");
const themeToggle = $("#themeToggle");
const editIdInput = $("#editId");
const submitBtn = $("#submitBtn");
const suggestDropdown = $("#suggestDropdown");
const gameChip = $("#gameChip");
const gameChipTitle = $("#gameChipTitle");
const gameChipMeta = $("#gameChipMeta");
const gameChipCover = $("#gameChipCover");

// ── 来源选项 ───────────────────────────────────────────────────────────────
function buildSourceOptions() {
    formSource.innerHTML = "";
    formSource.appendChild(new Option("未指定", ""));
    for (const s of SOURCE_PRESETS) {
        formSource.appendChild(new Option(s, s));
    }
    formSource.appendChild(new Option("其他（填写）", SOURCE_CUSTOM));
    refreshSourceFilter();
}

/** 来源筛选下拉 = 预设来源 + 记录里出现过的自定义来源（此前只填了「全部来源」，筛选形同虚设） */
function refreshSourceFilter() {
    const current = sourceFilter.value;
    const sources = new Set(SOURCE_PRESETS);
    for (const c of cartridges) {
        if (c.source) sources.add(c.source);
    }
    sourceFilter.innerHTML = "";
    sourceFilter.appendChild(new Option("全部来源", ""));
    for (const s of sources) {
        sourceFilter.appendChild(new Option(s, s));
    }
    sourceFilter.value = sources.has(current) ? current : "";
}

function sourceClass(name) {
    return SOURCE_CLASS[name] || "src-custom";
}

function syncSourceCustomVisibility() {
    formSourceCustom.style.display =
        formSource.value === SOURCE_CUSTOM ? "block" : "none";
}

/** 根据记录里的来源值回填表单（预设 → 下拉；自定义 → 其他 + 文本框）。 */
function setFormSource(value) {
    if (!value) {
        formSource.value = "";
    } else if (SOURCE_PRESETS.includes(value)) {
        formSource.value = value;
    } else {
        formSource.value = SOURCE_CUSTOM;
        formSourceCustom.value = value;
    }
    syncSourceCustomVisibility();
}

/** 读取表单里的最终来源值。 */
function readFormSource() {
    return formSource.value === SOURCE_CUSTOM
        ? formSourceCustom.value.trim()
        : formSource.value;
}

// ── 游戏库关联 ─────────────────────────────────────────────────────────────
const CJK_RE = /[\u4e00-\u9fff]/;
// 先删 ™®©（NFKC 会把 ™ 展开成 tm），再折叠全角（皮克敏４→皮克敏4）、小写、去空白
const normText = (s) =>
    (s || "")
        .replace(/[™®©]/g, "")
        .normalize("NFKC")
        .toLowerCase()
        .replace(/\s+/g, "");

/** 中文名：简体化名优先，其次港服繁体名，最后英文名。 */
function gameDisplayName(g) {
    return g.zhs || g.zh || g.t;
}

/**
 * 搜索内置游戏库：英文名 / 繁体中文名 / 简体化名 / 人工别名。
 * 前缀命中优先于包含命中；含中文的短名（如别名「耀西」）允许反向包含，
 * 输入「耀西与不可思议图鉴」也能命中；同分按标题长度升序（正统作品优先）。
 */
function searchGames(keyword, limit = 6) {
    const q = normText(keyword);
    if (!q) return [];
    const ranked = [];
    for (const { g, fields } of GAMES_SEARCH) {
        let rank = null;
        for (const f of fields) {
            if (!f) continue;
            if (f.includes(q)) {
                rank = Math.min(rank ?? 2, f.startsWith(q) ? 0 : 1);
            } else if (f.length >= 2 && CJK_RE.test(f) && q.includes(f)) {
                rank = Math.min(rank ?? 2, 1);
            }
        }
        if (rank !== null) ranked.push([rank, g]);
    }
    ranked.sort((a, b) => a[0] - b[0] || a[1].t.length - b[1].t.length);
    return ranked.slice(0, limit).map(([, g]) => g);
}

/** 游戏条目的英文名（与显示名不同时用于副标题）。 */
function gameSubtitle(g) {
    const display = gameDisplayName(g);
    return display === g.t ? "" : g.t;
}

function renderGameChip() {
    if (!selectedGame) {
        gameChip.style.display = "none";
        return;
    }
    gameChip.style.display = "flex";
    gameChipTitle.textContent = gameDisplayName(selectedGame);
    const meta = [gameSubtitle(selectedGame), selectedGame.p, selectedGame.dt].filter(Boolean);
    gameChipMeta.textContent = meta.join(" · ") || "已关联内置游戏库";
    gameChipCover.src = coverUrl(selectedGame.i);
    gameChipCover.style.display = "";
    gameChipCover.onerror = () => {
        gameChipCover.style.display = "none";
    };
}

function pickGame(game) {
    selectedGame = game;
    // 繁体中文介绍优先（港服数据），没有再用英文
    introDraft = game.zi || game.d || "";
    // 联想选中后自动用全称覆盖输入框（如「塞尔达」→「塞尔达传说 旷野之息」）
    formName.value = gameDisplayName(game);
    renderGameChip();
    hideSuggest();
}

function clearGame() {
    selectedGame = null;
    introDraft = "";
    renderGameChip();
}

// ── API helpers ────────────────────────────────────────────────────────────
async function api(path, options = {}) {
    if (NATIVE_MODE) return nativeApi(path, options);
    // 非 JSON 响应（如 500 的 HTML 错误页）或网络失败统一降级，
    // 调用方按 result.success 分支即可
    try {
        const res = await fetch(path, {
            headers: { "Content-Type": "application/json" },
            ...options,
        });
        return await res.json();
    } catch {
        return { success: false, message: "网络错误，请重试" };
    }
}

/**
 * 安卓壳：REST 语义直连 StorageBridge（SQLite）。
 * 桥同步返回 {"status", "body"}，这里包装成与 fetch 一致的 Promise 形态。
 */
function nativeApi(path, options = {}) {
    return new Promise((resolve) => {
        const method = (options.method || "GET").toUpperCase();
        const [pathOnly, query = ""] = path.split("?");
        let envelope;
        try {
            envelope = JSON.parse(
                window.GameLedgerBridge.request(
                    method, pathOnly, query,
                    options.body ? String(options.body) : ""
                )
            );
        } catch {
            resolve({ success: false, message: "本地存储不可用" });
            return;
        }
        let body = envelope && envelope.body;
        if (typeof body === "string") {
            try {
                body = JSON.parse(body);
            } catch {
                /* 保留原文，由下方统一兜底 */
            }
        }
        resolve(
            body && typeof body === "object" && "success" in body
                ? body
                : { success: false, message: "本地存储响应异常" }
        );
    });
}

// ── Toast ──────────────────────────────────────────────────────────────────
function showToast(message, type = "success") {
    toast.textContent = message;
    toast.className = `toast ${type} show`;
    clearTimeout(toast._timeout);
    toast._timeout = setTimeout(() => {
        toast.classList.remove("show");
    }, 2500);
}

// ── Load & Render ──────────────────────────────────────────────────────────
async function loadData() {
    const search = searchInput.value.trim();
    const category = categoryFilter.value;
    const source = sourceFilter.value;
    const params = new URLSearchParams();
    if (search) params.set("search", search);
    if (category) params.set("category", category);
    if (source) params.set("source", source);

    const result = await api(`/api/cartridges?${params.toString()}`);
    if (result.success) {
        cartridges = result.data;
        sortData();
        renderTable();
        refreshSourceFilter(); // 记录里的自定义来源进筛选下拉
    }
}

function sortData() {
    cartridges.sort((a, b) => {
        let va = a[sortField];
        let vb = b[sortField];
        if (va == null) va = "";
        if (vb == null) vb = "";
        if (typeof va === "number" && typeof vb === "number") {
            return sortDir === "asc" ? va - vb : vb - va;
        }
        va = String(va).toLowerCase();
        vb = String(vb).toLowerCase();
        if (va < vb) return sortDir === "asc" ? -1 : 1;
        if (va > vb) return sortDir === "asc" ? 1 : -1;
        return 0;
    });
}

function renderTable() {
    renderStats();

    if (cartridges.length === 0) {
        tableBody.innerHTML =
            '<tr><td colspan="8" class="empty-state">暂无数据，点击「＋ 新增卡带」开始添加</td></tr>';
        cardList.innerHTML =
            '<div class="empty-state card-empty">暂无数据，点右下角 ＋ 开始添加</div>';
        return;
    }

    tableBody.innerHTML = cartridges
        .map(
            (c) => `
            <tr>
                <td class="cover-cell">
                    <div class="cover-thumb${c.cover ? "" : " empty"}">${
                        c.cover
                            ? `<img loading="lazy" src="${coverUrl(c.cover)}" onerror="if(!coverImgError(this,'${esc(c.cover)}'))this.remove()">`
                            : ""
                    }</div>
                </td>
                <td class="category-cell"><span class="category-tag ${c.category.toLowerCase()}">${esc(c.category)}</span></td>
                <td>
                    <span class="name-link" data-id="${c.id}" title="查看详情">${esc(c.name)}</span>${
                        c.alias
                            ? `<span class="name-alias" title="别名：${esc(c.alias)}">${esc(c.alias)}</span>`
                            : ""
                    }
                </td>
                <td class="price-cell">¥${formatPrice(c.price)}</td>
                <td>${
                    c.source
                        ? `<span class="source-tag ${sourceClass(c.source)}">${esc(c.source)}</span>`
                        : '<span class="muted">—</span>'
                }</td>
                <td class="notes-cell" title="${esc(c.notes || "")}">${esc(c.notes || "-")}</td>
                <td>${formatDate(c.updated_at)}</td>
                <td class="actions-col">
                    <button class="btn btn-secondary btn-sm edit-btn" data-id="${c.id}">编辑</button>
                    <button class="btn btn-danger btn-sm delete-btn" data-id="${c.id}">删除</button>
                </td>
            </tr>`
        )
        .join("");

    renderCards();

    // 绑定事件（表格与卡片共用选择器）
    bindRecordEvents(tableBody);
    bindRecordEvents(cardList);
}

/** 窄屏卡片列表：封面 + 名称/别名 + 价格/来源/时间 + 操作。 */
function renderCards() {
    cardList.innerHTML = cartridges
        .map(
            (c) => `
        <div class="card-item">
            <div class="card-cover">
                <div class="cover-thumb${c.cover ? "" : " empty"}">${
                    c.cover
                        ? `<img loading="lazy" src="${coverUrl(c.cover)}" onerror="if(!coverImgError(this,'${esc(c.cover)}'))this.remove()">`
                        : ""
                }</div>
            </div>
            <div class="card-main">
                <div class="card-title-row">
                    <span class="name-link" data-id="${c.id}">${esc(c.name)}</span>
                    <span class="category-tag ${c.category.toLowerCase()}">${esc(c.category)}</span>
                </div>
                ${
                    c.alias
                        ? `<div class="card-alias" title="别名：${esc(c.alias)}">${esc(c.alias)}</div>`
                        : ""
                }
                ${
                    c.notes
                        ? `<div class="card-notes" title="${esc(c.notes)}">${esc(c.notes)}</div>`
                        : ""
                }
                <div class="card-meta-row">
                    <span class="card-price">¥${formatPrice(c.price)}</span>
                    ${
                        c.source
                            ? `<span class="source-tag ${sourceClass(c.source)}">${esc(c.source)}</span>`
                            : ""
                    }
                </div>
                <div class="card-date">${formatDate(c.updated_at)}</div>
            </div>
            <div class="card-actions">
                <button class="btn-icon edit-btn" data-id="${c.id}" aria-label="编辑" title="编辑">✎</button>
                <button class="btn-icon btn-icon-danger delete-btn" data-id="${c.id}" aria-label="删除" title="删除">✕</button>
            </div>
        </div>`
        )
        .join("");
}

/** 记录列表事件绑定：编辑/删除/名称点详情（表格与卡片共用）。 */
function bindRecordEvents(scope) {
    scope.querySelectorAll(".edit-btn").forEach((btn) => {
        btn.addEventListener("click", () => openEditModal(parseInt(btn.dataset.id)));
    });
    scope.querySelectorAll(".delete-btn").forEach((btn) => {
        btn.addEventListener("click", () => openDeleteConfirm(parseInt(btn.dataset.id)));
    });
    scope.querySelectorAll(".name-link").forEach((el) => {
        el.addEventListener("click", () => openDetailModal(parseInt(el.dataset.id)));
    });
}

function renderStats() {
    // 统计卡片
    const nsCount = cartridges.filter((c) => c.category === "NS").length;
    const ns2Count = cartridges.filter((c) => c.category === "NS2").length;
    const totalCost = cartridges.reduce((sum, c) => sum + (parseFloat(c.price) || 0), 0);

    $("#statTotal").textContent = cartridges.length;
    $("#statNS").textContent = nsCount;
    $("#statNS2").textContent = ns2Count;
    $("#statCost").textContent = "¥" + formatMoney(totalCost);

    // 来源分布（仅显示有记录的来源）
    const counts = {};
    for (const c of cartridges) {
        if (c.source) counts[c.source] = (counts[c.source] || 0) + 1;
    }
    const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]);
    statsBar.innerHTML = entries.length
        ? "来源分布：" +
          entries
              .map(
                  ([name, n]) =>
                      `<span class="source-tag ${sourceClass(name)}">${esc(name)} × ${n}</span>`
              )
              .join(" ")
        : "";
}

// ── Helpers ────────────────────────────────────────────────────────────────
function esc(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

function formatPrice(p) {
    const n = parseFloat(p);
    if (isNaN(n)) return "0.00";
    return n.toFixed(2);
}

function formatMoney(n) {
    return n.toLocaleString("zh-CN", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    });
}

function formatDate(d) {
    if (!d) return "-";
    const dt = new Date(d + (d.includes("Z") ? "" : "Z"));
    if (isNaN(dt.getTime())) return d;
    const pad = (n) => String(n).padStart(2, "0");
    return `${dt.getFullYear()}-${pad(dt.getMonth() + 1)}-${pad(dt.getDate())} ${pad(
        dt.getHours()
    )}:${pad(dt.getMinutes())}`;
}

// ── Modal: Add / Edit ──────────────────────────────────────────────────────
function openAddModal() {
    modalTitle.textContent = "新增卡带";
    cartridgeForm.reset();
    editIdInput.value = "";
    formSourceCustom.value = "";
    formAlias.value = "";
    submitBtn.textContent = "保存";
    clearGame();
    syncSourceCustomVisibility();
    suggestData = [];
    hideSuggest();
    modalOverlay.classList.add("active");
    formCategory.focus();
}

function openEditModal(id) {
    const record = cartridges.find((c) => c.id === id);
    if (!record) return;
    modalTitle.textContent = "编辑卡带";
    editIdInput.value = record.id;
    formCategory.value = record.category;
    formName.value = record.name;
    formAlias.value = record.alias || "";
    formPrice.value = record.price;
    formSourceCustom.value = "";
    setFormSource(record.source || "");
    formNotes.value = record.notes || "";
    selectedGame = record.cover ? GAMES_INDEX[record.cover] || { i: record.cover, t: record.name, d: record.intro || "" } : null;
    introDraft = record.intro || "";
    renderGameChip();
    submitBtn.textContent = "更新";
    suggestData = [];
    hideSuggest();
    modalOverlay.classList.add("active");
}

function closeModal() {
    modalOverlay.classList.remove("active");
    suggestData = [];
    hideSuggest();
}

async function submitForm(e) {
    e.preventDefault();
    if (submitBtn.disabled) return; // 防止连击造成重复记录

    const id = editIdInput.value;
    const category = formCategory.value;
    const name = formName.value.trim();
    const alias = formAlias.value.trim();
    const price = formPrice.value;
    const source = readFormSource();
    const notes = formNotes.value.trim();

    if (!category || !name) {
        showToast("请填写分类和名称", "error");
        return;
    }
    if (formSource.value === SOURCE_CUSTOM && !source) {
        showToast("请填写自定义来源名称", "error");
        return;
    }

    const body = {
        category,
        name,
        alias,
        price: price === "" ? 0 : parseFloat(price),
        notes,
        source,
        cover: selectedGame ? selectedGame.i : "",
        intro: introDraft,
    };

    submitBtn.disabled = true;
    try {
        let result;
        if (id) {
            result = await api(`/api/cartridges/${id}`, {
                method: "PUT",
                body: JSON.stringify(body),
            });
        } else {
            result = await api("/api/cartridges", {
                method: "POST",
                body: JSON.stringify(body),
            });
        }

        if (result.success) {
            showToast(id ? "更新成功！" : "添加成功！");
            closeModal();
            loadData();
        } else {
            showToast(result.message || "操作失败", "error");
        }
    } finally {
        submitBtn.disabled = false;
    }
}

// ── Suggest / Autocomplete ─────────────────────────────────────────────────
function hideSuggest() {
    suggestSeq++; // 使在途的联想响应失效
    suggestDropdown.classList.remove("active");
    suggestDropdown.innerHTML = "";
    suggestData = [];
}

async function onNameInput() {
    // Only trigger in add mode (no editId)
    if (editIdInput.value) {
        hideSuggest();
        return;
    }

    const q = formName.value.trim();
    if (!q) {
        hideSuggest();
        return;
    }

    const seq = suggestSeq + 1;
    suggestSeq = seq;
    await gamesReady; // 游戏目录异步加载，联想前等待（本地接口，毫秒级）
    if (seq !== suggestSeq) return; // 输入已变化或下拉已关闭，丢弃过期响应
    const [recordsResult, gameMatches] = await Promise.all([
        api(`/api/cartridges/suggest?q=${encodeURIComponent(q)}`),
        Promise.resolve(searchGames(q)),
    ]);
    if (seq !== suggestSeq) return; // 输入已变化或下拉已关闭，丢弃过期响应

    suggestData = recordsResult.success ? recordsResult.data : [];
    renderSuggest(gameMatches);
}

function renderSuggest(gameMatches = []) {
    if (!suggestData.length && !gameMatches.length) {
        hideSuggest();
        return;
    }

    const inputPrice = formPrice.value.trim() !== "" ? parseFloat(formPrice.value) : null;

    let html = "";

    if (suggestData.length) {
        html += '<div class="suggest-section">已有记录</div>';
        html += suggestData
            .map((item) => {
                const existingPrice = item.price || 0;
                let compareHtml = "";
                if (inputPrice !== null && !isNaN(inputPrice)) {
                    const diff = inputPrice - existingPrice;
                    if (diff > 0.01) {
                        compareHtml = `<span class="suggest-compare price-up">涨 ¥${diff.toFixed(2)}</span>`;
                    } else if (diff < -0.01) {
                        compareHtml = `<span class="suggest-compare price-down">降 ¥${Math.abs(diff).toFixed(2)}</span>`;
                    } else {
                        compareHtml = `<span class="suggest-compare price-same">价格持平</span>`;
                    }
                }
                // 历史最低价：输入价不高于历史最低时提示划算
                const minPrice = item.min_price;
                let minHtml = "";
                if (minPrice != null && inputPrice !== null && !isNaN(inputPrice)) {
                    if (inputPrice <= minPrice + 0.01) {
                        minHtml = `<span class="suggest-compare price-down">低于历史最低 ¥${formatPrice(minPrice)}</span>`;
                    } else if (minPrice < existingPrice - 0.01) {
                        minHtml = `<span class="suggest-compare price-same">历史最低 ¥${formatPrice(minPrice)}</span>`;
                    }
                }
                return `
                <div class="suggest-item" data-id="${item.id}">
                    <span class="suggest-name">${esc(item.name)}</span>
                    <span class="category-tag ${item.category.toLowerCase()}">${esc(item.category)}</span>
                    <span class="suggest-existing">已有 ¥${formatPrice(item.price)}</span>
                    ${compareHtml}
                    ${minHtml}
                    <span class="suggest-hint">→ 更新此记录</span>
                </div>`;
            })
            .join("");
    }

    if (gameMatches.length) {
        html += '<div class="suggest-section">内置游戏库 · 点击关联封面与介绍</div>';
        html += gameMatches
            .map(
                (g) => {
                    const subtitle = gameSubtitle(g);
                    const subHtml = subtitle
                        ? `<span class="suggest-en">${esc(subtitle)}</span>`
                        : "";
                    return `
                <div class="suggest-item game-item" data-game="${esc(g.i)}">
                    <span class="suggest-game-cover"><img loading="lazy" src="${coverUrl(g.i)}" onerror="if(!coverImgError(this,'${esc(g.i)}'))this.remove()"></span>
                    <span class="suggest-name">${esc(gameDisplayName(g))}${subHtml}</span>
                    <span class="suggest-existing">${esc(g.p || "")}</span>
                    <span class="suggest-hint">→ 关联</span>
                </div>`;
                }
            )
            .join("");
    }

    suggestDropdown.innerHTML = html;
    suggestDropdown.classList.add("active");

    suggestDropdown.querySelectorAll(".suggest-item[data-id]").forEach((el) => {
        el.addEventListener("click", () => fillFromSuggest(parseInt(el.dataset.id)));
    });
    suggestDropdown.querySelectorAll(".suggest-item.game-item").forEach((el) => {
        el.addEventListener("click", () => {
            const game = GAMES_INDEX[el.dataset.game];
            if (game) pickGame(game);
        });
    });
}

function fillFromSuggest(id) {
    const record = suggestData.find((item) => item.id === id);
    if (!record) return;

    editIdInput.value = record.id;
    formCategory.value = record.category;
    formName.value = record.name;
    formAlias.value = record.alias || "";
    // Keep user's price if entered, otherwise use existing
    if (formPrice.value.trim() === "" || parseFloat(formPrice.value) === 0) {
        formPrice.value = record.price;
    }
    formSourceCustom.value = "";
    setFormSource(record.source || "");
    formNotes.value = record.notes || "";
    selectedGame = record.cover ? GAMES_INDEX[record.cover] || { i: record.cover, t: record.name, d: record.intro || "" } : null;
    introDraft = record.intro || "";
    renderGameChip();
    modalTitle.textContent = "更新卡带";
    submitBtn.textContent = "更新";
    hideSuggest();
}

// ── Detail modal ───────────────────────────────────────────────────────────
let detailChartSeq = 0; // 详情切换序号：丢弃过期走势响应

async function loadPriceHistory(record) {
    const box = $("#detailChart");
    const seq = ++detailChartSeq;
    box.style.display = "none";
    if (!record) return;

    const result = await api(`/api/cartridges/${record.id}/history`);
    const points = result.success ? result.data : [];
    if (seq !== detailChartSeq || !points.length) return; // 详情已切换或无历史

    const prices = points.map((p) => p.price);
    const min = Math.min(...prices);
    const max = Math.max(...prices);

    // SVG 走势：横向铺满容器，上下留边距；单点只画标记
    const W = 300;
    const H = 64;
    const PAD = 6;
    let poly = "";
    if (points.length > 1) {
        const stepX = (W - PAD * 2) / (points.length - 1);
        poly = points
            .map((p, i) => {
                const y =
                    max === min
                        ? H / 2
                        : PAD + ((max - p.price) / (max - min)) * (H - PAD * 2);
                return `${(PAD + i * stepX).toFixed(1)},${y.toFixed(1)}`;
            })
            .join(" ");
    }

    box.innerHTML = `
        <div class="detail-chart-title">价格走势<span class="detail-chart-meta">最低 ¥${formatPrice(min)} · 最高 ¥${formatPrice(max)} · 共 ${points.length} 次</span></div>
        <svg class="chart-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
            ${
                poly
                    ? `<polyline points="${poly}" fill="none" style="stroke: var(--primary)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
                       <circle cx="${poly.split(" ").at(-1).split(",")[0]}" cy="${poly.split(" ").at(-1).split(",")[1]}" r="3" style="fill: var(--primary)"/>`
                    : `<circle cx="${W / 2}" cy="${H / 2}" r="3.5" style="fill: var(--primary)"/>`
            }
        </svg>`;
    box.style.display = "";
}

function openDetailModal(id) {
    const record = cartridges.find((c) => c.id === id);
    if (!record) return;
    detailRecord = record;

    $("#detailName").textContent = record.name;
    $("#detailCover").style.display = record.cover ? "" : "none";
    $("#detailCover").src = record.cover ? coverUrl(record.cover) : "";
    $("#detailCover").onerror = () => {
        // 安卓壳内置封面缺失时回退在线官方地址，仍失败才隐藏
        if (!coverImgError($("#detailCover"), record.cover)) {
            $("#detailCover").style.display = "none";
        }
    };

    const tags = [
        `<span class="category-tag ${record.category.toLowerCase()}">${esc(record.category)}</span>`,
        record.source
            ? `<span class="source-tag ${sourceClass(record.source)}">${esc(record.source)}</span>`
            : "",
    ].filter(Boolean);
    $("#detailTags").innerHTML = tags.join(" ");

    const rows = [
        ["价格", `¥${formatPrice(record.price)}`],
        ["录入时间", formatDate(record.created_at)],
        ["更新时间", formatDate(record.updated_at)],
    ];
    if (record.alias) {
        rows.splice(1, 0, ["别名", esc(record.alias)]);
    }
    $("#detailRows").innerHTML = rows
        .map(([k, v]) => `<div class="detail-row"><span>${k}</span><span>${v}</span></div>`)
        .join("");

    loadPriceHistory(record);

    const game = record.cover ? GAMES_INDEX[record.cover] : null;
    // 繁体中文介绍优先：记录里存的是英文自动介绍时，换用目录里的繁体介绍；
    // 用户手动编辑过的介绍（与目录原文不同）保持原样
    let intro = record.intro || "";
    if (game && game.zi && (!intro || intro === game.d)) {
        intro = game.zi;
    } else if (!intro && game) {
        intro = game.d;
    }
    const introBox = $("#detailIntro");
    if (intro) {
        introBox.style.display = "";
        introBox.innerHTML =
            `<div class="detail-intro-title">游戏介绍${game ? "" : ""}</div>` +
            `<p>${esc(intro)}</p>` +
            (game
                ? `<div class="detail-intro-meta">${esc(game.p || "")}${
                      game.g ? " · " + esc(game.g) : ""
                  }${game.dt ? " · " + esc(game.dt) : ""}</div>`
                : "");
    } else {
        introBox.style.display = "none";
        introBox.innerHTML = "";
    }

    detailOverlay.classList.add("active");
}

function closeDetailModal() {
    detailChartSeq++; // 使在途的走势响应失效
    detailRecord = null;
    detailOverlay.classList.remove("active");
}

// ── Delete confirmation ────────────────────────────────────────────────────
function openDeleteConfirm(id) {
    deleteTargetId = id;
    confirmOverlay.classList.add("active");
}

function closeDeleteConfirm() {
    deleteTargetId = null;
    confirmOverlay.classList.remove("active");
}

async function confirmDelete() {
    if (!deleteTargetId) return;
    const result = await api(`/api/cartridges/${deleteTargetId}`, {
        method: "DELETE",
    });
    if (result.success) {
        showToast("删除成功！");
        closeDeleteConfirm();
        loadData();
    } else {
        showToast(result.message || "删除失败", "error");
    }
}

// ── Sorting ────────────────────────────────────────────────────────────────
function handleSort(field) {
    if (sortField === field) {
        sortDir = sortDir === "asc" ? "desc" : "asc";
    } else {
        sortField = field;
        sortDir = "asc";
    }
    // 更新表头样式
    document.querySelectorAll("th.sortable").forEach((th) => {
        th.classList.remove("sorted-asc", "sorted-desc");
        if (th.dataset.sort === field) {
            th.classList.add(sortDir === "asc" ? "sorted-asc" : "sorted-desc");
        }
    });
    // 同步移动端排序下拉（category/source 不在选项里时跳过）
    if ([...mobileSort.options].some((o) => o.value === sortField)) {
        mobileSort.value = sortField;
    }
    sortData();
    renderTable();
}

// ── Event bindings ─────────────────────────────────────────────────────────
$("#searchBtn").addEventListener("click", loadData);
$("#resetBtn").addEventListener("click", () => {
    searchInput.value = "";
    categoryFilter.value = "";
    sourceFilter.value = "";
    mobileSort.value = "updated_at";
    sortField = "updated_at";
    sortDir = "desc";
    loadData();
});
searchInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") loadData();
});
categoryFilter.addEventListener("change", loadData);
sourceFilter.addEventListener("change", loadData);

// 筛选面板折叠（窄屏）：默认收起，点「筛选」展开
filterToggle.addEventListener("click", () => {
    const open = filterPanel.classList.toggle("open");
    filterToggle.classList.toggle("active", open);
    filterToggle.setAttribute("aria-expanded", String(open));
});

// 移动端排序（卡片列表无表头）：字段切换，名称升序其余降序
mobileSort.addEventListener("change", () => {
    sortField = mobileSort.value;
    sortDir = sortField === "name" ? "asc" : "desc";
    sortData();
    renderTable();
});

$("#addBtn").addEventListener("click", openAddModal);
fabAdd.addEventListener("click", openAddModal);

// ── CSV 导出 / 导入 ────────────────────────────────────────────────────────
$("#exportBtn").addEventListener("click", async () => {
    if (NATIVE_MODE) {
        // 安卓壳：经存储桥取 CSV 文本，由原生层写入系统下载目录
        const result = await api("/api/export/csv");
        const data = result.success && result.data;
        if (!data) {
            showToast(result.message || "导出失败", "error");
            return;
        }
        const saved = window.GameLedgerBridge.saveFile(
            data.filename, "text/csv; charset=utf-8", data.content
        );
        showToast(
            saved ? `已导出到：${saved}` : "导出失败，请重试",
            saved ? "success" : "error"
        );
        return;
    }
    window.location.href = "/api/export/csv";
});

$("#importBtn").addEventListener("click", () => $("#importFile").click());

/** 读文本文件（FileReader，兼容旧 WebView；file.text() 在 minSdk 24 旧内核上不可靠）。 */
function readFileText(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result));
        reader.onerror = () => reject(reader.error);
        reader.readAsText(file, "utf-8");
    });
}

$("#importFile").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    e.target.value = ""; // 允许连续导入同一个文件
    if (!file) return;
    try {
        let result;
        if (NATIVE_MODE) {
            // 安卓壳：无 multipart，读文件文本后以 JSON 提交
            const content = await readFileText(file);
            result = await api("/api/import/csv", {
                method: "POST",
                body: JSON.stringify({ content }),
            });
        } else {
            const fd = new FormData();
            fd.append("file", file);
            const res = await fetch("/api/import/csv", { method: "POST", body: fd });
            result = await res.json();
        }
        if (result.success) {
            const firstError = result.data && result.data.errors && result.data.errors[0];
            showToast(firstError ? `${result.message}；${firstError}` : result.message, "success");
            loadData();
        } else {
            showToast(result.message || "导入失败", "error");
        }
    } catch {
        showToast("导入失败，请重试", "error");
    }
});
$("#modalClose").addEventListener("click", closeModal);
$("#cancelBtn").addEventListener("click", closeModal);
modalOverlay.addEventListener("click", (e) => {
    if (e.target === modalOverlay) closeModal();
});
cartridgeForm.addEventListener("submit", submitForm);
formSource.addEventListener("change", syncSourceCustomVisibility);
$("#gameChipRemove").addEventListener("click", clearGame);

// Detail events
$("#detailClose").addEventListener("click", closeDetailModal);
$("#detailCloseBtn").addEventListener("click", closeDetailModal);
detailOverlay.addEventListener("click", (e) => {
    if (e.target === detailOverlay) closeDetailModal();
});
$("#detailEditBtn").addEventListener("click", () => {
    const id = detailRecord && detailRecord.id;
    closeDetailModal();
    if (id) openEditModal(id);
});

// Suggest events
formName.addEventListener("input", () => {
    clearTimeout(suggestTimer);
    suggestTimer = setTimeout(onNameInput, 300);
});
formPrice.addEventListener("input", () => {
    if (suggestData.length) renderSuggest();
});
document.addEventListener("click", (e) => {
    if (!suggestDropdown.contains(e.target) && e.target !== formName) {
        hideSuggest();
    }
});

$("#confirmCancel").addEventListener("click", closeDeleteConfirm);
$("#confirmDelete").addEventListener("click", confirmDelete);
confirmOverlay.addEventListener("click", (e) => {
    if (e.target === confirmOverlay) closeDeleteConfirm();
});

document.querySelectorAll("th.sortable").forEach((th) => {
    th.addEventListener("click", () => handleSort(th.dataset.sort));
});

// ── Keyboard shortcuts ─────────────────────────────────────────────────────
document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
        if (confirmOverlay.classList.contains("active")) {
            closeDeleteConfirm();
        } else if (detailOverlay.classList.contains("active")) {
            closeDetailModal();
        } else if (modalOverlay.classList.contains("active")) {
            closeModal();
        }
    }
    if (e.ctrlKey && e.key === "k") {
        e.preventDefault();
        searchInput.focus();
    }
});

// ── 安卓返回键（由 MainActivity 注入调用）──────────────────────────────────
// 返回 true 表示前端已消费（关闭了弹层），false 交给壳做 WebView 后退/退出
window.__onBackPressed = function () {
    if (confirmOverlay.classList.contains("active")) {
        closeDeleteConfirm();
    } else if (detailOverlay.classList.contains("active")) {
        closeDetailModal();
    } else if (modalOverlay.classList.contains("active")) {
        closeModal();
    } else {
        return false;
    }
    return true;
};

// ── 主题切换（深色/浅色）──────────────────────────────────────────────────
// 首帧主题已在 <head> 内联脚本里确定（无闪烁）；太阳/月亮图标由 CSS
// 按主题切换（SVG 在方框内精确居中），这里只同步提示文字
function syncThemeButton() {
    const light = document.documentElement.dataset.theme === "light";
    themeToggle.title = light ? "切换到深色模式" : "切换到浅色模式";
}
themeToggle.addEventListener("click", () => {
    const root = document.documentElement;
    const next = root.dataset.theme === "light" ? "dark" : "light";
    root.classList.add("theming"); // 短暂启用全局颜色过渡，切换更顺滑
    root.dataset.theme = next;
    try {
        localStorage.setItem("swpt-theme", next);
    } catch {
        /* localStorage 不可用时本次会话内切换仍生效 */
    }
    syncThemeButton();
    setTimeout(() => root.classList.remove("theming"), 400);
});
syncThemeButton();

// ── Init ───────────────────────────────────────────────────────────────────
buildSourceOptions();
syncSourceCustomVisibility();
loadData();
