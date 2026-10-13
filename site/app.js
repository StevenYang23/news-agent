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
};

const $ = (sel) => document.querySelector(sel);

const CATEGORY_LABEL = {
  macro: "宏观",
  tech: "科技",
  politics: "政治",
  other: "其他",
  "bbg-tv-news": "BBG TV",
};
const SENTIMENT_LABEL = { positive: "偏多", negative: "偏空", neutral: "中性" };

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
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
    if (state.cat && it.category !== state.cat) return false;
    if (q) {
      const hay = [
        it.title, it.title_zh, it.summary_zh, it.summary_en, it.source_name,
        (it.tags || []).join(" "), (it.tickers || []).join(" "),
      ].join(" ").toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

function render() {
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
    grid.innerHTML = '<div class="state">这一天没有相关美股 insight（或已被 30 天窗口过滤）。</div>';
    return;
  }
  grid.innerHTML = list.map(renderCard).join("");
}

function renderCard(it) {
  const kind = it.source_kind || "article";
  const cat = it.category || "other";
  const titleZh = it.title_zh || it.title || "";
  const titleEn = it.title || "";
  const showSub = titleZh && titleEn && titleZh !== titleEn;
  const summary = state.lang === "zh" ? it.summary_zh : it.summary_en;
  const points = (it.key_points || []).map((p) => (state.lang === "zh" ? p.zh : p.en)).filter(Boolean);
  const tags = it.tags || [];
  const tickers = it.tickers || [];
  const sentiment = it.sentiment || "neutral";
  const dateStr = (it.published_at || "").slice(0, 10);

  return `
  <article class="card">
    <div class="card-head">
      <span class="src-dot ${kind}"></span>
      <span class="src-name">${esc(it.source_name)}</span>
      <span class="cat-badge cat-${esc(cat)}">${CATEGORY_LABEL[cat] || cat}</span>
      <span class="src-date">${esc(dateStr)}</span>
    </div>
    <div class="lang-toggle">
      <button class="${state.lang === "zh" ? "active" : ""}" data-lang="zh">中</button>
      <button class="${state.lang === "en" ? "active" : ""}" data-lang="en">EN</button>
    </div>
    <h3 class="card-title">
      <a href="${esc(it.url || "#")}" target="_blank" rel="noopener">${esc(titleZh)}</a>
    </h3>
    ${showSub ? `<p class="card-sub">${esc(titleEn)}</p>` : ""}
    <p class="summary">${esc(summary || "—")}</p>
    ${points.length ? `<ul class="keypoints">${points.map((p) => `<li>${esc(p)}</li>`).join("")}</ul>` : ""}
    <div class="chips-row">
      <span class="sentiment ${sentiment}">${SENTIMENT_LABEL[sentiment] || sentiment}</span>
      ${tickers.map((t) => `<span class="ticker">${esc(t)}</span>`).join("")}
      ${tags.map((t) => `<span class="tag">${esc(t)}</span>`).join("")}
    </div>
  </article>`;
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

document.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-lang]");
  if (!btn) return;
  state.lang = btn.dataset.lang;
  render();
});

init();
