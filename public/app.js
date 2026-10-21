// Виртуальный офис — клиент. Без сборки и фреймворков: открывается на любом телефоне.

import { DESK_H, DESK_W, drawDesk, icon, portrait } from "/sprites.js";

const $ = (sel) => document.querySelector(sel);

const state = {
  agents: [],
  tasks: [],
  messages: [],
  questions: [],
  stats: {},
  models: [],
  tab: localStorageGet("tab") || "office",
  target: null, // кому адресована следующая команда
  taskFilter: "active",
  openTaskId: null,
};

const STATUS_LABEL = {
  queued: "в очереди",
  working: "работает",
  waiting: "ждёт ответа",
  done: "готово",
  failed: "ошибка",
  cancelled: "отменено",
};
const AGENT_STATUS = {
  idle: "Свободен",
  working: "Работает",
  waiting: "Ждёт вашего ответа",
  queued: "Есть задачи в очереди",
};

// ---------- Утилиты ----------

function localStorageGet(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}
function localStorageSet(key, value) {
  try { localStorage.setItem(key, value); } catch { /* приватный режим — не страшно */ }
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function parseTime(s) {
  return new Date(String(s).replace(" ", "T") + "Z");
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
  let text = esc(src).replace(/```[\w-]*\n?([\s\S]*?)```/g, (_, code) => {
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
    else if (line.trim()) out.push(`<p>${inline(line)}</p>`);
  }
  if (list) out.push(`</${list}>`);
  return out.join("").replace(/\u0000(\d+)\u0000/g, (_, i) => blocks[Number(i)]);
}

function agentById(id) {
  return state.agents.find((a) => a.id === id);
}
// Пиксельный портрет сотрудника (для босса и неизвестных — иконка офиса).
function avatar(agent, cls = "ava") {
  const src = agent ? portrait(agent) : icon("office");
  return `<img class="${cls}" src="${src}" alt="" style="${agentStyle(agent)}" />`;
}

function agentStyle(agent) {
  return `--agent:${agent?.color || "#7c8cff"}`;
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
  toastTimer = setTimeout(() => el.classList.add("hidden"), 2600);
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
  const data = await api("/state");
  Object.assign(state, data);
  if (!state.target || !agentById(state.target)) state.target = defaultTarget();
  renderAll();
}

function defaultTarget() {
  return (state.agents.find((a) => a.can_delegate) || state.agents[0])?.id ?? null;
}

function connect() {
  source?.close();
  source = new EventSource("/api/stream");
  source.onopen = () => {
    $("#conn").classList.add("on");
    // После обрыва связи могли пропустить события — подтягиваем всё заново.
    refresh().catch(() => {});
  };
  source.onerror = () => $("#conn").classList.remove("on");
  source.onmessage = (e) => handleEvent(JSON.parse(e.data));
}

function upsert(list, item, key = "id") {
  const i = list.findIndex((x) => x[key] === item[key]);
  if (i >= 0) list[i] = item;
  else list.push(item);
}

function handleEvent(ev) {
  switch (ev.type) {
    case "agent":
      upsert(state.agents, ev.agent);
      break;
    case "agent_deleted":
      state.agents = state.agents.filter((a) => a.id !== ev.id);
      break;
    case "task": {
      const prev = state.tasks.find((t) => t.id === ev.task.id);
      upsert(state.tasks, ev.task);
      state.tasks.sort((a, b) => b.id - a.id);
      if (prev && prev.status !== ev.task.status && ev.task.parent_id === null && ["done", "failed"].includes(ev.task.status)) {
        const agent = agentById(ev.task.agent_id);
        notify(`${agent?.emoji ?? "🤖"} ${agent?.name ?? "Агент"}: ${ev.task.status === "done" ? "готово" : "ошибка"}`, ev.task.title);
      }
      break;
    }
    case "message":
      if (ev.message.kind === "thinking") break;
      state.messages.push(ev.message);
      if (state.messages.length > 300) state.messages.splice(0, state.messages.length - 300);
      break;
    case "question":
      state.questions = state.questions.filter((q) => q.id !== ev.question.id);
      if (ev.question.answer === null) {
        state.questions.push(ev.question);
        const agent = agentById(ev.question.agent_id);
        notify(`❓ ${agent?.name ?? "Агент"} спрашивает`, ev.question.question);
      }
      break;
    case "file":
      if (state.tab === "files") renderView();
      return;
  }
  scheduleRender();
  if (state.openTaskId && (ev.type === "task" || ev.type === "message")) {
    const tid = ev.task?.id ?? ev.message?.task_id;
    const t = state.tasks.find((x) => x.id === tid);
    if (tid === state.openTaskId || t?.parent_id === state.openTaskId) scheduleTaskSheetRefresh();
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
  if (document.visibilityState === "visible") return toast(`${title} — ${body}`.slice(0, 120));
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  const reg = await navigator.serviceWorker?.getRegistration();
  if (reg) reg.showNotification(title, { body, icon: "/icon-192.png", tag: title });
  else new Notification(title, { body });
}

// ---------- Отрисовка ----------

function renderAll() {
  renderTopbar();
  renderQuestions();
  renderView();
}

function renderTopbar() {
  const s = state.stats;
  const spend = $("#spend");
  spend.textContent = `≈${money(s.spent_today_usd)} / ${money(s.daily_budget_usd)}`;
  spend.title = "Расходы за последние сутки / суточный лимит";
  spend.classList.toggle("hot", s.spent_today_usd > 0.8 * s.daily_budget_usd);
  const granted = "Notification" in window && Notification.permission === "granted";
  $("#notify-btn").style.opacity = granted ? "1" : ".45";
  const active = state.tasks.filter((t) => ["queued", "working", "waiting"].includes(t.status)).length;
  const badge = $("#tasks-badge");
  badge.textContent = active;
  badge.classList.toggle("hidden", active === 0);
}

function renderQuestions() {
  const el = $("#questions");
  // Не перерисовываем, пока пользователь печатает ответ.
  if (el.contains(document.activeElement)) return;
  el.innerHTML = state.questions
    .map((q) => {
      const a = agentById(q.agent_id);
      return `<div class="q-card">
        <div class="q-card-head">${avatar(a)} ${esc(a?.name ?? q.agent_id)} спрашивает · задача #${q.task_id}</div>
        <div class="md">${md(q.question)}</div>
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
    toast("Ответ отправлен");
  } catch (err) {
    toast(err.message);
    form.querySelector("button").disabled = false;
  }
});

function renderView() {
  document.querySelectorAll(".tabbar button").forEach((b) => b.classList.toggle("active", b.dataset.tab === state.tab));
  const withComposer = state.tab === "office" || state.tab === "chat";
  $("#composer").classList.toggle("hidden", !withComposer);
  $("#app").classList.toggle("with-composer", withComposer);
  if (withComposer) renderChips();

  const view = $("#view");
  const stickToBottom = state.tab === "chat" && view.scrollHeight - view.scrollTop - view.clientHeight < 80;
  const html = { office: viewOffice, chat: viewChat, tasks: viewTasks, files: viewFiles, team: viewTeam }[state.tab]();
  if (typeof html === "string") view.innerHTML = `<div class="view-inner">${html}</div>`;
  if (state.tab === "office") drawDesks();
  if (state.tab === "chat" && (stickToBottom || !view.dataset.scrolled)) {
    view.scrollTop = view.scrollHeight;
    view.dataset.scrolled = "1";
  }
}

document.querySelector(".tabbar").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-tab]");
  if (!btn) return;
  state.tab = btn.dataset.tab;
  localStorageSet("tab", state.tab);
  delete $("#view").dataset.scrolled;
  $("#view").scrollTop = 0;
  renderView();
});

// ----- Офис -----

function viewOffice() {
  if (!state.agents.length) {
    return `<div class="empty px" style="padding:28px">В офисе пока пусто. Наймите сотрудников во вкладке «Команда».</div>`;
  }
  const busy = state.agents.filter((a) => a.status === "working" || a.status === "waiting").length;
  const desks = state.agents
    .map((a) => {
      let bubble = "z z z… свободен";
      if (a.status === "working") bubble = esc(a.current_task?.title);
      if (a.status === "waiting") bubble = "Есть вопрос к вам!";
      if (a.status === "queued") bubble = `В очереди: ${a.queued}`;
      else if (a.queued) bubble += ` · ещё ${a.queued}`;
      return `<div class="desk ${a.status}" style="${agentStyle(a)}" data-agent="${esc(a.id)}" title="${esc(AGENT_STATUS[a.status])}">
        <div class="speech"><span>${bubble}</span></div>
        <canvas width="${DESK_W}" height="${DESK_H}" data-desk="${esc(a.id)}"></canvas>
        <div class="nameplate"><b><span class="status-led"></span>${esc(a.name)}</b><small>${esc(a.role)}</small></div>
      </div>`;
    })
    .join("");

  const recent = state.messages
    .filter((m) => m.kind !== "boss")
    .slice(-5)
    .reverse()
    .map((m) => {
      const a = agentById(m.agent_id);
      const text = m.text.replace(/\s+/g, " ");
      return `<div class="ticker-item" data-task="${m.task_id ?? ""}">${avatar(a, "")}<time>${clock(m.created_at)}</time><span><b>${esc(a?.name ?? "Офис")}:</b> ${esc(text.length > 110 ? text.slice(0, 110) + "…" : text)}</span></div>`;
    })
    .join("");

  const onboarding = `<div class="onboarding px">
      <h3>КАК ЭТО РАБОТАЕТ</h3>
      <ol>
        <li>Напишите задачу внизу. По умолчанию её получает менеджер.</li>
        <li>Менеджер раздаст части коллегам. За работой видно прямо здесь, в офисе.</li>
        <li>Если нужно уточнение, сотрудник поднимет руку, а сверху появится вопрос.</li>
        <li>Результат придёт в «Чат», большие файлы лягут на «Диск».</li>
      </ol>
      <div class="examples">
        <button class="btn small" data-example="Найди 5 идей для поста про мой пет-проект и напиши лучший пост">Идеи для поста</button>
        <button class="btn small" data-example="Сравни 3 дешёвых хостинга для Node.js-сервера с диском и дай рекомендацию">Сравнить хостинги</button>
      </div>
    </div>`;

  return `<div class="room px">
      <div class="room-wall">
        ${windowHtml()}
        <div class="office-sign">ОФИС<small>${busy ? `в работе: ${busy}` : "все свободны"}</small></div>
        <div class="wall-clock" id="wall-clock">${new Date().toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}</div>
      </div>
      <div class="floor"><div class="desks">${desks}</div></div>
      <div class="legend">
        <span class="working"><span class="status-led"></span>работает</span>
        <span class="waiting"><span class="status-led"></span>ждёт вашего ответа</span>
        <span class="queued"><span class="status-led"></span>есть очередь</span>
        <span class="idle"><span class="status-led"></span>свободен</span>
      </div>
    </div>
    ${recent ? `<div class="ticker px"><div class="ticker-title">ПОСЛЕДНИЕ СОБЫТИЯ</div>${recent}</div>` : onboarding}`;
}

// Окно показывает реальное время суток: днём солнце, ночью звёзды.
function windowHtml() {
  const h = new Date().getHours();
  const night = h < 6 || h >= 21;
  const evening = h >= 18 && h < 21;
  const sky = night ? "#0e1433" : evening ? "linear-gradient(#ff8a5c, #7a3d8c)" : "linear-gradient(#5ec8ff, #b8e8ff)";
  const extra = night
    ? [[10, 8], [30, 20], [60, 10], [74, 30], [20, 38], [48, 42]].map(([x, y]) => `<i class="star" style="left:${x}px;top:${y}px"></i>`).join("")
    : `<i class="sun" style="background:${evening ? "#ffd23f" : "#fff3a0"};top:${evening ? 34 : 10}px"></i>`;
  return `<div class="window"><div class="sky" style="background:${sky}"></div>${extra}</div>`;
}

let deskFrame = 0;
function drawDesks() {
  document.querySelectorAll("canvas[data-desk]").forEach((c) => {
    const a = agentById(c.dataset.desk);
    if (a) drawDesk(c, a, deskFrame);
  });
}

$("#view").addEventListener("click", (e) => {
  const example = e.target.closest("[data-example]");
  if (example) {
    textarea.value = example.dataset.example;
    textarea.dispatchEvent(new Event("input"));
    textarea.focus();
    return;
  }
  const desk = e.target.closest("[data-agent]");
  if (desk && state.tab === "office") return openAgentSheet(desk.dataset.agent);
  const taskEl = e.target.closest("[data-task]");
  if (taskEl && taskEl.dataset.task) return openTaskSheet(Number(taskEl.dataset.task));
});

// ----- Чат -----

function viewChat() {
  if (!state.messages.length) {
    return `<div class="empty px"><img class="empty-icon" src="${icon("chat")}" alt="" /><br/>Здесь будет переписка с командой.<br/>Выберите внизу, кому писать, и отправьте задачу.</div>`;
  }
  return `<div class="section-title"><h2>Лента офиса</h2><button class="btn small" id="clear-feed">Очистить</button></div>
    <div class="feed">${state.messages.map(renderMessage).join("")}</div>`;
}

function renderMessage(m) {
  const a = agentById(m.agent_id);
  const task = m.task_id ? ` data-task="${m.task_id}"` : "";
  if (m.kind === "tool") return `<div class="msg-line"${task}>${esc(a?.name ?? "")}: ${esc(m.text)}</div>`;
  if (m.kind === "system") return `<div class="msg-line system"${task}>${esc(m.text)}</div>`;
  if (m.kind === "boss") {
    const to = a ? ` → ${esc(a.name)}` : "";
    return `<div class="msg boss"${task}><div class="msg-body"><div class="msg-meta">Вы${to} · ${clock(m.created_at)}</div><div class="md">${md(m.text)}</div></div></div>`;
  }
  const label = m.kind === "question" ? " спрашивает" : m.kind === "answer" ? " · ваш ответ" : "";
  const t = state.tasks.find((x) => x.id === m.task_id);
  const sub = t?.parent_id ? ` → ${esc(agentById(t.created_by)?.name ?? "коллеге")}` : "";
  return `<div class="msg ${m.kind}" style="${agentStyle(a)}"${task}>
    ${avatar(a)}
    <div class="msg-body"><div class="msg-meta"><b>${esc(a?.name ?? "Агент")}</b>${label}${sub} · ${clock(m.created_at)}</div><div class="md">${md(m.text)}</div></div>
  </div>`;
}

document.addEventListener("click", async (e) => {
  if (e.target.id !== "clear-feed") return;
  if (!confirm("Очистить ленту? Задачи и файлы останутся.")) return;
  await api("/messages", { method: "DELETE" });
  state.messages = [];
  renderView();
});

// ----- Поле ввода -----

function renderChips() {
  $("#target-chips").innerHTML =
    `<span class="chips-label">Кому:</span>` +
    state.agents
      .map((a) => `<button type="button" class="chip ${a.id === state.target ? "active" : ""}" style="${agentStyle(a)}" data-target="${esc(a.id)}">${avatar(a, "")}${esc(a.name)}</button>`)
      .join("");
  const t = agentById(state.target);
  $("#composer-text").placeholder = t ? `Напишите задачу, её получит ${t.name}…` : "Напишите задачу…";
}

$("#target-chips").addEventListener("click", (e) => {
  const chip = e.target.closest("[data-target]");
  if (!chip) return;
  state.target = chip.dataset.target;
  renderChips();
});

const textarea = $("#composer-text");
textarea.addEventListener("input", () => {
  textarea.style.height = "auto";
  textarea.style.height = Math.min(textarea.scrollHeight, 140) + "px";
});
textarea.addEventListener("keydown", (e) => {
  // На компьютере Enter отправляет, Shift+Enter — новая строка. На телефоне Enter всегда перенос.
  if (e.key === "Enter" && !e.shiftKey && window.matchMedia("(pointer: fine)").matches) {
    e.preventDefault();
    $("#composer").requestSubmit();
  }
});

$("#composer").addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = textarea.value.trim();
  if (!text) return;
  const btn = $("#composer .send");
  btn.disabled = true;
  try {
    await api("/command", { method: "POST", body: { text, agent_id: state.target } });
    textarea.value = "";
    textarea.style.height = "auto";
    if (state.tab !== "chat") {
      state.tab = "chat";
      localStorageSet("tab", "chat");
    }
    delete $("#view").dataset.scrolled;
    renderView();
  } catch (err) {
    toast(err.message);
  } finally {
    btn.disabled = false;
  }
});

// ----- Задачи -----

function viewTasks() {
  const active = ["queued", "working", "waiting"];
  const list = state.tasks.filter((t) => (state.taskFilter === "active" ? active.includes(t.status) : true));
  const filters = [
    ["active", "Активные"],
    ["all", "Все"],
  ]
    .map(([k, l]) => `<button class="chip ${state.taskFilter === k ? "active" : ""}" data-filter="${k}">${l}</button>`)
    .join("");
  const rows = list.map((t) => taskRow(t)).join("");
  return `<div class="section-title"><h2>Задачи</h2></div>
    <div class="filters">${filters}</div>
    <div class="list">${rows || `<div class="empty px"><img class="empty-icon" src="${icon("tasks")}" alt="" /><br/>${state.taskFilter === "active" ? "Активных задач нет" : "Задач пока нет"}</div>`}</div>`;
}

function taskRow(t, extraClass = "") {
  const a = agentById(t.agent_id);
  return `<div class="row px ${t.parent_id ? "sub" : ""} ${extraClass}" data-task="${t.id}">
    ${avatar(a)}
    <div class="row-main">
      <div class="row-title">${esc(t.title)}</div>
      <div class="row-meta">#${t.id} · ${esc(a?.name ?? t.agent_id)} · ${timeAgo(t.created_at)}${t.cost_usd ? ` · ≈${money(t.cost_usd)}` : ""}</div>
    </div>
    <span class="pill ${t.status}">${STATUS_LABEL[t.status]}</span>
  </div>`;
}

document.addEventListener("click", (e) => {
  const f = e.target.closest("[data-filter]");
  if (!f) return;
  state.taskFilter = f.dataset.filter;
  renderView();
});

// ----- Шторка: задача -----

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
  const { task, messages, subtasks } = data;
  const a = agentById(task.agent_id);
  const active = ["queued", "working", "waiting"].includes(task.status);
  const log = messages
    .filter((m) => m.kind !== "boss" && !(m.kind === "agent" && m.text === task.result))
    .map((m) => {
      if (m.kind === "thinking") return `<details><summary>💭 мысли</summary><div class="thinking">${esc(m.text)}</div></details>`;
      if (m.kind === "question") return `<div>❓ <b>Вопрос:</b> ${esc(m.text)}</div>`;
      if (m.kind === "answer") return `<div>💬 <b>Ваш ответ:</b> ${esc(m.text)}</div>`;
      return `<div>${esc(m.text)}</div>`;
    })
    .join("");
  const from = task.created_by === "boss" ? "вы" : agentById(task.created_by)?.name ?? task.created_by;
  const html = `
    <h3>${esc(task.title)}</h3>
    <div class="kv">
      <span>#${task.id}</span>
      <span style="display:inline-flex;gap:6px;align-items:center">${avatar(a, "")} ${esc(a?.name ?? task.agent_id)}</span>
      <span>от: ${esc(from)}</span>
      <span class="pill ${task.status}">${STATUS_LABEL[task.status]}</span>
      ${task.cost_usd ? `<span>≈${money(task.cost_usd)} · ${(task.input_tokens + task.output_tokens).toLocaleString("ru-RU")} ток.</span>` : ""}
    </div>
    ${task.parent_id ? `<button class="btn small" data-open-task="${task.parent_id}">← к задаче #${task.parent_id}</button>` : ""}
    <div class="box"><div class="box-title">Задание</div><div class="md">${md(task.instructions)}</div></div>
    ${subtasks.length ? `<div class="box"><div class="box-title">Поручения коллегам</div><div class="list">${subtasks.map((s) => taskRow(s)).join("")}</div></div>` : ""}
    ${log ? `<div class="box"><div class="box-title">Ход работы</div><div class="log">${log}</div></div>` : ""}
    ${task.result ? `<div class="box"><div class="box-title">Результат</div><div class="md">${md(task.result)}</div></div>` : ""}
    <div class="actions">
      ${active ? `<button class="btn danger" data-cancel="${task.id}">⏹ Остановить</button>` : ""}
      ${!active ? `<button class="btn" data-retry="${task.id}">🔁 Повторить</button>` : ""}
      ${task.result ? `<button class="btn" data-copy-result>📋 Копировать результат</button>` : ""}
    </div>`;
  const panel = $(".sheet-panel");
  const scroll = panel.scrollTop;
  openSheet(html);
  panel.scrollTop = initial ? 0 : scroll;
  $("#sheet-body").dataset.result = task.result ?? "";
  $("#sheet-body").dataset.instructions = task.instructions;
  $("#sheet-body").dataset.agent = task.agent_id;
}

$("#sheet-body").addEventListener("click", async (e) => {
  const body = $("#sheet-body");
  const cancel = e.target.closest("[data-cancel]");
  if (cancel) {
    await api(`/tasks/${cancel.dataset.cancel}/cancel`, { method: "POST" }).catch((err) => toast(err.message));
    return toast("Останавливаю…");
  }
  if (e.target.closest("[data-retry]")) {
    await api("/command", { method: "POST", body: { text: body.dataset.instructions, agent_id: body.dataset.agent } }).catch((err) => toast(err.message));
    closeSheet();
    return toast("Задача отправлена заново");
  }
  if (e.target.closest("[data-copy-result]")) {
    await navigator.clipboard?.writeText(body.dataset.result).catch(() => {});
    return toast("Скопировано");
  }
  const open = e.target.closest("[data-open-task], [data-task]");
  if (open) return openTaskSheet(Number(open.dataset.openTask || open.dataset.task));
});

// ----- Шторка: агент -----

function openAgentSheet(id) {
  const a = agentById(id);
  if (!a) return;
  const tasks = state.tasks.filter((t) => t.agent_id === id).slice(0, 8);
  openSheet(`
    <div class="agent-head" style="${agentStyle(a)}">
      ${avatar(a, "")}
      <div><h3>${esc(a.name)}</h3><div class="muted">${esc(a.role)}</div><div class="muted" style="font-size:13px">${AGENT_STATUS[a.status]}</div></div>
    </div>
    <div class="actions">
      <button class="btn primary" data-assign="${esc(a.id)}">✉️ Поручить задачу</button>
      <button class="btn" data-edit-agent="${esc(a.id)}">⚙️ Настроить</button>
    </div>
    <div class="box"><div class="box-title">Последние задачи</div>
      <div class="list">${tasks.map((t) => taskRow(t)).join("") || `<div class="muted">Пока не было</div>`}</div>
    </div>`);
}

document.addEventListener("click", (e) => {
  const assign = e.target.closest("[data-assign]");
  if (assign) {
    state.target = assign.dataset.assign;
    closeSheet();
    state.tab = "chat";
    renderView();
    textarea.focus();
    return;
  }
  const edit = e.target.closest("[data-edit-agent]");
  if (edit) openAgentForm(edit.dataset.editAgent);
});

// ----- Диск -----

let filesCache = null;

function viewFiles() {
  api("/files")
    .then(({ files }) => {
      filesCache = files;
      if (state.tab !== "files") return;
      const rows = files
        .map((f) => {
          const a = agentById(f.updated_by);
          const who = f.updated_by === "boss" ? "вы" : a?.name ?? f.updated_by;
          return `<div class="row px" data-file="${esc(f.path)}"><img class="file-icon" src="${icon("files")}" alt="" />
            <div class="row-main"><div class="row-title">${esc(f.path)}</div>
            <div class="row-meta">${esc(who)} · ${timeAgo(f.updated_at)} · ${(f.size / 1024).toFixed(1)} КБ</div></div></div>`;
        })
        .join("");
      $("#view").innerHTML = `<div class="view-inner"><div class="section-title"><h2>Диск офиса</h2><button class="btn small" id="new-file">+ Файл</button></div>
        <p class="muted" style="margin-top:0">Здесь агенты хранят отчёты, тексты и код. Это же — общая память команды.</p>
        <div class="list">${rows || `<div class="empty px"><img class="empty-icon" src="${icon("files")}" alt="" /><br/>Файлов пока нет</div>`}</div></div>`;
    })
    .catch((err) => toast(err.message));
  return filesCache === null ? `<div class="empty">Загрузка…</div>` : undefined;
}

document.addEventListener("click", async (e) => {
  const row = e.target.closest("[data-file]");
  if (row && state.tab === "files" && !e.target.closest(".sheet")) {
    const { file } = await api(`/file?path=${encodeURIComponent(row.dataset.file)}`);
    return openFileSheet(file);
  }
  if (e.target.id === "new-file") {
    const path = prompt("Путь к файлу, например notes/идеи.md");
    if (!path) return;
    openFileSheet({ path, content: "", updated_by: "boss", updated_at: new Date().toISOString() }, true);
  }
});

function openFileSheet(file, editing = false) {
  openSheet(`
    <h3 style="word-break:break-all;display:flex;gap:8px;align-items:center"><img class="file-icon" src="${icon("files")}" alt="" />${esc(file.path)}</h3>
    ${editing
      ? `<textarea id="file-editor" style="min-height:50vh;font-family:ui-monospace,monospace;font-size:13px">${esc(file.content)}</textarea>`
      : `<div class="box"><div class="file-content">${esc(file.content)}</div></div>`}
    <div class="actions">
      ${editing ? `<button class="btn primary" data-save-file>💾 Сохранить</button>` : `<button class="btn" data-edit-file>✏️ Редактировать</button>`}
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

// ----- Команда -----

function viewTeam() {
  const current = state.stats.default_model;
  const options = state.models
    .map((m) => `<option value="${esc(m.id)}" ${m.id === current ? "selected" : ""}>${esc(m.label)} · $${m.input}/$${m.output}</option>`)
    .join("");
  const custom = state.models.some((m) => m.id === current) ? "" : `<option selected value="${esc(current)}">${esc(current)}</option>`;
  const rows = state.agents
    .map(
      (a) => `<div class="row px" data-edit-agent="${esc(a.id)}" style="${agentStyle(a)}">
        ${avatar(a)}
        <div class="row-main"><div class="row-title">${esc(a.name)}</div>
        <div class="row-meta">${esc(a.role)} · ${esc(modelLabel(a.model || current))}${a.web ? " · интернет" : ""}${a.can_delegate ? " · раздаёт задачи" : ""}</div></div>
        <span class="muted">›</span>
      </div>`,
    )
    .join("");
  return `<div class="section-title"><h2>КОМАНДА</h2><button class="btn small primary" data-new-agent>+ Нанять</button></div>
    <div class="box px">
      <div class="box-title">МОДЕЛЬ ДЛЯ ВСЕХ ПО УМОЛЧАНИЮ</div>
      <select id="default-model">${custom}${options}</select>
      <p class="price-note">Цена: $ за 1 млн токенов, вход/выход. Haiku примерно в 40 раз дешевле Opus и хорошо справляется с простыми задачами. У любого сотрудника можно выбрать свою модель.</p>
    </div>
    <div class="list">${rows}</div>
    <div class="actions" style="margin-top:24px"><button class="btn" id="logout">Выйти</button></div>`;
}

function modelLabel(id) {
  return state.models.find((m) => m.id === id)?.label.split(" — ")[0] ?? id;
}

document.addEventListener("change", async (e) => {
  if (e.target.id !== "default-model") return;
  try {
    const { default_model } = await api("/settings", { method: "PUT", body: { default_model: e.target.value } });
    state.stats.default_model = default_model;
    toast(`Теперь по умолчанию: ${modelLabel(default_model)}`);
    renderView();
  } catch (err) {
    toast(err.message);
  }
});

document.addEventListener("click", async (e) => {
  if (e.target.closest("[data-new-agent]")) return openAgentForm(null);
  if (e.target.id === "logout") {
    await api("/logout", { method: "POST" });
    source?.close();
    showLogin();
  }
});

function openAgentForm(id) {
  const a = id ? agentById(id) : { name: "", role: "", emoji: "🤖", color: "#7c8cff", system_prompt: "", model: "", effort: "medium", web: 0, can_delegate: 0 };
  if (!a) return;
  const efforts = ["low", "medium", "high", "xhigh", "max"].map((e) => `<option ${a.effort === e ? "selected" : ""}>${e}</option>`).join("");
  openSheet(`
    <h3>${id ? "Настройки сотрудника" : "Новый сотрудник"}</h3>
    <form class="form" id="agent-form" data-id="${esc(id ?? "")}">
      <div class="two">
        <label>Имя<input name="name" value="${esc(a.name)}" required maxlength="40" /></label>
        <label>Значок для уведомлений<input name="emoji" value="${esc(a.emoji)}" required maxlength="16" /></label>
      </div>
      <label>Должность<input name="role" value="${esc(a.role)}" required maxlength="80" placeholder="Например: SMM-менеджер" /></label>
      <label>Инструкции (характер, обязанности, стиль)
        <textarea name="system_prompt" placeholder="Чем занимается, как работает, что важно…">${esc(a.system_prompt)}</textarea></label>
      <div class="two">
        <label>Цвет<input name="color" type="color" value="${esc(a.color)}" /></label>
        <label>Усилие мышления<select name="effort">${efforts}</select></label>
      </div>
      <label>Модель
        <select name="model">
          <option value="">Как у всех (${esc(modelLabel(state.stats.default_model))})</option>
          ${state.models.map((m) => `<option value="${esc(m.id)}" ${a.model === m.id ? "selected" : ""}>${esc(m.label)} · $${m.input}/$${m.output}</option>`).join("")}
          ${a.model && !state.models.some((m) => m.id === a.model) ? `<option selected value="${esc(a.model)}">${esc(a.model)}</option>` : ""}
        </select></label>
      <label class="check"><input type="checkbox" name="web" ${a.web ? "checked" : ""} /> 🌐 Может искать в интернете</label>
      <label class="check"><input type="checkbox" name="can_delegate" ${a.can_delegate ? "checked" : ""} /> 👑 Может раздавать задачи коллегам</label>
      <div class="actions">
        <button class="btn primary" type="submit">Сохранить</button>
        ${id ? `<button class="btn danger" type="button" data-delete-agent="${esc(id)}">Уволить</button>` : ""}
      </div>
    </form>`);
}

$("#sheet-body").addEventListener("submit", async (e) => {
  const form = e.target.closest("#agent-form");
  if (!form) return;
  e.preventDefault();
  const f = new FormData(form);
  const body = {
    name: f.get("name"),
    role: f.get("role"),
    emoji: f.get("emoji"),
    color: f.get("color"),
    system_prompt: f.get("system_prompt"),
    model: f.get("model") || null,
    effort: f.get("effort"),
    web: f.get("web") === "on",
    can_delegate: f.get("can_delegate") === "on",
  };
  try {
    const id = form.dataset.id;
    await api(id ? `/agents/${id}` : "/agents", { method: id ? "PUT" : "POST", body });
    closeSheet();
    toast(id ? "Сохранено" : "Новый сотрудник в офисе!");
    await refresh();
  } catch (err) {
    toast(err.message);
  }
});

$("#sheet-body").addEventListener("click", async (e) => {
  const del = e.target.closest("[data-delete-agent]");
  if (!del) return;
  const a = agentById(del.dataset.deleteAgent);
  if (!confirm(`Уволить ${a?.name}? Его активные задачи будут отменены.`)) return;
  await api(`/agents/${del.dataset.deleteAgent}`, { method: "DELETE" }).catch((err) => toast(err.message));
  closeSheet();
  await refresh();
});

// ---------- PWA ----------

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});

document.querySelectorAll("img[data-icon]").forEach((img) => (img.src = icon(img.dataset.icon)));

// Анимация офиса: 4 кадра в секунду, перерисовываем только столы на экране.
setInterval(() => {
  if (state.tab !== "office" || document.hidden) return;
  deskFrame++;
  drawDesks();
  const clockEl = $("#wall-clock");
  if (clockEl) clockEl.textContent = new Date().toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}, 250);

// Раз в минуту обновляем «5 мин назад» и т.п.
setInterval(() => {
  if (state.tab === "tasks" && !document.activeElement?.closest("#view")) renderView();
}, 60_000);

start();
