"use strict";

// Fully static: reads insights.json directly (no server / API).
const state = {
  insights: [],
  generatedAt: null,
  dates: [],
  selectedDate: null,
  cat: "",
  q: "",
  lang: "zh",
  modalItem: null,
  sources: null,
};

const $ = (sel) => document.querySelector(sel);

const CATEGORY_LABEL = {
  macro: "宏观",
  tech: "科技",
  politics: "政治",
  volatility: "波动率",
  other: "其他",
  "bbg-tv-news": "BBG TV",
};
const SENTIMENT_LABEL = { positive: "偏多", negative: "偏空", neutral: "中性" };
const KIND_LABEL = { podcast: "播客", video: "视频", article: "文章" };

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

// Backward-compatible category accessor (old data used a single `category`).
function categories(it) {
  if (Array.isArray(it.categories)) return it.categories;
  if (it.category) return [it.category];
  return [];
}

function detailOf(it) {
  const d = state.lang === "zh" ? it.detail_zh : it.detail_en;
  const s = state.lang === "zh" ? it.summary_zh : it.summary_en;
  return d || s || "";
}

async function init() {
  try {
    const resp = await fetch("insights.json", { cache: "no-store" });
    const data = await resp.json();
    state.insights = data.insights || [];
    state.generatedAt = data.generated_at;
  } catch (e) {
    $("#state").textContent = "加载数据失败：" + e.message;
    return;
  }

  buildDates();
  state.selectedDate = state.dates[0]?.date || null;
  render();
}

function buildDates() {
  const map = {};
  for (const it of state.insights) {
    const d = (it.published_at || "").slice(0, 10);
    if (d) map[d] = (map[d] || 0) + 1;
  }
  state.dates = Object.keys(map).sort().reverse().map((d) => ({ date: d, count: map[d] }));
}

function filtered() {
  const q = state.q.toLowerCase();
  return state.insights.filter((it) => {
    if (state.selectedDate && (it.published_at || "").slice(0, 10) !== state.selectedDate) return false;
    if (state.cat && !categories(it).includes(state.cat)) return false;
    if (q) {
      const hay = [
        it.title, it.title_zh, it.summary_zh, it.summary_en, it.detail_zh, it.detail_en,
        it.source_name, (it.tags || []).join(" "), (it.tickers || []).join(" "),
      ].join(" ").toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

function updateLangToggles() {
  document.querySelectorAll(".lang-toggle [data-lang]").forEach((b) => {
    b.classList.toggle("active", b.dataset.lang === state.lang);
  });
}

function render() {
  updateLangToggles();
  $("#dateLabel").textContent = state.selectedDate || "全部";
  const idx = state.dates.findIndex((d) => d.date === state.selectedDate);
  $("#prevDay").disabled = idx === -1 || idx >= state.dates.length - 1;
  $("#nextDay").disabled = idx === -1 || idx <= 0;

  if (state.generatedAt) {
    $("#lastUpdated").textContent = "数据更新于 " + new Date(state.generatedAt).toLocaleString("zh-CN");
  }

  const list = filtered();
  $("#countBadge").textContent = `${list.length} 条`;
  const grid = $("#grid");

  if (!list.length) {
    grid.innerHTML = '<div class="state">当日无相关内容。</div>';
    return;
  }
  grid.innerHTML = list.map(renderCard).join("");
}

function catBadges(it) {
  return categories(it).map((c) => `<span class="cat-badge cat-${esc(c)}">${CATEGORY_LABEL[c] || c}</span>`).join("");
}

function renderCard(it) {
  const kind = it.source_kind || "article";
  const titleZh = it.title_zh || it.title || "";
  const titleEn = it.title || "";
  const showSub = titleZh && titleEn && titleZh !== titleEn;
  const summary = state.lang === "zh" ? it.summary_zh : it.summary_en;
  const tickers = it.tickers || [];
  const sentiment = it.sentiment || "neutral";
  const dateStr = (it.published_at || "").slice(0, 10);

  return `
  <article class="card" data-id="${esc(it.guid || "")}">
    <div class="card-head">
      <span class="src-dot ${kind}"></span>
      <span class="src-name">${esc(it.source_name)}</span>
      ${catBadges(it)}
      <span class="src-date">${esc(dateStr)}</span>
    </div>
    <h3 class="card-title">
      <a href="${esc(it.url || "#")}" target="_blank" rel="noopener">${esc(titleZh)}</a>
    </h3>
    ${showSub ? `<p class="card-sub">${esc(titleEn)}</p>` : ""}
    <p class="summary">${esc(summary || "—")}</p>
    <div class="chips-row">
      <span class="sentiment ${sentiment}">${SENTIMENT_LABEL[sentiment] || sentiment}</span>
      ${tickers.map((t) => `<span class="ticker">${esc(t)}</span>`).join("")}
    </div>
    <div class="card-more">点击查看详情 →</div>
  </article>`;
}

function renderModal() {
  const it = state.modalItem;
  if (!it) return;
  updateLangToggles();
  const titleZh = it.title_zh || it.title || "";
  const titleEn = it.title || "";
  $("#modalSrc").textContent = it.source_name + " · " + (it.published_at || "").slice(0, 10);
  $("#modalTitle").textContent = titleZh;
  $("#modalSub").textContent = titleZh !== titleEn ? titleEn : "";
  $("#modalDetail").textContent = detailOf(it) || "—";

  const points = (it.key_points || [])
    .map((p) => (state.lang === "zh" ? p.zh : p.en))
    .filter(Boolean);
  $("#modalPoints").innerHTML = points.length
    ? points.map((p) => `<li>${esc(p)}</li>`).join("")
    : "";

  const tickers = (it.tickers || []).map((t) => `<span class="ticker">${esc(t)}</span>`).join("");
  const tags = (it.tags || []).map((t) => `<span class="tag">${esc(t)}</span>`).join("");
  $("#modalChips").innerHTML = catBadges(it) +
    `<span class="sentiment ${esc(it.sentiment || "neutral")}">${SENTIMENT_LABEL[it.sentiment] || it.sentiment}</span>` +
    tickers + tags;

  $("#modalLink").href = it.url || "#";
  $("#modalLink").style.display = it.url ? "inline-block" : "none";
}

function openModal(it) {
  state.modalItem = it;
  renderModal();
  $("#modal").hidden = false;
  document.body.style.overflow = "hidden";
}

function closeModal() {
  $("#modal").hidden = true;
  state.modalItem = null;
  document.body.style.overflow = "";
}

async function openSources() {
  try {
    if (!state.sources) {
      const resp = await fetch("sources.json", { cache: "no-store" });
      const data = await resp.json();
      state.sources = data.sources || [];
    }
  } catch (e) {
    state.sources = [];
  }
  $("#sourcesList").innerHTML = state.sources.map(renderSource).join("");
  $("#sourcesModal").hidden = false;
  document.body.style.overflow = "hidden";
}

function closeSources() {
  $("#sourcesModal").hidden = true;
  document.body.style.overflow = "";
}

function renderSource(s) {
  const kind = s.kind || "article";
  const cat = s.category || "other";
  return `
  <li class="source-item">
    <span class="src-dot ${kind}"></span>
    <a class="source-name" href="${esc(s.url || "#")}" target="_blank" rel="noopener">${esc(s.name)}</a>
    <span class="cat-badge cat-${esc(cat)}">${CATEGORY_LABEL[cat] || cat}</span>
    <span class="source-kind">${KIND_LABEL[kind] || kind}</span>
    ${s.note ? `<span class="source-note">${esc(s.note)}</span>` : ""}
  </li>`;
}

function shiftDate(dir) {
  const idx = state.dates.findIndex((d) => d.date === state.selectedDate);
  const target = idx + dir;
  if (target >= 0 && target < state.dates.length) {
    state.selectedDate = state.dates[target].date;
    render();
  }
}

// Events
$("#prevDay").addEventListener("click", () => shiftDate(1));
$("#nextDay").addEventListener("click", () => shiftDate(-1));
$("#todayBtn").addEventListener("click", () => {
  state.selectedDate = state.dates[0]?.date || null;
  render();
});

$("#catChips").addEventListener("click", (e) => {
  const chip = e.target.closest(".chip");
  if (!chip) return;
  state.cat = chip.dataset.cat;
  document.querySelectorAll("#catChips .chip").forEach((c) => c.classList.remove("active"));
  chip.classList.add("active");
  render();
});

let searchTimer;
$("#searchInput").addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    state.q = e.target.value.trim();
    render();
  }, 200);
});

// Open modal on card click (but not on links / lang toggles)
document.addEventListener("click", (e) => {
  const langBtn = e.target.closest("[data-lang]");
  if (langBtn) {
    state.lang = langBtn.dataset.lang;
    if (state.modalItem) renderModal();
    else render();
    return;
  }
  const card = e.target.closest(".card");
  if (card && !e.target.closest("a")) {
    const guid = card.dataset.id;
    const it = state.insights.find((x) => (x.guid || "") === guid);
    if (it) openModal(it);
  }
});

$("#modalClose").addEventListener("click", closeModal);
$("#modal").addEventListener("click", (e) => {
  if (e.target === $("#modal")) closeModal();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    closeModal();
    closeSources();
  }
});

$("#sourcesBtn").addEventListener("click", openSources);
$("#sourcesClose").addEventListener("click", closeSources);
$("#sourcesModal").addEventListener("click", (e) => {
  if (e.target === $("#sourcesModal")) closeSources();
});

init();
