const CATEGORIES = [
  "all",
  "system",
  "telegram_client",
  "release_monitor",
  "download",
  "dub_detector",
  "sonarr",
  "bot",
];

const LEVELS = ["all", "debug", "info", "warning", "error"];
const HIGHLIGHT_EVENTS = new Set([
  "match",
  "download_finished",
  "download_failed",
  "dub_discovered",
]);

const state = {
  category: "all",
  level: "all",
  events: [],
};

function matchesFilters(event) {
  if (state.category !== "all" && event.category !== state.category) return false;
  if (state.level !== "all" && event.level !== state.level) return false;
  return true;
}

function formatTs(ts) {
  if (!ts) return "";
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

function renderChips() {
  const catEl = document.getElementById("category-chips");
  const lvlEl = document.getElementById("level-chips");
  catEl.innerHTML = "";
  lvlEl.innerHTML = "";
  CATEGORIES.forEach((name) => {
    const btn = document.createElement("button");
    btn.className = "chip" + (state.category === name ? " active" : "");
    btn.textContent = name;
    btn.onclick = () => {
      state.category = name;
      renderChips();
      renderFeed();
    };
    catEl.appendChild(btn);
  });
  LEVELS.forEach((name) => {
    const btn = document.createElement("button");
    btn.className = "chip" + (state.level === name ? " active" : "");
    btn.textContent = name;
    btn.onclick = () => {
      state.level = name;
      renderChips();
      renderFeed();
    };
    lvlEl.appendChild(btn);
  });
}

function renderHighlights() {
  const root = document.getElementById("highlights");
  root.innerHTML = "";
  const items = state.events.filter((e) => HIGHLIGHT_EVENTS.has(e.event)).slice(0, 8);
  items.forEach((event) => {
    const card = document.createElement("div");
    card.className = "hl-card";
    card.innerHTML =
      `<div class="meta">${event.event} · ${formatTs(event.ts)}</div>` +
      `<div>${escapeHtml(event.message)}</div>`;
    root.appendChild(card);
  });
}

function renderFeed() {
  const feed = document.getElementById("feed");
  feed.innerHTML = "";
  state.events.filter(matchesFilters).forEach((event) => {
    feed.appendChild(rowEl(event));
  });
  renderHighlights();
}

function rowEl(event) {
  const row = document.createElement("article");
  row.className = "row";
  const dataText = event.data && Object.keys(event.data).length
    ? JSON.stringify(event.data, null, 2)
    : "";
  row.innerHTML =
    `<div class="row-head">` +
    `<span class="level ${event.level || "info"}">${event.level || "info"}</span>` +
    `<span class="cat">${escapeHtml(event.category || "")}</span>` +
    `<span class="evt">${escapeHtml(event.event || "")}</span>` +
    `<span class="ts">${escapeHtml(formatTs(event.ts))}</span>` +
    `</div>` +
    `<div class="msg">${escapeHtml(event.message || "")}</div>`;
  if (dataText) {
    const pre = document.createElement("pre");
    pre.className = "data collapsed";
    pre.textContent = dataText;
    pre.onclick = () => pre.classList.toggle("collapsed");
    row.appendChild(pre);
  }
  return row;
}

function prependEvent(event) {
  state.events.unshift(event);
  if (state.events.length > 2000) state.events.pop();
  if (!matchesFilters(event)) {
    renderHighlights();
    return;
  }
  const feed = document.getElementById("feed");
  feed.insertBefore(rowEl(event), feed.firstChild);
  renderHighlights();
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function setConnection(up) {
  const el = document.getElementById("connection");
  el.className = "status " + (up ? "up" : "down");
  el.textContent = up ? "SSE connected" : "SSE disconnected";
}

async function loadSnapshot() {
  const response = await fetch("/api/events?limit=300");
  const body = await response.json();
  state.events = body.events || [];
  renderFeed();
}

function connectSse() {
  const source = new EventSource("/api/stream");
  source.onopen = () => setConnection(true);
  source.onerror = () => setConnection(false);
  source.onmessage = (msg) => {
    try {
      prependEvent(JSON.parse(msg.data));
    } catch {
      /* ignore malformed frames */
    }
  };
}

renderChips();
loadSnapshot().then(connectSse).catch(() => {
  setConnection(false);
  connectSse();
});
