// Офис субагентов — клиент. Без сборки и фреймворков: открывается на любом телефоне.
import { drawRoom, groupIcon, hash, icon, portrait, ROOM_H, ROOM_W, roomLayout } from "/sprites.js";

const $ = (sel) => document.querySelector(sel);

const state = {
  groups: [],
  tasks: [],
  messages: [],
  questions: [],
  stats: {},
  models: [],
  tab: storageGet("tab") || "office",
  feedFilter: "all",
  openTaskId: null,
};

const STATUS_LABEL = {
  queued: "в очереди",
  working: "в работе",
  waiting: "ждёт ответа",
  done: "готово",
  failed: "ошибка",
  cancelled: "отменено",
};
const GROUP_STATUS = {
  idle: "свободен",
  working: "работает",
  waiting: "ждёт вашего ответа",
  queued: "задача в очереди",
};

// Примеры заданий для стартовых отделов — чтобы не думать, с чего начать.
const EXAMPLES = {
  study: ["Хочу 1450 на SAT, экзамен через 8 недель, сейчас около 1250 — составь план", "Проверь моё эссе IELTS Writing Task 2: …", "Давай потренируем IELTS Speaking Part 1"],
  lab: ["Сделай ревью кода в папке code/ на диске", "Напиши и запусти тесты для code/bot/ — особенно казахские буквы и эмодзи"],
  ideas: ["Разбери идею: Telegram-бот, который подбирает хакатоны в Казахстане", "Собери дайджест за неделю и сохрани в файл"],
};

// ---------- Утилиты ----------

function storageGet(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}
function storageSet(key, value) {
  try { localStorage.setItem(key, value); } catch { /* приватный режим — не страшно */ }
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}
function parseTime(s) {
  return new Date(/Z|T/.test(s) ? s : String(s).replace(" ", "T") + "Z");
}
function timeAgo(s) {
  const diff = (Date.now() - parseTime(s).getTime()) / 1000;
  if (diff < 60) return "только что";
  if (diff < 3600) return `${Math.floor(diff / 60)} мин назад`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} ч назад`;
  return parseTime(s).toLocaleDateString("ru-RU", { day: "numeric", month: "short" });
}
function clock(s) {
  return parseTime(s).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}
function money(n) {
  return "$" + (n || 0).toFixed(n >= 10 ? 0 : 2);
}

// Минимальный и безопасный markdown: сначала экранируем, потом размечаем.
function md(src) {
  const blocks = [];
  const text = esc(src).replace(/```[\w-]*\n?([\s\S]*?)```/g, (_, code) => {
    blocks.push(`<pre><code>${code}</code></pre>`);
    return `\u0000${blocks.length - 1}\u0000`;
  });
  const inline = (s) =>
    s
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
      .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<i>$2</i>")
      .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
      .replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>');
  const out = [];
  let list = null;
  for (const line of text.split("\n")) {
    const m = line.match(/^\s*(?:[-*•]|(\d+)[.)])\s+(.*)$/);
    if (m) {
      const type = m[1] ? "ol" : "ul";
      if (list !== type) { if (list) out.push(`</${list}>`); out.push(`<${type}>`); list = type; }
      out.push(`<li>${inline(m[2])}</li>`);
      continue;
    }
    if (list) { out.push(`</${list}>`); list = null; }
    const h = line.match(/^#{1,6}\s+(.*)$/);
    if (h) out.push(`<h4>${inline(h[1])}</h4>`);
    else if (/^\|.*\|$/.test(line.trim())) out.push(`<p class="table-line">${inline(line)}</p>`);
    else if (line.trim()) out.push(`<p>${inline(line)}</p>`);
  }
  if (list) out.push(`</${list}>`);
  return out.join("").replace(/\u0000(\d+)\u0000/g, (_, i) => blocks[Number(i)]);
}

const groupById = (id) => state.groups.find((g) => g.id === id);
function subById(id) {
  for (const g of state.groups) {
    const s = g.subagents.find((x) => x.id === id);
    if (s) return { ...s, color: g.color, group: g };
  }
  return null;
}
const gstyle = (g) => `--g:${g?.color || "#3ab7ff"}`;
const subPortrait = (s, cls = "ava") => `<img class="${cls}" src="${portrait({ id: s.id, color: s.color })}" alt="" />`;
const groupImg = (g, cls = "gicon") => (g ? `<img class="${cls}" src="${groupIcon(g)}" alt="" />` : `<img class="${cls}" src="${icon("office")}" alt="" />`);

// Уровень отдела растёт с каждой выполненной задачей: 1, 4, 9, 16… задач — следующий уровень.
function level(done) {
  const lvl = Math.floor(Math.sqrt(done)) + 1;
  const from = (lvl - 1) ** 2, to = lvl ** 2;
  return { lvl, progress: to === from ? 0 : (done - from) / (to - from) };
}

function streak() {
  const days = new Set(state.stats.done_days ?? []);
  let n = 0;
  const d = new Date();
  const key = (x) => x.toISOString().slice(0, 10);
  if (!days.has(key(d))) d.setUTCDate(d.getUTCDate() - 1); // сегодня ещё не успели — серия не сгорела
  while (days.has(key(d))) {
    n++;
    d.setUTCDate(d.getUTCDate() - 1);
  }
  return n;
}

async function api(path, options = {}) {
  const res = await fetch(`/api${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    body: options.body && typeof options.body !== "string" ? JSON.stringify(options.body) : options.body,
  });
  if (res.status === 401 && path !== "/login") {
    showLogin();
    throw new Error("Нужно войти");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Ошибка ${res.status}`);
  return data;
}

let toastTimer;
function toast(text) {
  const el = $("#toast");
  el.textContent = text;
  el.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("hidden"), 2800);
}

// ---------- Вход ----------

function showLogin() {
  $("#app").classList.add("hidden");
  $("#login").classList.remove("hidden");
  $("#login-password").focus();
}

$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("#login-error").textContent = "";
  try {
    await api("/login", { method: "POST", body: { password: $("#login-password").value } });
    $("#login-password").value = "";
    start();
  } catch (err) {
    $("#login-error").textContent = err.message;
  }
});

// ---------- Загрузка и живые обновления ----------

let source;

async function start() {
  const me = await fetch("/api/me").then((r) => r.json()).catch(() => ({ authed: false }));
  if (!me.authed) return showLogin();
  $("#login").classList.add("hidden");
  $("#app").classList.remove("hidden");
  await refresh();
  connect();
}

async function refresh() {
  Object.assign(state, await api("/state"));
  for (const g of state.groups) syncScene(g, true);
  renderAll();
}

function connect() {
  source?.close();
  source = new EventSource("/api/stream");
  source.onopen = () => {
    $("#conn").classList.add("on");
    refresh().catch(() => {});
  };
  source.onerror = () => $("#conn").classList.remove("on");
  source.onmessage = (e) => handleEvent(JSON.parse(e.data));
}

function upsert(list, item) {
  const i = list.findIndex((x) => x.id === item.id);
  if (i >= 0) list[i] = item;
  else list.push(item);
}

function handleEvent(ev) {
  switch (ev.type) {
    case "group":
      upsert(state.groups, ev.group);
      state.groups.sort((a, b) => a.position - b.position);
      syncScene(ev.group, false);
      if (state.tab === "office" && updateRoomCard(ev.group)) {
        renderTopbar();
        return;
      }
      break;
    case "group_deleted":
      state.groups = state.groups.filter((g) => g.id !== ev.id);
      break;
    case "task": {
      const prev = state.tasks.find((t) => t.id === ev.task.id);
      upsert(state.tasks, ev.task);
      state.tasks.sort((a, b) => b.id - a.id);
      if (prev && prev.status !== ev.task.status && ["done", "failed"].includes(ev.task.status)) {
        const g = groupById(ev.task.group_id);
        if (ev.task.status === "done") {
          celebrate(ev.task.group_id);
          notify(`«${g?.name ?? "Отдел"}» справился!`, ev.task.title);
        } else notify(`«${g?.name ?? "Отдел"}»: ошибка`, ev.task.title);
      }
      break;
    }
    case "message":
      state.messages.push(ev.message);
      if (state.messages.length > 400) state.messages.splice(0, state.messages.length - 400);
      if (state.tab === "office") return; // в офисе лента не видна
      break;
    case "question":
      state.questions = state.questions.filter((q) => q.id !== ev.question.id);
      if (ev.question.answer === null) {
        state.questions.push(ev.question);
        const s = subById(ev.question.subagent_id);
        notify(`✋ ${s?.name ?? groupById(ev.question.group_id)?.name ?? "Отдел"} спрашивает`, ev.question.question);
      }
      renderQuestions();
      return;
    case "limits":
      state.stats.rate_limit = ev.limits;
      renderTopbar();
      return;
    case "file":
      if (state.tab === "files") renderView();
      return;
  }
  scheduleRender();
  if (state.openTaskId && (ev.type === "task" || ev.type === "message" || ev.type === "group")) {
    const tid = ev.task?.id ?? ev.message?.task_id ?? ev.group?.current_task?.id;
    if (tid === state.openTaskId) scheduleTaskSheetRefresh();
  }
}

let renderQueued = false;
function scheduleRender() {
  if (renderQueued) return;
  renderQueued = true;
  requestAnimationFrame(() => {
    renderQueued = false;
    renderAll();
  });
}

// ---------- Уведомления ----------

$("#notify-btn").addEventListener("click", async () => {
  if (!("Notification" in window)) return toast("Браузер не поддерживает уведомления");
  const p = await Notification.requestPermission();
  toast(p === "granted" ? "Уведомления включены" : "Уведомления запрещены в настройках браузера");
  renderTopbar();
});

async function notify(title, body) {
  navigator.vibrate?.(30);
  if (document.visibilityState === "visible") return toast(`${title} ${body}`.slice(0, 120));
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  const reg = await navigator.serviceWorker?.getRegistration();
  if (reg) reg.showNotification(title, { body, icon: "/icon-192.png", tag: title });
  else new Notification(title, { body });
}

// ---------- Сцена: маленькие сотрудники ходят между диваном и столами ----------

const scenes = new Map(); // groupId -> Map(subId -> член сцены)
const SIT_Y = 50;
const LOUNGE_Y = 28;

function moodFor(g, s) {
  const r = s.run;
  if (r?.status === "working") return /ждёт ответа/.test(r.activity ?? "") ? "waiting" : "working";
  return "idle";
}

function syncScene(g, initial) {
  const layout = roomLayout(g.subagents.length);
  const old = scenes.get(g.id) ?? new Map();
  const next = new Map();
  g.subagents.slice(0, 4).forEach((s, i) => {
    const mood = moodFor(g, s);
    const seat = layout.seats[i];
    const lounge = layout.lounge[i];
    const target = mood === "idle" ? lounge : seat;
    let m = old.get(s.id);
    if (!m) {
      m = { id: s.id, x: target.x, y: target.y, deskIndex: i, doneUntil: 0 };
      if (!initial && mood !== "idle") Object.assign(m, lounge); // новенький пришёл с дивана
    }
    if (m.mood && m.mood !== "idle" && mood === "idle" && s.run?.status === "done") m.doneUntil = Date.now() + 6000;
    Object.assign(m, { mood, target, deskIndex: i, color: g.color });
    next.set(s.id, m);
  });
  scenes.set(g.id, next);
}

function stepMember(m) {
  const speed = 2;
  const t = m.target;
  let moved = false;
  const goX = () => {
    if (m.x === t.x) return false;
    m.x += Math.sign(t.x - m.x) * Math.min(speed, Math.abs(t.x - m.x));
    return true;
  };
  const goY = () => {
    if (m.y === t.y) return false;
    m.y += Math.sign(t.y - m.y) * Math.min(speed, Math.abs(t.y - m.y));
    return true;
  };
  // Вниз к столу: сначала по ковру до своего места, потом садимся. Обратно — встаём и идём к дивану.
  if (t.y > m.y) moved = m.y <= LOUNGE_Y ? goX() || goY() : goY() || goX();
  else moved = goY() || goX();
  m.walking = moved;
  m.seated = !moved && m.y === SIT_Y;
}

function bubbleFor(m, tick) {
  if (m.walking) return null;
  if (m.mood === "waiting") return "question";
  if (m.mood === "working" && m.seated) return "dots";
  if (m.doneUntil > Date.now()) return "check";
  if (m.mood === "idle" && (tick + (hash(m.id) % 40)) % 80 < 10) return "zzz";
  return null;
}

function skyNow() {
  const h = new Date().getHours();
  if (h < 6 || h >= 21) return { night: true, top: "#0e1433", bottom: "#1a2150" };
  if (h >= 18) return { evening: true, top: "#ff8a5c", bottom: "#7a3d8c" };
  return { top: "#5ec8ff", bottom: "#b8e8ff" };
}

let tick = 0;
const visibleRooms = new Set();
const roomObserver = new IntersectionObserver((entries) => {
  for (const e of entries) {
    const id = e.target.dataset.room;
    if (e.isIntersecting) visibleRooms.add(id);
    else visibleRooms.delete(id);
  }
});

function drawRooms(all = false) {
  const sky = skyNow();
  document.querySelectorAll("canvas[data-room]").forEach((c) => {
    const id = c.dataset.room;
    if (!all && !visibleRooms.has(id)) return;
    const g = groupById(id);
    const scene = scenes.get(id);
    if (!g || !scene) return;
    const members = [...scene.values()].map((m) => ({ ...m, bubble: bubbleFor(m, tick) }));
    const runs = g.current_task ? g.subagents.filter((s) => s.run).map((s) => s.run) : [];
    drawRoom(c, { color: g.color, members, runs, sky, frame: Math.floor(tick / 2) });
  });
}

setInterval(() => {
  if (document.hidden) return;
  tick++;
  for (const scene of scenes.values()) for (const m of scene.values()) stepMember(m);
  if (state.tab === "office") drawRooms();
}, 125);

// Конфетти, когда отдел закончил задачу.
function celebrate(groupId) {
  const card = document.querySelector(`.room-card[data-group="${groupId}"]`);
  if (!card) return;
  const colors = ["#ffd23f", "#ff6b8b", "#5fd07e", "#3ab7ff", "#fff8e6"];
  for (let i = 0; i < 26; i++) {
    const p = document.createElement("i");
    p.className = "confetti";
    p.style.left = 50 + (Math.random() * 40 - 20) + "%";
    p.style.background = colors[i % colors.length];
    p.style.setProperty("--dx", Math.round(Math.random() * 240 - 120) + "px");
    p.style.setProperty("--dy", Math.round(-60 - Math.random() * 120) + "px");
    p.style.animationDelay = Math.random() * 0.15 + "s";
    card.appendChild(p);
    setTimeout(() => p.remove(), 1400);
  }
}

// ---------- Отрисовка ----------

function renderAll() {
  renderTopbar();
  renderQuestions();
  renderView();
}

function renderTopbar() {
  const s = state.stats;
  const chip = $("#limit-chip");
  const rl = s.rate_limit;
  chip.className = "limit-chip";
  if (s.auth === "subscription") {
    const pct = rl?.utilization != null ? Math.round(rl.utilization * (rl.utilization <= 1 ? 100 : 1)) : null;
    const reset = rl?.resetsAt ? new Date(rl.resetsAt * (rl.resetsAt < 1e12 ? 1000 : 1)).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" }) : null;
    chip.innerHTML = `<img src="${icon("bolt")}" alt="" />${rl?.status === "rejected" ? "Лимит исчерпан" : pct != null ? `${pct}%` : "Подписка"}${reset ? ` · до ${reset}` : ""}`;
    chip.title = "Лимит подписки Claude за 5 часов";
    if (rl?.status === "rejected") chip.classList.add("bad");
    else if (rl?.status === "allowed_warning" || (pct ?? 0) > 80) chip.classList.add("warn");
  } else if (s.auth === "api") {
    chip.innerHTML = `≈${money(s.spent_today_usd)} / ${money(s.daily_budget_usd)}`;
    chip.title = "Расходы по API-ключу за сутки / лимит";
    if (s.spent_today_usd > 0.8 * s.daily_budget_usd) chip.classList.add("warn");
  } else {
    chip.innerHTML = "⚠ не подключено";
    chip.classList.add("bad");
  }
  const granted = "Notification" in window && Notification.permission === "granted";
  $("#notify-btn").style.opacity = granted ? "1" : ".45";
  const active = state.tasks.filter((t) => ["queued", "working", "waiting"].includes(t.status)).length;
  const badge = $("#panel-badge");
  badge.textContent = active;
  badge.classList.toggle("hidden", active === 0);
}

function renderQuestions() {
  const el = $("#questions");
  if (el.contains(document.activeElement)) return; // не мешаем печатать ответ
  el.innerHTML = state.questions
    .map((q) => {
      const s = subById(q.subagent_id);
      const g = groupById(q.group_id);
      const who = s ? `${subPortrait(s)} <b>${esc(s.name)}</b>` : `${groupImg(g)} <b>${esc(g?.name ?? "Отдел")}</b>`;
      return `<div class="q-card" style="${gstyle(g)}">
        <div class="q-card-head">${who}<span>спрашивает · ${esc(g?.name ?? "")}</span></div>
        <div class="md q-text">${md(q.question)}</div>
        <form data-question="${q.id}">
          <input name="answer" placeholder="Ваш ответ…" autocomplete="off" required />
          <button class="btn primary small">Ответить</button>
        </form>
      </div>`;
    })
    .join("");
}

$("#questions").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target.closest("form[data-question]");
  if (!form) return;
  const answer = form.answer.value.trim();
  if (!answer) return;
  form.querySelector("button").disabled = true;
  try {
    await api(`/questions/${form.dataset.question}/answer`, { method: "POST", body: { answer } });
    form.answer.blur();
    state.questions = state.questions.filter((q) => String(q.id) !== form.dataset.question);
    renderQuestions();
    toast("Ответ отправлен — работа продолжается");
  } catch (err) {
    toast(err.message);
    form.querySelector("button").disabled = false;
  }
});

const VIEWS = { office: viewOffice, panel: viewPanel, feed: viewFeed, files: viewFiles, groups: viewGroups };

function renderView() {
  document.querySelectorAll(".tabbar button").forEach((b) => b.classList.toggle("active", b.dataset.tab === state.tab));
  $("#fab").classList.toggle("hidden", !(state.tab === "office" || state.tab === "feed"));
  const view = $("#view");
  // Не перерисовываем пульт, пока человек печатает задание.
  if (state.tab === "panel" && view.contains(document.activeElement) && document.activeElement.tagName === "TEXTAREA") {
    updatePanelStatuses();
    return;
  }
  const stickToBottom = state.tab === "feed" && view.scrollHeight - view.scrollTop - view.clientHeight < 80;
  const html = VIEWS[state.tab]();
  if (typeof html === "string") view.innerHTML = `<div class="view-inner">${html}</div>`;
  view.classList.toggle("panel-view", state.tab === "panel");
  if (state.tab === "office") {
    roomObserver.disconnect();
    visibleRooms.clear();
    document.querySelectorAll("canvas[data-room]").forEach((c) => roomObserver.observe(c));
    drawRooms(true);
  }
  if (state.tab === "feed" && (stickToBottom || !view.dataset.scrolled)) {
    view.scrollTop = view.scrollHeight;
    view.dataset.scrolled = "1";
  }
}

document.querySelector(".tabbar").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-tab]");
  if (!btn) return;
  state.tab = btn.dataset.tab;
  storageSet("tab", state.tab);
  delete $("#view").dataset.scrolled;
  $("#view").scrollTop = 0;
  renderView();
});

// ----- Офис -----

function hud() {
  const done = state.groups.reduce((n, g) => n + g.done_total, 0);
  const today = state.groups.reduce((n, g) => n + g.done_today, 0);
  const busy = state.groups.filter((g) => g.status === "working" || g.status === "waiting").length;
  const office = level(done);
  return `<div class="hud">
    <div class="hud-cell px"><img src="${icon("star")}" alt="" /><div><b>Офис ур.${office.lvl}</b><div class="bar"><i style="width:${Math.round(office.progress * 100)}%"></i></div></div></div>
    <div class="hud-cell px"><img src="${icon("tasks")}" alt="" /><div><b>${today}</b><small>сегодня</small></div></div>
    <div class="hud-cell px"><img src="${icon("fire")}" alt="" /><div><b>${streak()}</b><small>серия</small></div></div>
    <div class="hud-cell px"><img src="${icon("team")}" alt="" /><div><b>${busy}/${state.groups.length}</b><small>в работе</small></div></div>
  </div>`;
}

function viewOffice() {
  // Без подключения офис бесполезен — говорим об этом первым делом.
  const banner =
    state.stats.auth === "none"
      ? `<div class="banner px">⚠ Офис не подключён к Claude. <button class="btn small primary" data-help="connect">Как подключить</button></div>`
      : "";
  const rooms = state.groups.map(roomCard).join("");
  const firstTime = state.tasks.length === 0;
  return `${banner}${hud()}
    ${firstTime ? `<div class="tip px"><b>С чего начать:</b> нажмите «Дать задание» у любого отдела. Координатор раздаст работу своим субагентам — смотрите, как они встают с дивана и садятся за столы.</div>` : ""}
    <div class="building">${rooms}
      <button class="room-new px" data-new-group><img src="${icon("plus")}" alt="" />Открыть новый отдел</button>
    </div>`;
}

function roomCard(g) {
  const lv = level(g.done_total);
  const t = g.current_task;
  const runs = g.subagents.filter((s) => s.run);
  const doneRuns = runs.filter((s) => s.run.status === "done").length;
  let status = `<span class="muted">${esc(g.motto || "Готовы к работе")}</span>`;
  if (t) status = `<b>${t.status === "waiting" ? "✋ Ждёт вашего ответа" : "▶ В работе"}:</b> ${esc(t.title)}${runs.length ? ` <span class="muted">· ${doneRuns}/${runs.length}</span>` : ""}`;
  else if (g.queued) status = `<b>⏳ В очереди:</b> ${g.queued}`;
  const crew = g.subagents
    .map((s) => {
      const sub = { ...s, color: g.color };
      const mood = moodFor(g, s);
      const doing = mood === "waiting" ? "ждёт вашего ответа" : mood === "working" ? s.run.activity || s.run.description || "работает" : s.role;
      return `<li class="crew-${mood}" data-sub="${esc(s.id)}">${subPortrait(sub, "ava-s")}<span class="crew-name">${esc(s.name)}</span><span class="crew-role">${esc(s.role)}</span><span class="crew-doing">${esc(doing)}</span></li>`;
    })
    .join("");
  return `<section class="room-card px ${g.status}" data-group="${esc(g.id)}" style="${gstyle(g)}">
    <header class="room-head" data-open-room="${esc(g.id)}">
      ${groupImg(g)}
      <div class="room-title"><b>${esc(g.name)}</b><small>${GROUP_STATUS[g.status]}</small></div>
      <div class="lvl"><span>УР.${lv.lvl}</span><div class="bar"><i style="width:${Math.round(lv.progress * 100)}%"></i></div></div>
    </header>
    <div class="stage"><canvas width="${ROOM_W}" height="${ROOM_H}" data-room="${esc(g.id)}"></canvas></div>
    <div class="room-status" ${t ? `data-task="${t.id}"` : ""}>${status}</div>
    <ul class="crew">${crew}</ul>
    <div class="room-actions">
      <button class="btn small primary" data-assign="${esc(g.id)}">＋ Дать задание</button>
      ${t ? `<button class="btn small" data-task="${t.id}">Ход работы</button><button class="btn small danger" data-cancel="${t.id}">Стоп</button>` : `<button class="btn small" data-open-room="${esc(g.id)}">Отдел</button>`}
    </div>
  </section>`;
}

// Точечно обновляем одну комнату, чтобы не перерисовывать всё здание.
function updateRoomCard(g) {
  const old = document.querySelector(`.room-card[data-group="${g.id}"]`);
  if (!old) return false;
  const tmp = document.createElement("div");
  tmp.innerHTML = roomCard(g);
  const fresh = tmp.firstElementChild;
  // Канвас оставляем тот же — анимация не дёргается.
  fresh.querySelector(".stage").replaceWith(old.querySelector(".stage"));
  old.querySelectorAll(".confetti").forEach((c) => fresh.appendChild(c));
  old.replaceWith(fresh);
  return true;
}

// Тап по комнате: попали в человечка — карточка субагента, иначе — карточка отдела.
document.addEventListener("click", (e) => {
  const c = e.target.closest("canvas[data-room]");
  if (!c) return;
  const r = c.getBoundingClientRect();
  const x = ((e.clientX - r.left) / r.width) * ROOM_W;
  const y = ((e.clientY - r.top) / r.height) * ROOM_H;
  const scene = scenes.get(c.dataset.room);
  const hit = scene && [...scene.values()].find((m) => x >= m.x - 2 && x <= m.x + 12 && y >= m.y - 4 && y <= m.y + 16);
  if (hit) openSubagentCard(hit.id);
  else openRoomSheet(c.dataset.room);
});

// ----- Пульт: свои задания каждому отделу, запуск разом -----

function draftKey(id) {
  return `draft:${id}`;
}

function viewPanel() {
  const rows = state.groups
    .map((g) => {
      const t = g.current_task;
      const ex = (EXAMPLES[g.id] ?? []).map((x) => `<button class="chip" data-example-for="${esc(g.id)}" data-text="${esc(x)}">${esc(x.length > 34 ? x.slice(0, 33) + "…" : x)}</button>`).join("");
      return `<div class="pult px" data-pult-group="${esc(g.id)}" style="${gstyle(g)}">
        <div class="pult-head">${groupImg(g)}<b>${esc(g.name)}</b><span class="pill ${t ? t.status : g.status === "queued" ? "queued" : "idle"}" data-pult-status>${t ? STATUS_LABEL[t.status] : g.queued ? "очередь" : "свободен"}</span></div>
        ${t ? `<div class="pult-current" data-task="${t.id}">${esc(t.title)} <button class="btn small danger" data-cancel="${t.id}">Стоп</button></div>` : ""}
        <textarea rows="2" data-pult="${esc(g.id)}" placeholder="Задание для «${esc(g.name)}»…">${esc(storageGet(draftKey(g.id)) ?? "")}</textarea>
        ${ex ? `<div class="chips">${ex}</div>` : ""}
        <div class="pult-actions"><button class="btn small" data-send-one="${esc(g.id)}">Отправить</button></div>
      </div>`;
    })
    .join("");
  return `<div class="section-title"><h2>ПУЛЬТ</h2></div>
    <p class="hint">Дайте каждому отделу своё задание и запустите все разом — они работают параллельно (одновременно до ${state.stats.max_parallel ?? 3}).</p>
    <div class="list">${rows}</div>
    <div class="pult-launch"><button class="btn primary big" id="send-all">🚀 Запустить все задания</button></div>
    ${recentTasks()}`;
}

function recentTasks() {
  const list = state.tasks.slice(0, 15).map(taskRow).join("");
  return list ? `<div class="section-title" style="margin-top:22px"><h2>НЕДАВНИЕ</h2></div><div class="list">${list}</div>` : "";
}

function updatePanelStatuses() {
  for (const g of state.groups) {
    const el = document.querySelector(`[data-pult-group="${g.id}"] [data-pult-status]`);
    if (!el) continue;
    const t = g.current_task;
    el.className = `pill ${t ? t.status : g.status === "queued" ? "queued" : "idle"}`;
    el.textContent = t ? STATUS_LABEL[t.status] : g.queued ? "очередь" : "свободен";
  }
}

document.addEventListener("input", (e) => {
  const ta = e.target.closest("textarea[data-pult]");
  if (ta) storageSet(draftKey(ta.dataset.pult), ta.value);
});

document.addEventListener("click", async (e) => {
  const ex = e.target.closest("[data-example-for]");
  if (ex) {
    const ta = document.querySelector(`textarea[data-pult="${ex.dataset.exampleFor}"]`);
    ta.value = ex.dataset.text;
    storageSet(draftKey(ex.dataset.exampleFor), ta.value);
    return;
  }
  const one = e.target.closest("[data-send-one]");
  if (one) {
    const id = one.dataset.sendOne;
    const ta = document.querySelector(`textarea[data-pult="${id}"]`);
    if (!ta.value.trim()) return toast("Сначала напишите задание");
    await send([{ group_id: id, text: ta.value.trim() }]);
    return;
  }
  if (e.target.closest("#send-all")) {
    const items = [...document.querySelectorAll("textarea[data-pult]")]
      .filter((t) => t.value.trim())
      .map((t) => ({ group_id: t.dataset.pult, text: t.value.trim() }));
    if (!items.length) return toast("Напишите хотя бы одно задание");
    await send(items);
  }
});

async function send(items) {
  try {
    await api(items.length === 1 ? "/command" : "/commands", { method: "POST", body: items.length === 1 ? items[0] : { items } });
    for (const i of items) storageSet(draftKey(i.group_id), "");
    document.activeElement?.blur?.();
    toast(items.length === 1 ? "Задание отправлено" : `Запущено заданий: ${items.length}`);
    navigator.vibrate?.(20);
    renderView();
  } catch (err) {
    toast(err.message);
  }
}

// ----- Лента -----

function viewFeed() {
  const chips = [`<button class="chip ${state.feedFilter === "all" ? "active" : ""}" data-feed="all">Все</button>`]
    .concat(state.groups.map((g) => `<button class="chip ${state.feedFilter === g.id ? "active" : ""}" style="${gstyle(g)}" data-feed="${esc(g.id)}">${groupImg(g, "")}${esc(g.name)}</button>`))
    .join("");
  const msgs = state.messages.filter((m) => state.feedFilter === "all" || m.group_id === state.feedFilter);
  const feed = msgs.length
    ? msgs.map(renderMessage).join("")
    : `<div class="empty px"><img class="empty-icon" src="${icon("chat")}" alt="" /><br/>Здесь появится всё, что происходит в офисе.</div>`;
  return `<div class="feed-filters chips">${chips}</div>
    <div class="feed">${feed}</div>
    ${msgs.length ? `<div class="actions"><button class="btn small" id="clear-feed">Очистить ленту</button></div>` : ""}`;
}

function renderMessage(m) {
  const g = groupById(m.group_id);
  const s = subById(m.subagent_id);
  const task = m.task_id ? ` data-task="${m.task_id}"` : "";
  if (m.kind === "tool") return `<div class="msg-line"${task}>${s ? `<b style="color:${g?.color}">${esc(s.name)}</b> ` : ""}${esc(m.text)}</div>`;
  if (m.kind === "system") return `<div class="msg-line system"${task}>${esc(m.text)}</div>`;
  if (m.kind === "boss") {
    return `<div class="msg boss"${task}><div class="msg-body"><div class="msg-meta">Вы → ${esc(g?.name ?? "")} · ${clock(m.created_at)}</div><div class="md">${md(m.text)}</div></div></div>`;
  }
  const who = s ? `<b>${esc(s.name)}</b> · ${esc(s.role)}` : `<b>${esc(g?.name ?? "Отдел")}</b> · итог`;
  const label = m.kind === "question" ? " · вопрос" : m.kind === "answer" ? " · ваш ответ" : "";
  const ava = s ? subPortrait(s) : groupImg(g, "ava");
  return `<div class="msg ${m.kind}" style="${gstyle(g)}"${task}>${ava}
    <div class="msg-body"><div class="msg-meta">${who}${label} · ${clock(m.created_at)}</div><div class="md">${md(m.text)}</div></div>
  </div>`;
}

document.addEventListener("click", async (e) => {
  const f = e.target.closest("[data-feed]");
  if (f) {
    state.feedFilter = f.dataset.feed;
    delete $("#view").dataset.scrolled;
    return renderView();
  }
  if (e.target.id === "clear-feed") {
    if (!confirm("Очистить ленту? Задачи и файлы останутся.")) return;
    await api("/messages", { method: "DELETE" });
    state.messages = [];
    renderView();
  }
});

// ----- Задачи -----

function taskRow(t) {
  const g = groupById(t.group_id);
  return `<div class="row px" data-task="${t.id}" style="${gstyle(g)}">
    ${groupImg(g)}
    <div class="row-main"><div class="row-title">${esc(t.title)}</div>
      <div class="row-meta">#${t.id} · ${esc(g?.name ?? "")} · ${timeAgo(t.created_at)}${state.stats.auth === "api" && t.cost_usd ? ` · ≈${money(t.cost_usd)}` : ""}</div></div>
    <span class="pill ${t.status}">${STATUS_LABEL[t.status]}</span>
  </div>`;
}

// ---------- Шторка ----------

function openSheet(html) {
  $("#sheet-body").innerHTML = html;
  $("#sheet").classList.remove("hidden");
  document.body.style.overflow = "hidden";
}
function closeSheet() {
  $("#sheet").classList.add("hidden");
  document.body.style.overflow = "";
  state.openTaskId = null;
}
$("#sheet").addEventListener("click", (e) => {
  if (e.target.closest("[data-close]")) closeSheet();
});

// Общие клики по кнопкам с data-атрибутами (в шторке и на экранах).
document.addEventListener("click", async (e) => {
  const el = (sel) => e.target.closest(sel);
  if (el("canvas[data-room]")) return;
  let b;
  if ((b = el("[data-cancel]"))) {
    e.stopPropagation();
    await api(`/tasks/${b.dataset.cancel}/cancel`, { method: "POST" }).catch((err) => toast(err.message));
    return toast("Останавливаю…");
  }
  if ((b = el("[data-assign]"))) return openComposer(b.dataset.assign);
  if ((b = el("[data-open-room]"))) return openRoomSheet(b.dataset.openRoom);
  if ((b = el("[data-sub]"))) return openSubagentCard(b.dataset.sub);
  if ((b = el("[data-task]"))) return openTaskSheet(Number(b.dataset.task));
  if ((b = el("[data-help]"))) return openHelp();
  if ((b = el("[data-new-group]"))) return openGroupForm(null);
  if ((b = el("[data-edit-group]"))) return openGroupForm(b.dataset.editGroup);
  if ((b = el("[data-edit-sub]"))) return openSubagentForm(b.dataset.editSub, null);
  if ((b = el("[data-add-sub]"))) return openSubagentForm(null, b.dataset.addSub);
});

$("#fab").addEventListener("click", () => openComposer(null));

// ----- Новое задание -----

function openComposer(groupId) {
  const target = groupId ?? storageGet("lastGroup") ?? state.groups[0]?.id;
  const cards = state.groups
    .map(
      (g) => `<label class="pick px" style="${gstyle(g)}">
        <input type="radio" name="group" value="${esc(g.id)}" ${g.id === target ? "checked" : ""} />
        ${groupImg(g)}<span><b>${esc(g.name)}</b><small>${g.status === "idle" ? "свободен" : "занят — задача встанет в очередь"}</small></span>
      </label>`,
    )
    .join("");
  openSheet(`<h3>Новое задание</h3>
    <form class="form" id="composer-form">
      <div class="picks">${cards}</div>
      <textarea name="text" rows="4" placeholder="Что нужно сделать? Чем подробнее, тем лучше результат." required></textarea>
      <div class="chips" id="composer-examples"></div>
      <button class="btn primary big" type="submit">Отправить отделу</button>
    </form>`);
  const fillExamples = () => {
    const id = $("#composer-form").group.value;
    $("#composer-examples").innerHTML = (EXAMPLES[id] ?? []).map((x) => `<button type="button" class="chip" data-example="${esc(x)}">${esc(x.length > 40 ? x.slice(0, 39) + "…" : x)}</button>`).join("");
  };
  fillExamples();
  $("#composer-form").addEventListener("change", fillExamples);
  $("#composer-form").addEventListener("click", (e) => {
    const ex = e.target.closest("[data-example]");
    if (ex) $("#composer-form").text.value = ex.dataset.example;
  });
  $("#composer-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.target;
    const group_id = f.group.value;
    storageSet("lastGroup", group_id);
    closeSheet();
    await send([{ group_id, text: f.text.value.trim() }]);
  });
  setTimeout(() => $("#composer-form").text.focus(), 50);
}

// ----- Отдел -----

function openRoomSheet(id) {
  const g = groupById(id);
  if (!g) return;
  const lv = level(g.done_total);
  const crew = g.subagents
    .map((s) => {
      const sub = { ...s, color: g.color };
      const mood = moodFor(g, s);
      return `<div class="member px crew-${mood}" data-sub="${esc(s.id)}">${subPortrait(sub, "ava-l")}
        <div><b>${esc(s.name)}</b> <span class="muted">· ${esc(s.role)}</span>
        <div class="member-desc">${esc(s.description)}</div>
        <div class="member-doing">${mood === "idle" ? "💤 свободен" : mood === "waiting" ? "✋ ждёт вашего ответа" : "⌨ " + esc(s.run.activity || s.run.description)}</div></div></div>`;
    })
    .join("");
  const tasks = state.tasks.filter((t) => t.group_id === id).slice(0, 6).map(taskRow).join("");
  openSheet(`<div class="sheet-room" style="${gstyle(g)}">
    <div class="agent-head">${groupImg(g, "gicon-l")}<div><h3>${esc(g.name)}</h3><div class="muted">${esc(g.motto)}</div><div class="muted">Уровень ${lv.lvl} · выполнено задач: ${g.done_total}</div></div></div>
    <div class="actions"><button class="btn primary" data-assign="${esc(g.id)}">＋ Дать задание</button><button class="btn" data-edit-group="${esc(g.id)}">Настроить</button></div>
    <div class="box-title" style="margin-top:16px">КОМАНДА · ${g.subagents.length} из 4</div>
    <div class="list">${crew}</div>
    ${tasks ? `<div class="box-title" style="margin-top:16px">ЗАДАЧИ ОТДЕЛА</div><div class="list">${tasks}</div>` : ""}
  </div>`);
}

function openSubagentCard(id) {
  const s = subById(id);
  if (!s) return;
  const g = s.group;
  const mood = moodFor(g, s);
  openSheet(`<div style="${gstyle(g)}">
    <div class="agent-head">${subPortrait(s, "ava-xl")}<div><h3>${esc(s.name)}</h3><div class="muted">${esc(s.role)} · отдел «${esc(g.name)}»</div>
      <div class="member-doing">${mood === "idle" ? "💤 Сейчас свободен" : mood === "waiting" ? "✋ Ждёт вашего ответа" : "⌨ " + esc(s.run.activity || s.run.description)}</div></div></div>
    <div class="box px"><div class="box-title">КОГДА ЕГО ЗОВУТ</div>${esc(s.description)}</div>
    <div class="box px"><div class="box-title">ИНСТРУМЕНТЫ</div>${s.tools ? JSON.parse(s.tools).map((t) => `<code>${esc(t)}</code>`).join(" ") : `📖 читать файлы${s.files ? " · 📝 писать файлы" : ""}${s.web ? " · 🌐 искать в интернете" : ""}`} · ✋ спрашивать вас</div>
    ${s.source_file ? `<p class="hint">Описан в файле <code>.claude/agents/${esc(s.source_file)}</code>${s.model ? ` · модель ${esc(s.model)}` : ""}</p>` : ""}
    ${s.run ? `<div class="box px"><div class="box-title">ТЕКУЩЕЕ ПОРУЧЕНИЕ</div>${esc(s.run.description)}</div>` : ""}
    <div class="actions"><button class="btn" data-edit-sub="${esc(s.id)}">Настроить</button><button class="btn" data-open-room="${esc(g.id)}">Весь отдел</button></div>
  </div>`);
}

// ----- Задача -----

async function openTaskSheet(id) {
  state.openTaskId = id;
  await renderTaskSheet(true);
}

let sheetTimer;
function scheduleTaskSheetRefresh() {
  clearTimeout(sheetTimer);
  sheetTimer = setTimeout(() => renderTaskSheet(false), 300);
}

async function renderTaskSheet(initial) {
  const id = state.openTaskId;
  if (!id) return;
  let data;
  try {
    data = await api(`/tasks/${id}`);
  } catch (err) {
    return toast(err.message);
  }
  if (state.openTaskId !== id) return;
  const { task, messages, runs } = data;
  const g = groupById(task.group_id);
  const active = ["queued", "working", "waiting"].includes(task.status);
  const timeline = runs
    .map((r) => {
      const s = subById(r.subagent_id) ?? { id: r.subagent_id, name: r.subagent_id, role: "", color: g?.color };
      return `<div class="run px">
        ${subPortrait(s)}
        <div class="run-main"><div><b>${esc(s.name)}</b> <span class="muted">${esc(s.role)}</span> <span class="pill ${r.status === "working" ? "working" : r.status}">${r.status === "working" ? "работает" : r.status === "done" ? "сделано" : "ошибка"}</span></div>
          <div>${esc(r.description)}</div>
          ${r.status === "working" && r.activity ? `<div class="muted">⌨ ${esc(r.activity)}</div>` : ""}
          ${r.summary ? `<details><summary>Что сделал(а)</summary><div class="md">${md(r.summary)}</div></details>` : ""}
        </div></div>`;
    })
    .join("");
  const log = messages
    .filter((m) => m.kind === "tool" || m.kind === "question" || m.kind === "answer" || m.kind === "system")
    .map((m) => `<div>${clock(m.created_at)} ${m.kind === "question" ? "✋ " : m.kind === "answer" ? "💬 " : ""}${esc(m.text)}</div>`)
    .join("");
  const html = `<div style="${gstyle(g)}">
    <h3>${esc(task.title)}</h3>
    <div class="kv"><span>#${task.id}</span><span class="kv-group">${groupImg(g, "")} ${esc(g?.name ?? "")}</span><span class="pill ${task.status}">${STATUS_LABEL[task.status]}</span>
      ${task.turns ? `<span>шагов: ${task.turns}</span>` : ""}${state.stats.auth === "api" && task.cost_usd ? `<span>≈${money(task.cost_usd)}</span>` : ""}</div>
    ${task.result ? `<div class="box px result"><div class="box-title">РЕЗУЛЬТАТ</div><div class="md">${md(task.result)}</div></div>` : ""}
    ${timeline ? `<div class="box-title" style="margin-top:14px">КТО ЧТО ДЕЛАЛ</div><div class="list">${timeline}</div>` : active ? `<div class="box px">Координатор разбирает задачу и раздаёт её команде…</div>` : ""}
    <details class="box px"><summary>Задание</summary><div class="md">${md(task.instructions)}</div></details>
    ${log ? `<details class="box px"><summary>Подробный журнал</summary><div class="log">${log}</div></details>` : ""}
    <div class="actions">
      ${active ? `<button class="btn danger" data-cancel="${task.id}">⏹ Остановить</button>` : `<button class="btn" data-retry>🔁 Повторить</button>`}
      ${task.result ? `<button class="btn" data-copy-result>📋 Копировать</button>` : ""}
    </div></div>`;
  const panel = $(".sheet-panel");
  const scroll = panel.scrollTop;
  openSheet(html);
  panel.scrollTop = initial ? 0 : scroll;
  const body = $("#sheet-body");
  body.dataset.result = task.result ?? "";
  body.dataset.instructions = task.instructions;
  body.dataset.group = task.group_id;
}

$("#sheet-body").addEventListener("click", async (e) => {
  const body = $("#sheet-body");
  if (e.target.closest("[data-retry]")) {
    closeSheet();
    return send([{ group_id: body.dataset.group, text: body.dataset.instructions }]);
  }
  if (e.target.closest("[data-copy-result]")) {
    await navigator.clipboard?.writeText(body.dataset.result).catch(() => {});
    return toast("Скопировано");
  }
});

// ----- Диск -----

let filesCache = null;

function viewFiles() {
  api("/files")
    .then(({ files }) => {
      filesCache = files;
      if (state.tab !== "files") return;
      const rows = files
        .map(
          (f) => `<div class="row px" data-file="${esc(f.path)}"><img class="file-icon" src="${icon("files")}" alt="" />
            <div class="row-main"><div class="row-title">${esc(f.path)}</div>
            <div class="row-meta">${timeAgo(f.updated_at)} · ${(f.size / 1024).toFixed(1)} КБ</div></div></div>`,
        )
        .join("");
      $("#view").innerHTML = `<div class="view-inner"><div class="section-title"><h2>ДИСК ОФИСА</h2><button class="btn small" id="new-file">+ Файл</button></div>
        <p class="hint">Сюда субагенты кладут отчёты, тексты и код. Это общая память всех отделов.</p>
        <div class="list">${rows || `<div class="empty px"><img class="empty-icon" src="${icon("files")}" alt="" /><br/>Файлов пока нет</div>`}</div></div>`;
    })
    .catch((err) => toast(err.message));
  return filesCache === null ? `<div class="empty">Загрузка…</div>` : undefined;
}

document.addEventListener("click", async (e) => {
  const row = e.target.closest("[data-file]");
  if (row && !e.target.closest(".sheet")) {
    try {
      const { file } = await api(`/file?path=${encodeURIComponent(row.dataset.file)}`);
      openFileSheet(file);
    } catch (err) {
      toast(err.message);
    }
    return;
  }
  if (e.target.id === "new-file") {
    const path = prompt("Путь к файлу, например notes/идеи.md");
    if (path) openFileSheet({ path, content: "" }, true);
  }
});

function openFileSheet(file, editing = false) {
  const isMd = /\.md$/i.test(file.path);
  openSheet(`
    <h3 class="file-title"><img class="file-icon" src="${icon("files")}" alt="" />${esc(file.path)}</h3>
    ${editing
      ? `<textarea id="file-editor" class="editor">${esc(file.content)}</textarea>`
      : `<div class="box px">${isMd ? `<div class="md">${md(file.content)}</div>` : `<div class="file-content">${esc(file.content)}</div>`}</div>`}
    <div class="actions">
      ${editing ? `<button class="btn primary" data-save-file>💾 Сохранить</button>` : `<button class="btn" data-edit-file>✏️ Править</button>`}
      <button class="btn" data-copy-file>📋 Копировать</button>
      <button class="btn" data-download-file>⬇️ Скачать</button>
      <button class="btn danger" data-delete-file>🗑 Удалить</button>
    </div>`);
  const body = $("#sheet-body");
  body.dataset.path = file.path;
  body._content = file.content;
}

$("#sheet-body").addEventListener("click", async (e) => {
  const body = $("#sheet-body");
  const path = body.dataset.path;
  if (!path) return;
  if (e.target.closest("[data-edit-file]")) return openFileSheet({ path, content: body._content }, true);
  if (e.target.closest("[data-save-file]")) {
    const content = $("#file-editor").value;
    await api("/file", { method: "PUT", body: { path, content } }).catch((err) => toast(err.message));
    toast("Сохранено");
    return openFileSheet({ path, content });
  }
  if (e.target.closest("[data-copy-file]")) {
    await navigator.clipboard?.writeText($("#file-editor")?.value ?? body._content).catch(() => {});
    return toast("Скопировано");
  }
  if (e.target.closest("[data-download-file]")) {
    const blob = new Blob([body._content], { type: "text/plain;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = path.split("/").pop();
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    return;
  }
  if (e.target.closest("[data-delete-file]")) {
    if (!confirm(`Удалить ${path}?`)) return;
    await api(`/file?path=${encodeURIComponent(path)}`, { method: "DELETE" }).catch((err) => toast(err.message));
    closeSheet();
    renderView();
  }
});

// ----- Отделы и подключение -----

function connectionCard() {
  const s = state.stats;
  const rl = s.rate_limit;
  const text = {
    subscription: `<b class="ok">● Подписка Claude</b><div>Субагенты тратят лимиты вашей подписки (окно 5 часов и недельный лимит).${rl?.utilization != null ? ` Сейчас использовано ~${Math.round(rl.utilization * (rl.utilization <= 1 ? 100 : 1))}%.` : ""}</div>`,
    api: `<b class="ok">● API-ключ</b><div>Оплата по токенам. За сутки ≈${money(s.spent_today_usd)} из лимита ${money(s.daily_budget_usd)}.</div>`,
    none: `<b class="bad">● Не подключено</b><div>Агенты не смогут работать, пока на сервере не задан токен подписки или API-ключ.</div>`,
  }[s.auth];
  return `<div class="box px conn-card">${text}<div class="actions"><button class="btn small" data-help="connect">Как подключить</button></div></div>`;
}

function modelOptions(current, withInherit) {
  const opts = state.models.map((m) => `<option value="${esc(m.id)}" ${m.id === (current ?? "") ? "selected" : ""}>${esc(withInherit && m.id === "" ? "Как у всего офиса" : m.label)} — ${esc(m.note)}</option>`);
  return opts.join("");
}

function viewGroups() {
  const rows = state.groups
    .map(
      (g) => `<div class="row px" data-edit-group="${esc(g.id)}" style="${gstyle(g)}">${groupImg(g)}
        <div class="row-main"><div class="row-title">${esc(g.name)}</div>
        <div class="row-meta">${g.subagents.map((s) => esc(s.name)).join(", ")} · ур.${level(g.done_total).lvl}</div></div><span class="muted">›</span></div>`,
    )
    .join("");
  return `<div class="section-title"><h2>ОТДЕЛЫ</h2><button class="btn small primary" data-new-group>+ Отдел</button></div>
    ${connectionCard()}
    <div class="box px"><div class="box-title">МОДЕЛЬ ДЛЯ ВСЕХ ПО УМОЛЧАНИЮ</div>
      <select id="default-model">${modelOptions(state.stats.default_model, false)}</select>
      <p class="hint" style="margin:8px 0 0">На подписке Pro лимиты тают быстрее всего на Opus. Sonnet или Haiku для простых отделов позволят работать дольше.</p></div>
    <div class="list">${rows}</div>
    <div class="actions" style="margin-top:24px"><button class="btn" id="logout">Выйти</button></div>`;
}

document.addEventListener("change", async (e) => {
  if (e.target.id !== "default-model") return;
  try {
    const { default_model } = await api("/settings", { method: "PUT", body: { default_model: e.target.value } });
    state.stats.default_model = default_model;
    toast("Модель по умолчанию изменена");
  } catch (err) {
    toast(err.message);
  }
});

document.addEventListener("click", async (e) => {
  if (e.target.id !== "logout") return;
  await api("/logout", { method: "POST" });
  source?.close();
  showLogin();
});

function openHelp() {
  openSheet(`<h3>Как подключить офис к Claude</h3>
    <div class="box px"><div class="box-title">ВАРИАНТ 1 · ПОДПИСКА PRO/MAX</div>
      <ol class="steps">
        <li>Один раз на любом компьютере установите Claude Code и выполните <code>claude setup-token</code>. Войдите своим аккаунтом, и вы получите токен на год.</li>
        <li>На хостинге добавьте переменную <code>CLAUDE_CODE_OAUTH_TOKEN</code> с этим токеном и перезапустите сервер.</li>
      </ol>
      <p class="warn-text">⚠ Важно: Anthropic рассчитывает лимиты подписки на «обычное личное использование» Claude Code и Agent SDK. Использование токена в самописном приложении правила прямо не разрешают. Пользуйтесь только сами и никому не давайте доступ. Если хотите без рисков, выбирайте вариант 2.</p></div>
    <div class="box px"><div class="box-title">ВАРИАНТ 2 · API-КЛЮЧ</div>
      <ol class="steps">
        <li>Создайте ключ на platform.claude.com. В подписке Max включены API-кредиты на $100–200 в месяц, их можно привязать в настройках оплаты claude.ai.</li>
        <li>Добавьте переменную <code>ANTHROPIC_API_KEY</code> и перезапустите сервер.</li>
      </ol></div>`);
}

// Форма отдела
function openGroupForm(id) {
  const g = id ? groupById(id) : { name: "", motto: "", color: "#9b5cff", lead_prompt: "", model: null, subagents: [] };
  if (!g) return;
  const subs = (g.subagents ?? [])
    .map((s) => `<div class="row px" data-edit-sub="${esc(s.id)}">${subPortrait({ ...s, color: g.color })}<div class="row-main"><div class="row-title">${esc(s.name)} · ${esc(s.role)}</div><div class="row-meta">${esc(s.description)}</div></div><span class="muted">›</span></div>`)
    .join("");
  openSheet(`<h3>${id ? "Настройки отдела" : "Новый отдел"}</h3>
    <form class="form" id="group-form" data-id="${esc(id ?? "")}">
      <div class="two">
        <label>Название<input name="name" value="${esc(g.name)}" required maxlength="40" /></label>
        <label>Цвет<input name="color" type="color" value="${esc(g.color)}" /></label>
      </div>
      <label>Девиз<input name="motto" value="${esc(g.motto)}" maxlength="80" placeholder="Коротко, чем силён отдел" /></label>
      <label>Чем занимается отдел (подсказка координатору)<textarea name="lead_prompt" rows="3" placeholder="Какие задачи сюда приходят и в каком порядке их делать">${esc(g.lead_prompt)}</textarea></label>
      <label>Модель<select name="model">${modelOptions(g.model, true)}</select></label>
      <div class="actions"><button class="btn primary" type="submit">Сохранить</button>
        ${id ? `<button class="btn danger" type="button" data-delete-group="${esc(id)}">Закрыть отдел</button>` : ""}</div>
    </form>
    ${id ? `<div class="box-title" style="margin-top:18px">СУБАГЕНТЫ · ${g.subagents.length} из 4</div><div class="list">${subs}</div>
      ${g.subagents.length < 4 ? `<div class="actions"><button class="btn" data-add-sub="${esc(id)}">+ Добавить субагента</button></div>` : `<p class="hint">В отделе максимум 4 субагента: так каждый остаётся узким специалистом.</p>`}` : ""}`);
}

// Форма субагента
function openSubagentForm(id, groupId) {
  const existing = id ? subById(id) : null;
  if (existing?.source_file) return openFileAgentCard(existing);
  const s = existing ?? { name: "", role: "", description: "", prompt: "", web: 0, files: 1, model: null };
  const gid = existing?.group_id ?? groupId;
  openSheet(`<h3>${id ? "Субагент" : "Новый субагент"}</h3>
    <form class="form" id="sub-form" data-id="${esc(id ?? "")}" data-group="${esc(gid)}">
      <div class="two">
        <label>Имя<input name="name" value="${esc(s.name)}" required maxlength="30" /></label>
        <label>Роль<input name="role" value="${esc(s.role)}" required maxlength="50" placeholder="Например: Дизайнер" /></label>
      </div>
      <label>Когда его звать (это читает координатор)<textarea name="description" rows="2" required maxlength="500" placeholder="Одна узкая задача, в которой он лучший">${esc(s.description)}</textarea></label>
      <label>Инструкции: как он работает и что отдаёт<textarea name="prompt" rows="7" required>${esc(s.prompt)}</textarea></label>
      <label class="check"><input type="checkbox" name="web" ${s.web ? "checked" : ""} /> 🌐 Ищет в интернете</label>
      <label class="check"><input type="checkbox" name="files" ${s.files ? "checked" : ""} /> 📝 Пишет файлы на диск</label>
      <label>Модель<select name="model">${modelOptions(s.model, true).replace("Как у всего офиса", "Как у отдела")}</select></label>
      <div class="actions"><button class="btn primary" type="submit">Сохранить</button>
        ${id ? `<button class="btn danger" type="button" data-delete-sub="${esc(id)}">Уволить</button>` : ""}</div>
    </form>`);
}

// Агент из .claude/agents: правится только файлом, но отдел можно поменять здесь.
function openFileAgentCard(s) {
  const groups = state.groups
    .map((g) => `<option value="${esc(g.id)}" ${g.id === s.group_id ? "selected" : ""} ${g.id !== s.group_id && g.subagents.length >= 4 ? "disabled" : ""}>${esc(g.name)} (${g.subagents.length}/4)</option>`)
    .join("");
  openSheet(`<div style="${gstyle(s.group)}">
    <div class="agent-head">${subPortrait(s, "ava-xl")}<div><h3>${esc(s.name)}</h3><div class="muted">${esc(s.role)}</div></div></div>
    <div class="box px"><div class="box-title">ОПИСАНИЕ (DESCRIPTION)</div>${esc(s.description)}</div>
    <div class="box px"><div class="box-title">ИНСТРУМЕНТЫ</div>${s.tools ? JSON.parse(s.tools).map((t) => `<code>${esc(t)}</code>`).join(" ") : "все"}${s.model ? ` · модель <code>${esc(s.model)}</code>` : ""}</div>
    <details class="box px"><summary>Системный промпт</summary><div class="md">${md(s.prompt)}</div></details>
    <p class="hint">Этот агент описан в <code>.claude/agents/${esc(s.source_file)}</code>. Чтобы изменить его, правьте файл в репозитории: офис подхватит изменения после перезапуска.</p>
    <form class="form" id="move-form" data-id="${esc(s.id)}">
      <label>Отдел<select name="group">${groups}</select></label>
      <div class="actions"><button class="btn primary" type="submit">Перевести</button></div>
    </form></div>`);
}

$("#sheet-body").addEventListener("submit", async (e) => {
  const form = e.target;
  if (form.id === "move-form") {
    e.preventDefault();
    try {
      const target = form.group.value;
      await api(`/subagents/${form.dataset.id}/group`, { method: "PUT", body: { group_id: target } });
      await refresh();
      closeSheet();
      toast(`Переведён в «${groupById(target)?.name}»`);
    } catch (err) {
      toast(err.message);
    }
    return;
  }
  if (form.id !== "group-form" && form.id !== "sub-form") return;
  e.preventDefault();
  const f = new FormData(form);
  try {
    if (form.id === "group-form") {
      const body = { name: f.get("name"), motto: f.get("motto"), color: f.get("color"), lead_prompt: f.get("lead_prompt"), model: f.get("model") || null };
      const id = form.dataset.id;
      const { group } = await api(id ? `/groups/${id}` : "/groups", { method: id ? "PUT" : "POST", body });
      await refresh();
      if (id) {
        closeSheet();
        toast("Сохранено");
      } else {
        toast("Отдел открыт! Наймите в него первого субагента.");
        openSubagentForm(null, group.id);
      }
    } else {
      const body = {
        name: f.get("name"), role: f.get("role"), description: f.get("description"), prompt: f.get("prompt"),
        web: f.get("web") === "on", files: f.get("files") === "on", model: f.get("model") || null,
      };
      const id = form.dataset.id;
      await api(id ? `/subagents/${id}` : `/groups/${form.dataset.group}/subagents`, { method: id ? "PUT" : "POST", body });
      await refresh();
      openGroupForm(form.dataset.group);
      toast(id ? "Сохранено" : "Новый субагент в команде!");
    }
  } catch (err) {
    toast(err.message);
  }
});

$("#sheet-body").addEventListener("click", async (e) => {
  const dg = e.target.closest("[data-delete-group]");
  if (dg) {
    if (!confirm("Закрыть отдел? Его активные задачи будут отменены.")) return;
    await api(`/groups/${dg.dataset.deleteGroup}`, { method: "DELETE" }).catch((err) => toast(err.message));
    closeSheet();
    return refresh();
  }
  const ds = e.target.closest("[data-delete-sub]");
  if (ds) {
    const s = subById(ds.dataset.deleteSub);
    if (!confirm(`Уволить ${s?.name}?`)) return;
    try {
      await api(`/subagents/${ds.dataset.deleteSub}`, { method: "DELETE" });
      await refresh();
      openGroupForm(s.group_id);
    } catch (err) {
      toast(err.message);
    }
  }
});

// ---------- PWA ----------

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
document.querySelectorAll("img[data-icon]").forEach((img) => (img.src = icon(img.dataset.icon)));
setInterval(() => {
  if (state.tab === "panel" && !document.activeElement?.closest("#view")) renderView();
}, 60_000);

start();
