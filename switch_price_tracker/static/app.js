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

// 内置游戏库（由 games.js 提供，含 id/标题/介绍/封面URL/热度）
const GAMES = window.__GAMES__ || [];
const GAMES_INDEX = {};
for (const g of GAMES) GAMES_INDEX[g.i] = g;

/** 封面地址：桌面端走 /cover/<id>（内置资源→缓存→在线）；安卓分支覆盖此函数。 */
function coverUrl(gameId) {
    return `/cover/${encodeURIComponent(gameId)}`;
}

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
const statsBar = $("#statsBar");
const searchInput = $("#searchInput");
const categoryFilter = $("#categoryFilter");
const sourceFilter = $("#sourceFilter");
const modalOverlay = $("#modalOverlay");
const modalTitle = $("#modalTitle");
const cartridgeForm = $("#cartridgeForm");
const confirmOverlay = $("#confirmOverlay");
const detailOverlay = $("#detailOverlay");
const toast = $("#toast");
const formName = $("#formName");
const formPrice = $("#formPrice");
const formCategory = $("#formCategory");
const formSource = $("#formSource");
const formSourceCustom = $("#formSourceCustom");
const formNotes = $("#formNotes");
const editIdInput = $("#editId");
const submitBtn = $("#submitBtn");
const suggestDropdown = $("#suggestDropdown");
const gameChip = $("#gameChip");
const gameChipTitle = $("#gameChipTitle");
const gameChipMeta = $("#gameChipMeta");
const gameChipCover = $("#gameChipCover");

// ── 来源选项 ───────────────────────────────────────────────────────────────
function buildSourceOptions() {
    for (const filter of [sourceFilter, formSource]) {
        filter.innerHTML = "";
    }
    sourceFilter.appendChild(new Option("全部来源", ""));
    formSource.appendChild(new Option("未指定", ""));
    for (const s of SOURCE_PRESETS) {
        formSource.appendChild(new Option(s, s));
    }
    formSource.appendChild(new Option("其他（填写）", SOURCE_CUSTOM));
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
function searchGames(keyword, limit = 6) {
    const q = (keyword || "").trim().toLowerCase();
    if (!q) return [];
    const matched = [];
    for (const g of GAMES) {
        const t = g.t.toLowerCase();
        if (t.includes(q)) matched.push(g);
    }
    // 前缀匹配优先，其次更短标题（正统作品通常比合集/长尾条目短）
    matched.sort((a, b) => {
        const ap = a.t.toLowerCase().startsWith(q) ? 0 : 1;
        const bp = b.t.toLowerCase().startsWith(q) ? 0 : 1;
        if (ap !== bp) return ap - bp;
        return a.t.length - b.t.length;
    });
    return matched.slice(0, limit);
}

function renderGameChip() {
    if (!selectedGame) {
        gameChip.style.display = "none";
        return;
    }
    gameChip.style.display = "flex";
    gameChipTitle.textContent = selectedGame.t;
    const meta = [selectedGame.p, selectedGame.dt].filter(Boolean).join(" · ");
    gameChipMeta.textContent = meta || "已关联内置游戏库";
    gameChipCover.src = coverUrl(selectedGame.i);
    gameChipCover.style.display = "";
    gameChipCover.onerror = () => {
        gameChipCover.style.display = "none";
    };
}

function pickGame(game) {
    selectedGame = game;
    introDraft = game.d || "";
    if (!formName.value.trim()) formName.value = game.t;
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
    const res = await fetch(path, {
        headers: { "Content-Type": "application/json" },
        ...options,
    });
    return res.json();
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
        return;
    }

    tableBody.innerHTML = cartridges
        .map(
            (c) => `
            <tr>
                <td class="cover-cell">
                    <div class="cover-thumb${c.cover ? "" : " empty"}">${
                        c.cover
                            ? `<img loading="lazy" src="${coverUrl(c.cover)}" onerror="this.remove()">`
                            : ""
                    }</div>
                </td>
                <td><span class="category-tag ${c.category.toLowerCase()}">${esc(c.category)}</span></td>
                <td><span class="name-link" data-id="${c.id}" title="查看详情">${esc(c.name)}</span></td>
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

    // 绑定事件
    tableBody.querySelectorAll(".edit-btn").forEach((btn) => {
        btn.addEventListener("click", () => openEditModal(parseInt(btn.dataset.id)));
    });
    tableBody.querySelectorAll(".delete-btn").forEach((btn) => {
        btn.addEventListener("click", () => openDeleteConfirm(parseInt(btn.dataset.id)));
    });
    tableBody.querySelectorAll(".name-link").forEach((el) => {
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
                return `
                <div class="suggest-item" data-id="${item.id}">
                    <span class="suggest-name">${esc(item.name)}</span>
                    <span class="category-tag ${item.category.toLowerCase()}">${esc(item.category)}</span>
                    <span class="suggest-existing">已有 ¥${formatPrice(item.price)}</span>
                    ${compareHtml}
                    <span class="suggest-hint">→ 更新此记录</span>
                </div>`;
            })
            .join("");
    }

    if (gameMatches.length) {
        html += '<div class="suggest-section">内置游戏库 · 点击关联封面与介绍</div>';
        html += gameMatches
            .map(
                (g) => `
                <div class="suggest-item game-item" data-game="${esc(g.i)}">
                    <span class="suggest-game-cover"><img loading="lazy" src="${coverUrl(g.i)}" onerror="this.remove()"></span>
                    <span class="suggest-name">${esc(g.t)}</span>
                    <span class="suggest-existing">${esc(g.p || "")}</span>
                    <span class="suggest-hint">→ 关联</span>
                </div>`
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
function openDetailModal(id) {
    const record = cartridges.find((c) => c.id === id);
    if (!record) return;
    detailRecord = record;

    $("#detailName").textContent = record.name;
    $("#detailCover").style.display = record.cover ? "" : "none";
    $("#detailCover").src = record.cover ? coverUrl(record.cover) : "";
    $("#detailCover").onerror = () => {
        $("#detailCover").style.display = "none";
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
    $("#detailRows").innerHTML = rows
        .map(([k, v]) => `<div class="detail-row"><span>${k}</span><span>${v}</span></div>`)
        .join("");

    const game = record.cover ? GAMES_INDEX[record.cover] : null;
    const intro = record.intro || (game ? game.d : "");
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
    sortData();
    renderTable();
}

// ── Event bindings ─────────────────────────────────────────────────────────
$("#searchBtn").addEventListener("click", loadData);
$("#resetBtn").addEventListener("click", () => {
    searchInput.value = "";
    categoryFilter.value = "";
    sourceFilter.value = "";
    loadData();
});
searchInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") loadData();
});
categoryFilter.addEventListener("change", loadData);
sourceFilter.addEventListener("change", loadData);

$("#addBtn").addEventListener("click", openAddModal);
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

// ── Init ───────────────────────────────────────────────────────────────────
buildSourceOptions();
syncSourceCustomVisibility();
loadData();
